from datetime import datetime
from payrollio.models import PaySchedule, PayrollSalaryProcess, PayrollSalaryComponent

from employeeio.models import Employee

from rest_framework import generics, response, decorators, viewsets
from ...serializers.payroll.pay_schedule import (
    PayScheduleListCreateSerializer,
    PayScheduleListUpdateSerializer,
    PayScheduleWithEmployeeCountSerializer,
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
