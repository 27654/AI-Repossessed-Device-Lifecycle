"""Login, lockout and MFA-login logic. Views call these; they never touch counters directly."""

import time
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib import auth
from django.utils import timezone

from audit.models import AuditAction
from audit.services import get_client_ip, get_user_agent, log_action

from . import mfa
from .middleware import start_session_clock
from .models import LoginAttempt, User

MFA_PENDING_USER_KEY = "mfa_pending_user_id"
MFA_PENDING_AT_KEY = "mfa_pending_at"

AUTH_BACKEND = "django.contrib.auth.backends.ModelBackend"

Reason = LoginAttempt.FailureReason


@dataclass
class LoginResult:
    user: User | None = None
    mfa_required: bool = False
    failure: str = ""  # a LoginAttempt.FailureReason, empty on success

    @property
    def ok(self):
        return not self.failure


def _record_attempt(request, email, user, failure=""):
    LoginAttempt.objects.create(
        email_attempted=email[:254],
        user=user,
        success=not failure,
        failure_reason=failure,
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
    )


def _register_failure(request, email, user, failure):
    """Record a failed attempt, audit it, and lock the account after too many failures."""
    _record_attempt(request, email, user, failure)
    action = AuditAction.MFA_FAILED if failure == Reason.BAD_MFA_CODE else AuditAction.LOGIN_FAILED
    log_action(
        action,
        request=request,
        user=user,
        user_label=email,
        entity=user,
        entity_type="user",
        description=f"Login failed: {Reason(failure).label}.",
    )

    counts_towards_lockout = failure in (Reason.BAD_CREDENTIALS, Reason.BAD_MFA_CODE)
    if user is None or not counts_towards_lockout:
        return

    user.failed_login_count += 1
    if user.failed_login_count >= settings.LOGIN_LOCKOUT_THRESHOLD:
        user.locked_until = timezone.now() + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
        user.failed_login_count = 0
        log_action(
            AuditAction.ACCOUNT_LOCKED,
            request=request,
            user=user,
            entity=user,
            description=f"Locked for {settings.LOGIN_LOCKOUT_MINUTES} minutes after "
            f"{settings.LOGIN_LOCKOUT_THRESHOLD} failed attempts.",
            new_values={"locked_until": user.locked_until.isoformat()},
        )
    user.save(update_fields=["failed_login_count", "locked_until", "updated_at"])


def _complete_login(request, user, email):
    user.failed_login_count = 0
    user.locked_until = None
    user.save(update_fields=["failed_login_count", "locked_until", "mfa_last_used_step", "updated_at"])
    auth.login(request, user, backend=AUTH_BACKEND)  # rotates the session key and CSRF token
    start_session_clock(request.session)
    _record_attempt(request, email, user)
    log_action(AuditAction.LOGIN, request=request, user=user, entity=user, description="Signed in.")


def attempt_login(request, email, password):
    """First login step: check email and password.

    Returns a LoginResult. On success the user is either fully logged in, or
    (MFA enabled) left in a pending state that `verify_mfa_login` completes.
    """
    email = email.strip().lower()
    user = User.objects.select_related("role").filter(email__iexact=email).first()

    if user is None:
        User().set_password(password)  # same hashing cost as a real check, so timing doesn't reveal accounts
        _register_failure(request, email, None, Reason.BAD_CREDENTIALS)
        return LoginResult(failure=Reason.BAD_CREDENTIALS)
    if user.is_locked:
        _register_failure(request, email, user, Reason.LOCKED)
        return LoginResult(failure=Reason.LOCKED)
    if not user.check_password(password):
        _register_failure(request, email, user, Reason.BAD_CREDENTIALS)
        # This failure may have triggered the lock.
        return LoginResult(failure=Reason.LOCKED if user.is_locked else Reason.BAD_CREDENTIALS)
    if not user.is_active:
        _register_failure(request, email, user, Reason.INACTIVE)
        return LoginResult(failure=Reason.INACTIVE)

    if user.mfa_enabled:
        if request.user.is_authenticated:
            auth.logout(request)
        request.session.cycle_key()
        request.session[MFA_PENDING_USER_KEY] = user.pk
        request.session[MFA_PENDING_AT_KEY] = time.time()
        return LoginResult(user=user, mfa_required=True)

    _complete_login(request, user, email)
    return LoginResult(user=user)


def get_pending_mfa_user(request):
    """The user waiting for MFA verification in this session, or None if absent or expired."""
    user_id = request.session.get(MFA_PENDING_USER_KEY)
    started = request.session.get(MFA_PENDING_AT_KEY, 0)
    if user_id is None or time.time() - started > settings.MFA_PENDING_TIMEOUT:
        clear_pending_mfa(request)
        return None
    return User.objects.select_related("role").filter(pk=user_id).first()


def clear_pending_mfa(request):
    request.session.pop(MFA_PENDING_USER_KEY, None)
    request.session.pop(MFA_PENDING_AT_KEY, None)


def verify_mfa_login(request, user, code):
    """Second login step: check the TOTP code and create the authenticated session."""
    if user.is_locked or not user.is_active:
        clear_pending_mfa(request)
        failure = Reason.LOCKED if user.is_locked else Reason.INACTIVE
        _register_failure(request, user.email, user, failure)
        return LoginResult(failure=failure)

    step = mfa.verify_code(user, code)
    if step is None:
        _register_failure(request, user.email, user, Reason.BAD_MFA_CODE)
        if user.is_locked:
            clear_pending_mfa(request)
            return LoginResult(failure=Reason.LOCKED)
        return LoginResult(failure=Reason.BAD_MFA_CODE)

    user.mfa_last_used_step = step
    clear_pending_mfa(request)
    log_action(AuditAction.MFA_VERIFIED, request=request, user=user, entity=user, description="MFA code accepted at login.")
    _complete_login(request, user, user.email)
    return LoginResult(user=user)
