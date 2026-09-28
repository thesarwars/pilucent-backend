from rest_framework.generics import (
    RetrieveUpdateAPIView,
    get_object_or_404,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
)
from django_filters.rest_framework import DjangoFilterBackend

from employeeio.models import EmployeeSalary

from employeeio.choices import EmployeeSalaryStatusChoices

from ..serializers.employee_salaries import (
    PrivateWeEmployeeSalaryDetailsSerializer,
    PrivateWeEmployeeBankingInformationDetailsSerializer,
    PrivateWeSalaryListSerializer,
    PrivateWeSalaryDetailsSerializer,
)


class PrivateWeCompanyEmployeeSalaryList(ListCreateAPIView):
    serializer_class = PrivateWeSalaryListSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = [
        "employee__designation__title",
        "employee__department__title",
    ]

    def get_queryset(self):
        return (
            EmployeeSalary.objects.get_status_all()
            .select_related(
                "employee",
                "employee__user",
                "employee__designation",
                "employee__department",
            )
            .filter(
                employee__user__id__in=self.request.user.get_active_company().companyuser_set.values_list(
                    "user_id", flat=True
                )
            )
        )

class PrivateWeEmployeeSalaryDetails(RetrieveUpdateAPIView):
    serializer_class = PrivateWeEmployeeSalaryDetailsSerializer

    def get_object(self):
        return get_object_or_404(
            self.request.user.get_active_company()
            .get_employees()
            .filter(uid=self.kwargs.get("uid"))
        ).get_salary()


class PrivateWeSalaryDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeSalaryDetailsSerializer

    def get_object(self):
        return get_object_or_404(
            EmployeeSalary.objects.select_related(
                "employee",
                "employee__user",
                "employee__designation",
                "employee__department",
            ).filter(
                employee__user__id__in=self.request.user.get_active_company().companyuser_set.values_list(
                    "user_id", flat=True
                )
            ),
            uid=self.kwargs["uid"],
        )

    def perform_destroy(self, instance):
        instance.status = EmployeeSalaryStatusChoices.REMOVED
        instance.save()


class PrivateWeEmployeeBankingInformationDetails(RetrieveUpdateAPIView):
    serializer_class = PrivateWeEmployeeBankingInformationDetailsSerializer

    def get_object(self):
        return get_object_or_404(
            self.request.user.get_active_company()
            .get_employees()
            .filter(uid=self.kwargs.get("uid"))
        ).get_bank_information()
