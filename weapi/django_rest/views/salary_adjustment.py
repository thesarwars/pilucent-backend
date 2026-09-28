from rest_framework import filters

from django_filters.rest_framework import DjangoFilterBackend, FilterSet

from rest_framework.generics import (
    RetrieveUpdateDestroyAPIView,
    ListCreateAPIView,
    get_object_or_404,
)

from common.django_rest.helpers.date_range_filters import DateFromToRangeFilter

from payrollio.models import SalaryAdjustment

from payrollio.choicess import SalaryAdjustmentStatusChoices

from ..serializers.salary_adjustment import PrivateWeSalaryAdjustmentListSerializer


class PrivateWeCompanyEmployeeSalaryAdjustmentList(ListCreateAPIView):
    serializer_class = PrivateWeSalaryAdjustmentListSerializer
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
        DateFromToRangeFilter,
    ]
    filterset_fields = [
        "kind",
        "employee__designation__title",
        "employee__department__title",
    ]
    ordering_fields = ["created_at"]
    search_fields = ["employee__user__name", "employee__code", "remark", "amount"]

    def get_queryset(self):
        return SalaryAdjustment.objects.get_status_all().filter(
            employee__user__id__in=self.request.user.get_active_company().companyuser_set.values_list(
                "user_id", flat=True
            )
        ).order_by("-created_at")

    # def get_queryset(self):
    #     queryset = (
    #         SalaryAdjustment.objects.get_status_all()
    #         .select_related(
    #             "employee",
    #             "employee__user",
    #             "employee__designation",
    #             "employee__department",
    #         )
    #         .filter(
    #             employee__user__id__in=self.request.user.get_active_company().companyuser_set.values_list(
    #                 "user_id", flat=True
    #             )
    #         )
    #     )

    #     join_date_from = self.request.query_params.get("join_date_from")
    #     join_date_to = self.request.query_params.get("join_date_to")

    #     if join_date_from:
    #         queryset = queryset.filter(join_date__gte=join_date_from)

    #     if join_date_to:
    #         queryset = queryset.filter(join_date__lte=join_date_to)

    #     return queryset


class PrivateWeCompanyEmployeeSalaryAdjustmentDetail(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeSalaryAdjustmentListSerializer

    def get_object(self):
        queryset = SalaryAdjustment.objects.get_status_all().filter(
            employee__user__id__in=self.request.user.get_active_company().companyuser_set.values_list(
                "user_id", flat=True
            ),
            uid=self.kwargs.get("uid", None),
        )
        return get_object_or_404(queryset)

    def perform_destroy(self, instance):
        instance.status = SalaryAdjustmentStatusChoices.REMOVED
        instance.save()
