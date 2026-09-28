from datetime import datetime
from payrollio.models import PaySchedule, PayrollSalaryProcess, PayrollSalaryComponent

from employeeio.models import Employee

from ..employees import PrivateWeEmployeeDetailsSerializer

from rest_framework import generics, response, decorators, viewsets
from ...serializers.payroll.pay_schedule import (
    PayScheduleListCreateSerializer,
    PayScheduleListUpdateSerializer,
    PayScheduleWithEmployeeCountSerializer,
    PayScheduleAssignedEmployeeDetailsSerializer,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from common.django_rest.helpers.decorators import set_auditlog_actor

from django.db.models import Count, Prefetch, Sum, OuterRef, Subquery, Q, DecimalField

from weapi.django_rest.helpers.payroll_access import (
    PAYROLL_PERMISSION_CLASSES,
    PAYROLL_REQUIRED_FEATURE,
)


class PayScheduleListCreateView(generics.ListCreateAPIView):
    serializer_class = PayScheduleListCreateSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE

    def get_queryset(self):
        return (
            PaySchedule.objects.get_status_active()
            .filter(company=self.request.user.get_active_company())
            .order_by("-created_at")
        )

    def create(self, request, *args, **kwargs):
        serializer = self.serializer_class(
            data=request.data,
            context={"request": self.request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response.Response({"success": True, "message": "created"}, status=201)


class PayScheduleUpdateView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PayScheduleListUpdateSerializer
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE

    def get_object(self):
        return generics.get_object_or_404(
            PaySchedule.objects.all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    # @set_auditlog_actor
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.status = "REMOVED"
        instance.is_default = False
        instance.save()
        return response.Response({"success": True, "message": "Deleted"}, status=200)


class PayScheduleWithEmployeeCountView(generics.ListAPIView):
    serializer_class = PayScheduleWithEmployeeCountSerializer

    def get_queryset(self):
        return (
            PaySchedule.objects.get_status_active()
            .filter(company=self.request.user.get_active_company())
            .annotate(employee_count=Count("employee"))
            .filter(employee_count__gt=0)
            .order_by("-created_at")
        )


class PayScheduleAssignedEmployeeView(generics.GenericAPIView):
    queryset = PaySchedule.objects.all()
    permission_classes = PAYROLL_PERMISSION_CLASSES
    required_feature = PAYROLL_REQUIRED_FEATURE
    serializer_class = PayScheduleAssignedEmployeeDetailsSerializer

    def get(self, request, *args, **kwargs):
        pay_period = request.query_params.get("pay_period")
        if not pay_period:
            return response.Response(
                {"error": True, "message": "Pay period is required"}, status=400
            )

        pay_schedule = self.queryset.filter(
            uid=kwargs.get("schedule_uid"),
            company=self.request.user.get_active_company(),
        ).first()

        start_date, end_date = [
            datetime.strptime(d.strip(), "%m/%d/%Y").date()
            # datetime.strptime(d.strip(), "%Y-%m-%d").date()
            for d in pay_period.split(" to ")
        ]
        # print("start_date", start_date, "end_date", end_date)

        if not pay_schedule:
            return response.Response(
                {"error": True, "message": "Pay schedule not found"}, status=404
            )
        # latest_subquery = (
        #     PayrollSalaryComponent.objects.filter(
        #         payroll=OuterRef("pk"), payroll_type="salary", payroll_category="PAY"
        #     )
        #     .order_by("-id")
        #     .values("current")[:1]
        # )
        # print("[latest_subquery]", latest_subquery)
        employee_qs = pay_schedule.employee_set.select_related(
            "work_locations"
        ).prefetch_related(
            Prefetch(
                "employee_salary",
                queryset=PayrollSalaryProcess.objects.prefetch_related(
                    "payroll_components"
                ),
            ),
        )

        return response.Response(
            {
                "employees": self.serializer_class(
                    employee_qs,
                    many=True,
                    context={"pay_period": (start_date, end_date)},
                ).data,
                "error": False,
            },
            status=200,
        )
