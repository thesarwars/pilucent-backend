import logging
import uuid

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Prefetch

from rest_framework import status, generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from adminio.django_rest.serializers.user_roles import (
    RoleListSerializer,
    RoleModifySerializer,
    RoleSlimSerializer,
    RoleSerializer,
)
from adminio.models import CompanyRole

from common.django_rest.helpers.crud_logger import CrudAction, crud_log
from common.django_rest.helpers.custome_pagination import CustomPageNumberPagination
from common.django_rest.permissions.admin import IsCompanyAdmin

from companyio.models import CompanyUser


logger = logging.getLogger(__name__)


class RoleCreateView(APIView):
    serializer_class = RoleSerializer
    permission_classes = [IsGroupPermission]

    def post(self, request):
        actor = getattr(request.user, "email", request.user)
        logger.debug("RoleCreateView.post invoked by=%s", actor)
        try:
            serializer = self.serializer_class(data=request.data, context={"request": request})
            if serializer.is_valid():
                serializer.save()
                # Success log is emitted inside RoleSerializer.create via crud_log
                return Response(
                    {"message": "role created", "error": False},
                    status.HTTP_201_CREATED,
                )
            logger.warning(
                "RoleCreateView.post validation failed by=%s errors=%s",
                actor,
                dict(serializer.errors),
            )
            return Response({"message": serializer.errors}, status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("RoleCreateView.post unexpected error by=%s", actor)
            return Response(str(e), status.HTTP_400_BAD_REQUEST)


class RoleView(APIView):
    """List CompanyRoles for a company.

    Supported query params (all optional, AND-combined):
    - uid:       role UUID (exact match)
    - kind:      USER | EMPLOYEE       (e.g. ?kind=EMPLOYEE)
    - status:    ACTIVE | INACTIVE | REMOVED
    - is_system: true | false
    - name:      exact match (case-insensitive)
    """

    queryset = CompanyRole.objects.all()
    serializer_class = RoleListSerializer
    permission_classes = [IsGroupPermission]

    @staticmethod
    def _coerce_bool(raw):
        return str(raw).lower() in {"1", "true", "yes", "y", "t"}

    def get(self, request, company_uid):
        try:
            queryset = self.queryset.filter(company__uid=company_uid)

            # Manual query-param filtering. APIView does not run DRF's
            # DjangoFilterBackend pipeline, so `filterset_fields` would be a
            # no-op here. Switch to ListAPIView if you want the auto-filtering
            # (note: that also enables global pagination).
            uid = request.query_params.get("role_uid")
            if uid:
                try:
                    queryset = queryset.filter(uid=uuid.UUID(str(uid)))
                except (ValueError, TypeError):
                    return Response(
                        {"message": "uid must be a valid UUID."},
                        status.HTTP_400_BAD_REQUEST,
                    )

            kind = request.query_params.get("kind")
            if kind:
                queryset = queryset.filter(kind=kind.upper())

            status_param = request.query_params.get("status")
            if status_param:
                queryset = queryset.filter(status=status_param.upper())

            is_system = request.query_params.get("is_system")
            if is_system is not None:
                queryset = queryset.filter(is_system=self._coerce_bool(is_system))

            name = request.query_params.get("name")
            if name:
                queryset = queryset.filter(name__iexact=name)

            queryset = queryset.prefetch_related(
                Prefetch(
                    "company_users",
                    # Include every User field that UserSerializer renders,
                    # otherwise Django defers them and re-queries per row.
                    queryset=CompanyUser.objects.select_related("user").only(
                        "user__uid",
                        "user__email",
                        "user__name",
                        "user__image",
                    ),
                    to_attr="assigned_users",
                ),
                Prefetch(
                    "permission",
                    queryset=Permission.objects.select_related("content_type"),
                    to_attr="permissions_list",
                ),
            )
            serializer = self.serializer_class(queryset, many=True)
            return Response(serializer.data, status.HTTP_200_OK)
        except Exception as e:
            logger.exception(
                "RoleView.get unexpected error company_uid=%s by=%s",
                company_uid,
                getattr(request.user, "email", request.user),
            )
            return Response(str(e), status.HTTP_400_BAD_REQUEST)


class RoleModify(APIView):
    queryset = CompanyRole.objects.all()
    serializer_class = RoleModifySerializer
    permission_classes = [IsGroupPermission]

    def patch(self, request):
        actor = getattr(request.user, "email", request.user)
        company_uid = request.data.get("company_uid")
        role_uid = request.data.get("uid")
        logger.debug(
            "RoleModify.patch invoked by=%s company_uid=%s role_uid=%s",
            actor,
            company_uid,
            role_uid,
        )
        if not company_uid or not role_uid:
            logger.warning(
                "RoleModify.patch missing required fields by=%s payload_keys=%s",
                actor,
                list(request.data.keys()),
            )
            return Response(
                {"message": "company_uid and uid are required."},
                status.HTTP_400_BAD_REQUEST,
            )
        try:
            queryset = self.queryset.get(uid=role_uid, company__uid=company_uid)
        except CompanyRole.DoesNotExist:
            logger.warning(
                "RoleModify.patch role not found by=%s company_uid=%s role_uid=%s",
                actor,
                company_uid,
                role_uid,
            )
            return Response(
                {"message": "Role not found in the given company."},
                status.HTTP_404_NOT_FOUND,
            )
        try:
            serializer = self.serializer_class(
                instance=queryset,
                data=request.data,
                partial=True,
                context={"request": request},
            )
            if serializer.is_valid():
                serializer.save()
                # Success log is emitted inside RoleModifySerializer.update via crud_log
                return Response(
                    {"message": "Role modified successfully"}, status.HTTP_200_OK
                )
            logger.warning(
                "RoleModify.patch validation failed by=%s role_uid=%s errors=%s",
                actor,
                role_uid,
                dict(serializer.errors),
            )
            return Response({"message": serializer.errors}, status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception(
                "RoleModify.patch unexpected error by=%s role_uid=%s",
                actor,
                role_uid,
            )
            return Response(str(e), status.HTTP_400_BAD_REQUEST)


class RoleBulkDeleteView(APIView):
    """Delete multiple custom CompanyRoles in one request.

    Payload:
    - role_uids: ["uuid", ...]

    Behavior:
    - All-or-nothing: if any uid is invalid, missing, out-of-company, or system,
      nothing is deleted and an error is returned.
    """

    queryset = CompanyRole.objects.all()
    permission_classes = [IsCompanyAdmin]

    def delete(self, request):
        active_company = request.user.get_active_company()
        if active_company is None:
            return Response(
                {"error": True, "message": "No active company for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        role_uids = request.data.get("role_uids") or []
        if not isinstance(role_uids, list) or not role_uids:
            return Response(
                {"error": True, "message": "role_uids (non-empty list) is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            requested_uids = [uuid.UUID(str(raw)) for raw in role_uids]
        except (ValueError, TypeError):
            return Response(
                {"error": True, "message": "role_uids must be a list of UUIDs."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        unique_uids = list(dict.fromkeys(requested_uids))
        roles = list(self.queryset.filter(uid__in=unique_uids, company=active_company))
        if len(roles) != len(unique_uids):
            return Response(
                {
                    "error": True,
                    "message": "One or more roles were not found in your company.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        system_roles = [r for r in roles if r.is_system]
        if system_roles:
            return Response(
                {
                    "error": True,
                    "message": (
                        f"System role '{system_roles[0].name}' cannot be deleted. "
                        f"Use modify to change its permissions instead."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        total_affected_users = 0
        snapshots = []
        for role in roles:
            affected = role.company_users.count()
            total_affected_users += affected
            snapshots.append(
                {
                    "uid": str(role.uid),
                    "name": role.name,
                    "kind": role.kind,
                    "company": active_company.name,
                    "affected_users": affected,
                }
            )

        try:
            with transaction.atomic():
                for role in roles:
                    role.delete()
        except DjangoValidationError as exc:
            return Response(
                {"error": True, "message": str(exc.messages[0] if exc.messages else exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for snapshot in snapshots:
            crud_log(
                logger,
                CrudAction.DELETED,
                type(
                    "Deleted",
                    (),
                    {"_meta": CompanyRole._meta, "uid": snapshot["uid"], "pk": None},
                )(),
                actor=request.user,
                extra={
                    "name": snapshot["name"],
                    "kind": snapshot["kind"],
                    "company": snapshot["company"],
                    "affected_users": snapshot["affected_users"],
                },
            )

        return Response(
            {
                "error": False,
                "message": "Roles deleted.",
                "deleted_count": len(roles),
                "affected_users": total_affected_users,
            },
            status=status.HTTP_200_OK,
        )


class RoleSlimViewAPI(generics.ListAPIView):
    queryset = CompanyRole.objects.all()
    serializer_class = RoleSlimSerializer
    permission_classes = [IsGroupPermission]
    pagination_class = CustomPageNumberPagination

    def get_queryset(self):
        company_uid = self.kwargs.get("company_uid")
        queryset = self.queryset.filter(company__uid=company_uid).only(
            "uid", "name", "kind", "is_system"
        )

        kind = self.request.query_params.get("kind")
        if kind:
            queryset = queryset.filter(kind=str(kind).upper())

        return queryset.order_by("name")
