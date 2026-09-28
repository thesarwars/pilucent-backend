from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from rest_framework.permissions import BasePermission

from companyio.models import CompanyUser


class GroupPermissionMixin:
    """Deprecated.

    Use HasCompanyPermission (adminio/django_rest/helpers/group_permissions.py) instead.
    Kept temporarily so that any view still inheriting from it does not crash.
    """

    model = None
    permission_codename = []

    def has_group_permission(self, request, company_uid=None):
        if not (self.model and self.permission_codename):
            return False
        ct = ContentType.objects.get_for_model(self.model)
        permissions = Permission.objects.filter(
            codename__in=self.permission_codename, content_type=ct
        )
        if request.user.is_admin or request.user.is_superuser:
            return any(
                group.permissions.filter(id__in=permissions).exists()
                for group in request.user.groups.all()
            )
        return CompanyUser.objects.filter(
            user__uid=request.user.uid,
            company__uid=company_uid,
            permission__in=permissions,
        ).exists()


class IsSuperAdmin(BasePermission):
    """Allow access if only SuperAdmin"""

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and request.user.is_superuser
        )
