"""Permission classes for company-scoped CRUD and custom-action endpoints.

`HasCompanyPermission` is the canonical permission class. `IsGroupPermission`
remains as a deprecation alias so the existing 250+ usages do not need to be
touched in one PR.

How a request is granted:
1. Superuser  -> always allowed.
2. `is_admin`  -> always allowed (admin of own company).
3. The required permission is looked up from either:
   - HTTP method (GET=view, POST=add, PUT/PATCH=change, DELETE=delete) on the
     view's model, OR
   - the view's `required_permissions = ["expense.approve", ...]` attribute
     (custom action codenames, useful for non-CRUD endpoints).
4. The request user must hold the required permission via either:
   - any of their Django Groups, OR
   - one of their CompanyRoles (in the active company), OR
   - their per-CompanyUser permission overlay.
5. `has_object_permission` additionally enforces that the object's `company`
   matches the requester's active company (when both are present).
"""

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from rest_framework.permissions import BasePermission

from companyio.models import CompanyUser


SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
METHOD_PERMISSION_MAP = {
    "GET": "view",
    "POST": "add",
    "PUT": "change",
    "PATCH": "change",
    "DELETE": "delete",
}


def _resolve_required_permissions(view, request):
    """Return a list of Permission rows the request needs to hold.

    Empty list means: no Permission row exists for this combination, so the
    permission check should fail closed (return False) rather than crash.
    """
    explicit = getattr(view, "required_permissions", None)
    if explicit:
        codenames = list(explicit)
        return list(Permission.objects.filter(codename__in=codenames))

    if getattr(view, "queryset", None) is not None:
        model = view.queryset.model
    elif hasattr(view, "serializer_class"):
        model = getattr(view.serializer_class.Meta, "model", None)
    else:
        model = None
    if model is None:
        return []

    action = METHOD_PERMISSION_MAP.get(request.method)
    if action is None:
        return []

    codename = f"{action}_{model._meta.model_name}"
    ct = ContentType.objects.get_for_model(model)
    perm = Permission.objects.filter(codename=codename, content_type=ct).first()
    return [perm] if perm else []


class HasCompanyPermission(BasePermission):
    """Grant access if the user holds the required permission via group, role, or overlay."""

    message = "Your role doesn't have power for this action, gain power and try again."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or getattr(user, "is_admin", False):
            return True

        required = _resolve_required_permissions(view, request)
        if not required:
            return False

        required_ids = [p.id for p in required]

        # Django group permissions
        if user.groups.filter(permissions__id__in=required_ids).exists():
            return True

        # CompanyRole + per-CompanyUser overlay
        return (
            CompanyUser.objects.filter(
                user=user,
                company=user.get_active_company(),
            )
            .filter(
                Q(roles__permission__id__in=required_ids)
                | Q(permission__id__in=required_ids)
            )
            .exists()
        )

    def has_object_permission(self, request, view, obj):
        """Cross-company isolation: object must belong to the requester's active company.

        Only enforced when the object actually has a `company` attribute. Models
        that aren't company-scoped (e.g. user-private records) are not affected.
        """
        user = request.user
        if user.is_superuser:
            return True
        obj_company = getattr(obj, "company", None) or getattr(obj, "company_id", None)
        if obj_company is None:
            return True
        active = user.get_active_company()
        if active is None:
            return False
        return getattr(obj_company, "id", obj_company) == active.id


# Deprecation alias. Prefer HasCompanyPermission in new code. Existing imports of
# `IsGroupPermission` continue to work; this alias may be removed in a later PR.
IsGroupPermission = HasCompanyPermission
