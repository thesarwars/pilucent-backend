import os
import logging

from rest_framework import filters

from django.db import transaction
from django.db.models import Exists, OuterRef, Prefetch, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, generics, permissions
from rest_framework.generics import CreateAPIView, ListAPIView, get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.models import User
from accounts.choices import UserStatusChoices
from employeeio.choices import EmployeeStatusChoices
from employeeio.models import Employee
from rest_framework_simplejwt.tokens import RefreshToken

from common.django_rest.helpers.tasks import send_email
from common.django_rest.helpers.crud_logger import CrudAction, crud_log

from ..helpers.invitation_token import generate_invitation_token
from ..helpers.login_access import ACCESS_DISABLED_MESSAGE, has_login_access
from ..serializers.user_onboards import (
    UserOnboardSerializer,
    UserListSerializer,
    VerifyInvitationSerializer,
    UserProfileUpdateSerializer,
    UserOnBoardEditDetailsSerializer,
    UserOnBoardDetailsSerializer,
)


logger = logging.getLogger(__name__)


def _coerce_bool(raw):
    return str(raw).lower() in {"1", "true", "yes", "y", "t"}


class UserOnboardCreateView(CreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserOnboardSerializer



class UserOnboardListView(ListAPIView):
    # permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserListSerializer
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["name", "email", "phone"]
    filterset_fields = ["status"]

    def get_queryset(self):
        active_company = self.request.user.get_active_company()
        if active_company is None:
            # companyuser__company=None would match every user with no
            # membership -- a fresh self-signup could list them all.
            return User.objects.none()
        # Two layers of "removed" both have to be excluded:
        #   1. User.status = REMOVED  -> account itself is soft-deleted.
        #   2. Employee.status = REMOVED -> linked HR record is terminated.
        # The inner OR keeps users-without-employees (`employee__isnull=True`)
        # while only including employee-linked users whose Employee is both
        # joined and not removed.
        # Every employee predicate is scoped to the active company: an employee
        # is a per-company record, and a user's record in another company must
        # neither include nor exclude them here (the rendered row is scoped the
        # same way, below).
        employee_here = Employee.objects.filter(user=OuterRef("pk"), company=active_company)
        qs = (
            User.objects.filter(companyuser__company=active_company)
            .exclude(status=UserStatusChoices.REMOVED)
            .filter(
                ~Exists(employee_here)
                | Exists(
                    employee_here.filter(is_joined=True).exclude(
                        status=EmployeeStatusChoices.REMOVED
                    )
                )
            )
            .distinct()
        )

        # ?is_employee=true|false (custom; not a model field on User)
        is_employee = self.request.query_params.get("is_employee")
        if is_employee is not None:
            if _coerce_bool(is_employee):
                qs = qs.filter(Exists(employee_here))
            else:
                qs = qs.filter(~Exists(employee_here))

        # Prefetch the employee row(s) into a list attr the serializer reads,
        # avoiding N+1 across is_employee + employee + designation/department.
        # Mirror the top-level REMOVED exclusion so the serializer never
        # renders a stale terminated-employee row alongside an active user.
        # Scoped to the active company: a user employed by two companies must
        # not show the other company's code, designation or department here.
        employee_qs = (
            Employee.objects.filter(company=active_company)
            .exclude(status=EmployeeStatusChoices.REMOVED)
            .select_related("designation", "department")
            .only(
                "id",
                "uid",
                "user_id",
                "code",
                "status",
                "is_joined",
                "is_access_enabled",
                "designation__title",
                "department__title",
            )
        )
        return qs.prefetch_related(
            Prefetch("employee_set", queryset=employee_qs, to_attr="_employees_for_list"),
            "companyuser_set__roles",
        )


class VerifyInvitationView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        serializer = VerifyInvitationSerializer(data={"token": token})
        # print("token", token)
        if serializer.is_valid():
            # print('worked')
            user = serializer.validated_data["user"]

            # An employee whose login access was revoked (or never granted)
            # cannot use an invitation link to activate and obtain tokens.
            if not has_login_access(user):
                return Response(
                    {"success": False, "message": ACCESS_DISABLED_MESSAGE},
                    status=status.HTTP_403_FORBIDDEN,
                )

            user.status = UserStatusChoices.ACTIVE
            user.is_email_verified = True
            user.save()

            # Accept the most recent pending invitation for this email, creating
            # the membership if it does not already exist. This covers the
            # existing-user / multi-company case where the membership was
            # deferred until acceptance; for brand-new invitees the membership
            # already exists and acceptance is idempotent. Best-effort: a missing
            # or stale invitation must not block activation.
            from companyio.choices import CompanyInvitationStatusChoices
            from companyio.models import CompanyInvitation
            from companyio.django_rest.helpers.invitations import (
                InvitationError,
                accept_invitation,
            )

            pending_invitation = (
                CompanyInvitation.objects.filter(
                    email=user.email,
                    status=CompanyInvitationStatusChoices.PENDING,
                )
                .order_by("-created_at")
                .first()
            )
            if pending_invitation is not None:
                try:
                    accept_invitation(pending_invitation, user, actor=user)
                except InvitationError:
                    logger.info(
                        "Invitation %s could not be auto-accepted on verify for %s",
                        pending_invitation.code,
                        user.email,
                    )

            # Generate JWT tokens for the user
            refresh = RefreshToken.for_user(user)

            return Response(
                {
                    "success": True,
                    "message": "Your account has been activated. Please set your password to continue.",
                    "email": user.email,
                    "access_token": str(refresh.access_token),
                    "refresh_token": str(refresh),
                }
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserOnboardProfileUpdateView(APIView):
    # permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserProfileUpdateSerializer

    def patch(self, request):
        try:
            serializer = UserProfileUpdateSerializer(
                instance=request.user, data=request.data, partial=True
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(
                {
                    "error": False,
                    "message": "Profile updated successfully",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            return Response(
                {"error": True, "message": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )


class UserOnBoardEditDetailsView(APIView):
    # permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = UserOnBoardEditDetailsSerializer

    def get_object(self, uid):
        active_company = self.request.user.get_active_company()
        if active_company is None:
            # companyuser__company=None would match any user with no membership.
            return None
        # The employee record in the active company -- the one this endpoint
        # shows, and the one validate_employee_code compares against.
        employee_qs = Employee.objects.filter(company=active_company).select_related(
            "designation", "department"
        ).only(
            "id",
            "uid",
            "user_id",
            "code",
            "status",
            "is_joined",
            "is_access_enabled",
            "designation__title",
            "department__title",
        )
        return (
            User.objects.filter(uid=uid, companyuser__company=active_company)
            .prefetch_related(
                Prefetch("employee_set", queryset=employee_qs, to_attr="_employees_for_list"),
                "companyuser_set__roles",
                "companyuser_set__permission",
            )
            .first()
        )

    def get(self, request, uid):
        user = self.get_object(uid)
        if not user:
            return Response(
                {"error": True, "message": "User not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = UserOnBoardDetailsSerializer(user)
        return Response(
            {"error": False, "data": serializer.data}, status=status.HTTP_200_OK
        )

    def patch(self, request, uid):
        user = self.get_object(uid)
        if not user:
            return Response(
                {"error": True, "message": "User not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = UserOnBoardEditDetailsSerializer(
            user, data=request.data, partial=True, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save()
            # Return updated user data
            return Response(
                {
                    "error": False,
                    "message": "User details updated successfully",
                    "data": UserListSerializer(user).data,
                }
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @transaction.atomic
    def delete(self, request, uid):
        """Soft-delete the user and cascade to their Employee row(s).

        Universal: works for any user state (DRAFT invitations, ACTIVE
        members, etc.). Both User and any linked Employee are flipped to
        status=REMOVED so the list view (which excludes REMOVED at both
        layers) drops them automatically. The records stay in the DB so
        history, audit logs, and YTD/payroll references remain intact.
        """
        user = self.get_object(uid)
        if not user:
            return Response(
                {"error": True, "message": "User not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        actor = request.user
        company = actor.get_active_company()
        email = user.email

        # Cascade to every Employee row tied to this user. `update()` issues
        # a single UPDATE and bypasses Employee.save(), which is fine here:
        # we're not creating signals-driven side effects, just marking rows
        # as removed.
        employees_removed = Employee.objects.filter(user=user).exclude(
            status=EmployeeStatusChoices.REMOVED
        ).update(status=EmployeeStatusChoices.REMOVED)

        previous_status = user.status
        user.status = UserStatusChoices.REMOVED
        user.save(update_fields=["status"])

        crud_log(
            logger,
            CrudAction.DELETED,
            user,
            actor=actor,
            extra={
                "flow": "user_onboard",
                "company": company.name if company else None,
                "email": email,
                "previous_status": previous_status,
                "employees_removed": employees_removed,
                "soft_delete": True,
            },
        )
        return Response(
            {
                "error": False,
                "message": "User removed.",
                "employees_removed": employees_removed,
            },
            status=status.HTTP_200_OK,
        )


class UserOnboardResendInviteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, uid):
        active_company = request.user.get_active_company()
        if active_company is None:
            return Response(
                {"error": True, "message": "No active company for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(
            uid=uid, companyuser__company=active_company
        ).first()
        if not user:
            return Response(
                {"error": True, "message": "User not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if user.status != UserStatusChoices.DRAFT or user.is_email_verified:
            return Response(
                {
                    "error": True,
                    "message": "Invitation can only be resent to pending users.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        invitation_token = generate_invitation_token(user.email)
        frontend_url = os.environ.get("BASE_FRONTEND_URL", "http://localhost:3000")
        verification_link = f"{frontend_url}/auth/verify-invitation/{invitation_token}"

        send_email(
            {
                "invitation_link": verification_link,
                "user_name": user.name,
                "company": active_company,
            },
            "emails/onboard/user_invitation.html",
            user.email,
            "Invitation to join Balanzify",
        )

        crud_log(
            logger,
            CrudAction.INVITED,
            user,
            actor=request.user,
            extra={
                "flow": "user_onboard_resend",
                "company": active_company.name,
            },
        )

        return Response(
            {"error": False, "message": "Invitation resent successfully."},
            status=status.HTTP_200_OK,
        )
