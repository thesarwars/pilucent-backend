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


class IsActiveCompanyAdmin(BasePermission):
    """Allow only an admin *of the active company* (or a superuser).

    `IsCompanyAdmin` reads the user-global `is_admin` flag, which every self or
    Google signup sets -- so a user who owns one company passes it inside any
    other company they were merely invited to. This asks the company itself:
    the caller's membership in the active company must hold that company's
    seeded system admin role (the same rule the workspace picker uses to mark
    an owner, accounts.django_rest.helpers.workspace._company_user_is_owner).
    """

    message = "Only an admin of this company can perform this action."

    def has_permission(self, request, view):
        from accounts.django_rest.helpers.group_seeds import ADMIN_GROUP_NAME
        from companyio.models import CompanyUser

        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        company = user.get_active_company()
        if company is None:
            return False
        return CompanyUser.objects.filter(
            user=user,
            company=company,
            roles__company=company,
            roles__name=ADMIN_GROUP_NAME,
            roles__is_system=True,
        ).exists()
