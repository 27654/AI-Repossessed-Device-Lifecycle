from rest_framework import authentication


class SessionAuthentication(authentication.SessionAuthentication):
    """DRF session authentication that answers 401 (not 403) when not logged in.

    DRF only returns 401 when the authenticator supplies a WWW-Authenticate
    challenge. Browsers do not prompt for the custom "Session" scheme.
    """

    def authenticate_header(self, request):
        return "Session"


def enforce_csrf(request):
    """Run Django's CSRF check on an anonymous request (login, MFA verify).

    DRF only checks CSRF for session-authenticated users, which would leave
    the login endpoints open to login CSRF.
    """
    authentication.SessionAuthentication().enforce_csrf(request)
