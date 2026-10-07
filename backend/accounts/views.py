from django.contrib import auth
from django.contrib.auth import update_session_auth_hash
from django.db import transaction
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from audit.models import AuditAction
from audit.services import log_action

from . import mfa, services
from .authentication import enforce_csrf
from .models import LoginAttempt, Permission, Role, User
from .permissions import require_permission
from .rbac import Perm, RoleCode
from .serializers import (
    AdminSetPasswordSerializer,
    ChangePasswordSerializer,
    CurrentUserSerializer,
    LoginAttemptSerializer,
    LoginSerializer,
    MfaCodeSerializer,
    MfaDisableSerializer,
    PermissionSerializer,
    RoleSerializer,
    UserSerializer,
)

Reason = LoginAttempt.FailureReason

LOGIN_FAILURE_RESPONSES = {
    Reason.BAD_CREDENTIALS: (status.HTTP_401_UNAUTHORIZED, "Invalid email or password."),
    Reason.BAD_MFA_CODE: (status.HTTP_401_UNAUTHORIZED, "Invalid or expired verification code."),
    Reason.LOCKED: (status.HTTP_403_FORBIDDEN, "Too many failed attempts. The account is temporarily locked."),
    Reason.INACTIVE: (status.HTTP_403_FORBIDDEN, "This account is not active. Contact your system administrator."),
}

# Fields compared when auditing user updates. Password and MFA secret are never included.
AUDITED_USER_FIELDS = ["full_name", "email", "phone", "employee_id", "account_status"]


def _login_failure(result):
    code, message = LOGIN_FAILURE_RESPONSES[result.failure]
    return Response({"detail": message, "code": result.failure.lower()}, status=code)


# --- Authentication ---------------------------------------------------------


@api_view(["GET"])
@permission_classes([AllowAny])
def csrf(request):
    """Sets the CSRF cookie so the SPA can send the X-CSRFToken header."""
    get_token(request)
    return Response({"detail": "CSRF cookie set."})


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    enforce_csrf(request)
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    result = services.attempt_login(request, **serializer.validated_data)

    if not result.ok:
        return _login_failure(result)
    if result.mfa_required:
        return Response({"mfa_required": True})
    return Response({"mfa_required": False, "user": CurrentUserSerializer(result.user).data})


