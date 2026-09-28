"""Role + permission overlay management for employees.

Three endpoints:
- POST   /weapi/employees/{uid}/roles                    -> assign roles (additive)
- DELETE /weapi/employees/{uid}/roles/{role_uid}         -> unassign one role
- PUT    /weapi/employees/{uid}/extra-permissions        -> replace overlay

All three require admin (is_admin or is_superuser). The system 'employee' role
cannot be unassigned. Only EMPLOYEE-kind roles from the requester's company are
accepted.
"""

import logging

from django.contrib.auth.models import Permission
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.django_rest.helpers.group_seeds import EMPLOYEE_GROUP_NAME

from adminio.choices import CompanyRoleKindChoices, CompanyRoleStatusChoices
from adminio.models import CompanyRole

from common.django_rest.helpers.crud_logger import CrudAction, crud_log
from common.django_rest.permissions.admin import IsCompanyAdmin

from companyio.models import CompanyUser

from employeeio.models import Employee


logger = logging.getLogger(__name__)


def _get_employee_and_company_user(uid, requester):
    """Resolve (Employee, CompanyUser) for the given employee UID, scoped to the requester's company."""
    company = requester.get_active_company()
    employee = get_object_or_404(Employee, uid=uid, user__companyuser__company=company)
    company_user = CompanyUser.objects.get(user=employee.user, company=company)
    return employee, company_user, company


class EmployeeRoleAssignView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyAdmin]

    def post(self, request, uid):
        role_uids = request.data.get("role_uids") or []
        if not isinstance(role_uids, list) or not role_uids:
            return Response(
                {"error": True, "message": "role_uids (non-empty list) is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        employee, company_user, company = _get_employee_and_company_user(uid, request.user)
        roles = list(
            CompanyRole.objects.filter(
                uid__in=role_uids,
                company=company,
                kind=CompanyRoleKindChoices.EMPLOYEE,
                status=CompanyRoleStatusChoices.ACTIVE,
            )
        )
        if len(roles) != len(set(role_uids)):
            return Response(
                {
                    "error": True,
                    "message": (
                        "One or more roles were not found, do not belong to your company, "
                        "or are not EMPLOYEE-kind."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        before = list(company_user.roles.values_list("name", flat=True))
        company_user.roles.add(*roles)
        crud_log(
            logger,
            CrudAction.ASSIGNED,
            company_user,
            actor=request.user,
            extra={
                "employee_uid": str(employee.uid),
                "added": "[" + ",".join(r.name for r in roles) + "]",
                "before": "[" + ",".join(before) + "]",
            },
        )
        return Response(
            {
                "error": False,
                "message": "Roles assigned.",
                "roles": [{"uid": str(r.uid), "name": r.name} for r in company_user.roles.all()],
            },
            status=status.HTTP_200_OK,
        )


class EmployeeRoleUnassignView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyAdmin]

    def delete(self, request, uid, role_uid):
        employee, company_user, company = _get_employee_and_company_user(uid, request.user)
        role = get_object_or_404(CompanyRole, uid=role_uid, company=company)

        if role.is_system and role.name == EMPLOYEE_GROUP_NAME:
            return Response(
                {
                    "error": True,
                    "message": "The system 'employee' role cannot be unassigned.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        company_user.roles.remove(role)
        crud_log(
            logger,
            CrudAction.REVOKED,
            company_user,
            actor=request.user,
            extra={
                "employee_uid": str(employee.uid),
                "removed": role.name,
            },
        )
        return Response(
            {"error": False, "message": "Role unassigned."},
            status=status.HTTP_200_OK,
        )


class EmployeeExtraPermissionsView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyAdmin]

    def put(self, request, uid):
        permission_ids = request.data.get("permission_ids", None)
        if permission_ids is None or not isinstance(permission_ids, list):
            return Response(
                {"error": True, "message": "permission_ids (list, possibly empty) is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        employee, company_user, _ = _get_employee_and_company_user(uid, request.user)
        before_count = company_user.permission.count()
        new_permissions = Permission.objects.filter(id__in=permission_ids)
        company_user.permission.set(new_permissions)
        crud_log(
            logger,
            CrudAction.PERMISSIONS_CHANGED,
            company_user,
            actor=request.user,
            extra={
                "employee_uid": str(employee.uid),
                "before_count": before_count,
                "after_count": company_user.permission.count(),
            },
        )
        return Response(
            {
                "error": False,
                "message": "Extra permissions updated.",
                "extra_permission_count": company_user.permission.count(),
            },
            status=status.HTTP_200_OK,
        )
