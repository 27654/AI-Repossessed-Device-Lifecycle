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


def require_permission_by_method(**codes_by_method):
    """Like require_permission, with a different code per HTTP method.

    Usage: `require_permission_by_method(GET=Perm.DEVICE_VIEW, POST=Perm.DEVICE_CREATE)`.
    HEAD and OPTIONS use the GET code. Methods not listed are denied.
    """
    codes = {method.upper(): code for method, code in codes_by_method.items()}

    class MethodPermission(BasePermission):
        message = "Your role does not allow this action."

        def has_permission(self, request, view):
            user = request.user
            if not (user and user.is_authenticated):
                return False
            method = "GET" if request.method in ("HEAD", "OPTIONS") else request.method
            code = codes.get(method)
            return code is not None and user.has_permission_code(code)

    return MethodPermission