@api_view(["POST"])
@permission_classes([AllowAny])
def mfa_verify(request):
    enforce_csrf(request)
    user = services.get_pending_mfa_user(request)
    if user is None:
        return Response(
            {"detail": "No sign-in is waiting for verification. Sign in again.", "code": "mfa_not_pending"},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    serializer = MfaCodeSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    result = services.verify_mfa_login(request, user, serializer.validated_data["code"])

    if not result.ok:
        return _login_failure(result)
    return Response({"user": CurrentUserSerializer(result.user).data})


@api_view(["POST"])
def logout(request):
    log_action(AuditAction.LOGOUT, request=request, entity=request.user, description="Signed out.")
    auth.logout(request)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
def me(request):
    return Response(CurrentUserSerializer(request.user).data)


@api_view(["POST"])
def change_password(request):
    serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    user = request.user

    if not user.check_password(serializer.validated_data["current_password"]):
        log_action(
            AuditAction.PASSWORD_CHANGE_FAILED,
            request=request,
            entity=user,
            description="Password change rejected: current password incorrect.",
        )
        return Response({"current_password": ["Current password is incorrect."]}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(serializer.validated_data["new_password"])
    user.save()
    update_session_auth_hash(request, user)  # keep this session; other sessions are invalidated
    log_action(AuditAction.PASSWORD_CHANGED, request=request, entity=user, description="Password changed by the user.")
    return Response({"detail": "Password changed."})


# --- MFA enrolment ----------------------------------------------------------


@api_view(["POST"])
def mfa_setup(request):
    """Start enrolment: create a new secret and return it once for the authenticator app."""
    user = request.user
    if user.mfa_enabled:
        return Response({"detail": "MFA is already enabled."}, status=status.HTTP_400_BAD_REQUEST)

    secret = mfa.generate_secret()
    user.mfa_secret = mfa.encrypt_secret(secret)
    user.mfa_last_used_step = None
    user.save(update_fields=["mfa_secret", "mfa_last_used_step", "updated_at"])
    log_action(AuditAction.MFA_SETUP_STARTED, request=request, entity=user, description="MFA enrolment started.")
    return Response({"secret": secret, "otpauth_uri": mfa.provisioning_uri(secret, user.email)})


@api_view(["POST"])
def mfa_confirm(request):
    """Finish enrolment by proving the authenticator app produces valid codes."""
    user = request.user
    if user.mfa_enabled or not user.mfa_secret:
        return Response({"detail": "Start MFA setup first."}, status=status.HTTP_400_BAD_REQUEST)
    serializer = MfaCodeSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    step = mfa.verify_code(user, serializer.validated_data["code"])
    if step is None:
        log_action(AuditAction.MFA_FAILED, request=request, entity=user, description="Invalid code during MFA setup.")
        return Response({"code": ["Invalid verification code."]}, status=status.HTTP_400_BAD_REQUEST)

    user.mfa_enabled = True
    user.mfa_last_used_step = step
    user.save(update_fields=["mfa_enabled", "mfa_last_used_step", "updated_at"])
    log_action(
        AuditAction.MFA_ENABLED,
        request=request,
        entity=user,
        description="MFA enabled.",
        previous_values={"mfa_enabled": False},
        new_values={"mfa_enabled": True},
    )
    return Response(CurrentUserSerializer(user).data)


@api_view(["POST"])
def mfa_disable(request):
    user = request.user
    if not user.mfa_enabled:
        return Response({"detail": "MFA is not enabled."}, status=status.HTTP_400_BAD_REQUEST)
    serializer = MfaDisableSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    step = mfa.verify_code(user, serializer.validated_data["code"])
    if not user.check_password(serializer.validated_data["password"]) or step is None:
        log_action(AuditAction.MFA_FAILED, request=request, entity=user, description="MFA disable rejected.")
        return Response({"detail": "Password or verification code is incorrect."}, status=status.HTTP_400_BAD_REQUEST)

    user.mfa_enabled = False
    user.mfa_secret = ""
    user.mfa_last_used_step = None
    user.save(update_fields=["mfa_enabled", "mfa_secret", "mfa_last_used_step", "updated_at"])
    log_action(
        AuditAction.MFA_DISABLED,
        request=request,
        entity=user,
        description="MFA disabled by the user.",
        previous_values={"mfa_enabled": True},
        new_values={"mfa_enabled": False},
    )
    return Response(CurrentUserSerializer(user).data)


# --- User and role management (System Administrator) -------------------------


class UserListCreateView(generics.ListCreateAPIView):
    permission_classes = [require_permission(Perm.USER_MANAGE)]
    serializer_class = UserSerializer
    queryset = User.objects.select_related("role")

    @transaction.atomic
    def perform_create(self, serializer):
        user = serializer.save()
        log_action(
            AuditAction.USER_CREATED,
            request=self.request,
            entity=user,
            description=f"Created user {user.email} with role {user.role.name}.",
            new_values={**{f: getattr(user, f) for f in AUDITED_USER_FIELDS}, "role": user.role.code},
        )


class UserDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [require_permission(Perm.USER_MANAGE)]
    serializer_class = UserSerializer
    queryset = User.objects.select_related("role")
    http_method_names = ["get", "patch", "head", "options"]

    @transaction.atomic
    def perform_update(self, serializer):
        user = serializer.instance
        before = {f: getattr(user, f) for f in AUDITED_USER_FIELDS}
        old_role = user.role

        if user.pk == self.request.user.pk:
            new_status = serializer.validated_data.get("account_status", user.account_status)
            new_role = serializer.validated_data.get("role", old_role)
            if new_status != User.Status.ACTIVE or new_role != old_role:
                raise ValidationError({"detail": "You cannot change your own role or account status."})

        user = serializer.save()
        after = {f: getattr(user, f) for f in AUDITED_USER_FIELDS}
        changed = [f for f in AUDITED_USER_FIELDS if before[f] != after[f]]
        if changed:
            log_action(
                AuditAction.USER_UPDATED,
                request=self.request,
                entity=user,
                description=f"Updated {', '.join(changed)} for {user.email}.",
                previous_values={f: before[f] for f in changed},
                new_values={f: after[f] for f in changed},
            )
        if user.role != old_role:
            log_action(
                AuditAction.USER_ROLE_CHANGED,
                request=self.request,
                entity=user,
                description=f"Role of {user.email} changed to {user.role.name}.",
                previous_values={"role": old_role.code if old_role else None},
                new_values={"role": user.role.code},
            )


@api_view(["POST"])
@permission_classes([require_permission(Perm.USER_MANAGE)])
def user_reset_password(request, pk):
    """Administrator sets a temporary password. Ends the user's existing sessions."""
    user = get_object_or_404(User, pk=pk)
    serializer = AdminSetPasswordSerializer(data=request.data, context={"target_user": user})
    serializer.is_valid(raise_exception=True)
    user.set_password(serializer.validated_data["new_password"])
    user.failed_login_count = 0
    user.locked_until = None
    user.save()
    log_action(AuditAction.PASSWORD_RESET, request=request, entity=user, description=f"Password reset for {user.email}.")
    return Response({"detail": "Password reset."})


@api_view(["POST"])
@permission_classes([require_permission(Perm.USER_MANAGE)])
def user_reset_mfa(request, pk):
    """Administrator removes MFA, e.g. when a user loses their phone."""
    user = get_object_or_404(User, pk=pk)
    was_enabled = user.mfa_enabled
    user.mfa_enabled = False
    user.mfa_secret = ""
    user.mfa_last_used_step = None
    user.save(update_fields=["mfa_enabled", "mfa_secret", "mfa_last_used_step", "updated_at"])
    log_action(
        AuditAction.MFA_DISABLED,
        request=request,
        entity=user,
        description=f"MFA reset for {user.email} by administrator.",
        previous_values={"mfa_enabled": was_enabled},
        new_values={"mfa_enabled": False},
    )
    return Response(UserSerializer(user).data)


@api_view(["POST"])
@permission_classes([require_permission(Perm.USER_MANAGE)])
def user_unlock(request, pk):
    """Administrator lifts a failed-login lockout before it expires."""
    user = get_object_or_404(User, pk=pk)
    previous = {
        "locked_until": user.locked_until.isoformat() if user.locked_until else None,
        "failed_login_count": user.failed_login_count,
    }
    user.locked_until = None
    user.failed_login_count = 0
    user.save(update_fields=["locked_until", "failed_login_count", "updated_at"])
    log_action(
        AuditAction.ACCOUNT_UNLOCKED,
        request=request,
        entity=user,
        description=f"Account {user.email} unlocked by administrator.",
        previous_values=previous,
        new_values={"locked_until": None, "failed_login_count": 0},
    )
    return Response(UserSerializer(user).data)


class LoginAttemptListView(generics.ListAPIView):
    """Login history for security monitoring. Filters: email, user, success (true/false)."""

    permission_classes = [require_permission(Perm.AUDIT_VIEW)]
    serializer_class = LoginAttemptSerializer

    def get_queryset(self):
        qs = LoginAttempt.objects.all()
        params = self.request.query_params
        if params.get("email"):
            qs = qs.filter(email_attempted__iexact=params["email"].strip())
        if params.get("user", "").isdigit():
            qs = qs.filter(user_id=params["user"])
        if params.get("success") in ("true", "false"):
            qs = qs.filter(success=params["success"] == "true")
        return qs


class RoleListView(generics.ListAPIView):
    permission_classes = [require_permission(Perm.USER_MANAGE)]
    serializer_class = RoleSerializer
    queryset = Role.objects.prefetch_related("permissions")
    pagination_class = None


class RoleDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [require_permission(Perm.ROLE_MANAGE)]
    serializer_class = RoleSerializer
    queryset = Role.objects.prefetch_related("permissions")
    http_method_names = ["get", "patch", "head", "options"]

    # The administrator role must keep these, or nobody could manage access any more.
    PROTECTED_ADMIN_PERMISSIONS = {Perm.USER_MANAGE, Perm.ROLE_MANAGE}

    @transaction.atomic
    def perform_update(self, serializer):
        role = serializer.instance
        before = sorted(role.permissions.values_list("code", flat=True))
        before_details = {f: getattr(role, f) for f in ("name", "description")}
        if role.code == RoleCode.SYSTEM_ADMIN and "permissions" in serializer.validated_data:
            new_codes = {p.code for p in serializer.validated_data["permissions"]}
            if not self.PROTECTED_ADMIN_PERMISSIONS <= new_codes:
                raise ValidationError({"permissions": "The System Administrator role must keep user.manage and role.manage."})

        role = serializer.save()
        after = sorted(role.permissions.values_list("code", flat=True))
        changed = [f for f in before_details if getattr(role, f) != before_details[f]]
        if changed:
            log_action(
                AuditAction.ROLE_UPDATED,
                request=self.request,
                entity=role,
                description=f"Updated {', '.join(changed)} of role {role.code}.",
                previous_values={f: before_details[f] for f in changed},
                new_values={f: getattr(role, f) for f in changed},
            )
        if before != after:
            log_action(
                AuditAction.ROLE_PERMISSIONS_CHANGED,
                request=self.request,
                entity=role,
                description=f"Permissions of role {role.name} changed.",
                previous_values={"permissions": before},
                new_values={"permissions": after},
            )


class PermissionListView(generics.ListAPIView):
    permission_classes = [require_permission(Perm.ROLE_MANAGE)]
    serializer_class = PermissionSerializer
    queryset = Permission.objects.all()
    pagination_class = None
