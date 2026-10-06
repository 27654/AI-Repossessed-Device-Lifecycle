from rest_framework.permissions import BasePermission


def require_permission(*codes):
    """DRF permission class granting access when the user's role has every given code.

    Usage: `permission_classes = [require_permission(Perm.USER_MANAGE)]`.
    Unauthenticated requests get 401, authenticated users without the
    permission get 403.
    """

    class RequiredPermission(BasePermission):
        message = "Your role does not allow this action."

        def has_permission(self, request, view):
            user = request.user
            return bool(user and user.is_authenticated and user.has_permission_code(*codes))

    RequiredPermission.__name__ = f"RequiredPermission({', '.join(codes)})"
    return RequiredPermission
