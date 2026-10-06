import time

from django.conf import settings
from django.contrib.auth import logout

from audit.models import AuditAction
from audit.services import log_action

SESSION_STARTED_KEY = "auth_started_at"
SESSION_LAST_ACTIVITY_KEY = "auth_last_activity"

# Write the activity timestamp at most once a minute to avoid a session save per request.
ACTIVITY_WRITE_INTERVAL = 60


def start_session_clock(session):
    now = time.time()
    session[SESSION_STARTED_KEY] = now
    session[SESSION_LAST_ACTIVITY_KEY] = now


class SessionTimeoutMiddleware:
    """Ends authenticated sessions after inactivity or a maximum lifetime.

    Idle limit: SESSION_IDLE_TIMEOUT. Absolute limit: SESSION_COOKIE_AGE,
    counted from login (the cookie expiry alone would slide with activity).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            session = request.session
            now = time.time()
            if SESSION_STARTED_KEY not in session:
                start_session_clock(session)
            else:
                idle = now - session.get(SESSION_LAST_ACTIVITY_KEY, now)
                age = now - session[SESSION_STARTED_KEY]
                if idle > settings.SESSION_IDLE_TIMEOUT or age > settings.SESSION_COOKIE_AGE:
                    reason = "inactivity" if idle > settings.SESSION_IDLE_TIMEOUT else "maximum session length"
                    log_action(
                        AuditAction.SESSION_EXPIRED,
                        request=request,
                        user=user,
                        entity=user,
                        description=f"Session ended after {reason}.",
                    )
                    logout(request)
                elif idle > ACTIVITY_WRITE_INTERVAL:
                    session[SESSION_LAST_ACTIVITY_KEY] = now
        return self.get_response(request)
