from rest_framework.permissions import BasePermission


class IsCompanyAdmin(BasePermission):
    """Allow only company admins (`is_admin`) or superusers.

    Use for destructive or sensitive operations (deleting roles, reassigning
    permissions, etc.) where the broader `HasCompanyPermission` check would
    let any user holding the matching CRUD permission through.
    """

    message = "Only company admins can perform this action."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.is_superuser or getattr(user, "is_admin", False))
        )
