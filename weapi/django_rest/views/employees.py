from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters, response, status

from rest_framework.generics import (
    ListCreateAPIView,
    ListAPIView,
    CreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from django.http import HttpResponse

from openpyxl import Workbook
from io import BytesIO
import pandas as pd


from common.django_rest.permissions.company_subscription import HaveSubscription

from fileroomio.models import FileItem

from django.db.models import Prefetch

from employeeio.models import (
    Employee,
    EmployeeEducation,
    EmployeeBankingInformation,
    EmployeeTax,
    EmployeeEarning,
    EmployeeDeductionContribution,
    EmployeeGarnishment,
    EmployeeWorkExperience,
)

from payrollio.models import PayrollSalaryProcess

from ..serializers.employees import (
    PrivateWeEmployeeListSerializer,
    PrivateWeEmployeeDetailsSerializer,
    PrivateWeEmployeeEducationListSerializer,
    PrivateWeEmployeeEducationDetailsSerializer,
    PrivateWeEmployeeBankingInformationListSerializer,
    PrivateWeEmployeeBankingInformationDetailsSerializer,
    PrivateWeEmployeeTaxListSerializer,
    PrivateWeEmployeeTaxDetailsSerializer,
    PrivateWeEmployeeEarningListSerializer,
    PrivateWeEmployeeEarningDetilsSerializer,
    PrivateWeEmployeeDeductionContributionListSerializer,
    PrivateWeEmployeeDeductionContributionDetailsSerializer,
    PrivateWeEmployeeGarnishmentListSerializer,
    PrivateWeEmployeeGarnishmentDetailsSerializer,
    PrivateWeEmployeeWorkExperienceListSerializer,
    PrivateWeEmployeeWorkExperienceDetailsSerializer,
    PrivateWeEmployeeDocuementListSerializer,
    PrivateWeEmployeeDocuementDetailsSerializer,
    PrivateWeEmployeeListAllSerializer,
)


class PrivateWeEmployeeList(ListCreateAPIView):
    serializer_class = PrivateWeEmployeeListSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    ordering_fields = ["created_at"]
    search_fields = [
        "code",
        "user__email",
        "user__name",
        "user__first_name",
        "user__last_name",
        "user__middle_name",
        "designation__title",
        "department__title",
    ]

    def get_queryset(self):
        return Employee.objects.filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeEmployeeDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeEmployeeDetailsSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"

    def get_object(self):
        return get_object_or_404(
            Employee.objects.filter(
                company=self.request.user.get_active_company(),
                uid=self.kwargs.get("uid", None),
            )
            .select_related("user", "designation", "department")
            .prefetch_related(
                "addressconnector_set",
                Prefetch(
                    "employee_salary",
                    queryset=PayrollSalaryProcess.objects.prefetch_related(
                        "payroll_components"
                    ),
                ),
            )
        )


class PrivateWeEmployeeEducationList(ListCreateAPIView):
    serializer_class = PrivateWeEmployeeEducationListSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"
    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
    ]
    filterset_fields = ["status", "employee__uid"]
    search_fields = [
        "title",
        "institute_name",
        "institute_name",
        "degree",
        "level",
        "passing_year",
        "grade",
    ]

    def get_queryset(self):
        return EmployeeEducation.objects.filter(
            employee__uid=self.kwargs.get("uid", None),
            employee__company=self.request.user.get_active_company(),
        )


class PrivateWeEmployeeEducationDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeEmployeeEducationDetailsSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"

    def get_object(self):
        return get_object_or_404(
            EmployeeEducation.objects.filter(
                employee__uid=self.kwargs.get("uid", None),
                employee__company=self.request.user.get_active_company(),
                uid=self.kwargs.get("education_uid", None),
            )
        )


class PrivateWeEmployeeWorkExperienceList(ListCreateAPIView):
    serializer_class = PrivateWeEmployeeWorkExperienceListSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"
    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
    ]
    filterset_fields = ["status"]

    def get_queryset(self):
        return EmployeeWorkExperience.objects.filter(
            employee__uid=self.kwargs.get("uid", None),
            employee__company=self.request.user.get_active_company(),
        )


class PrivateWeEmployeeWorkExperienceDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeEmployeeWorkExperienceDetailsSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"
    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
    ]
    filterset_fields = ["status"]

    def get_object(self):
        return get_object_or_404(
            EmployeeWorkExperience.objects.filter(
                employee__uid=self.kwargs.get("uid", None),
                employee__company=self.request.user.get_active_company(),
                uid=self.kwargs.get("work_experience_uid", None),
            )
        )


class PrivateWeEmployeeBankingInformationList(CreateAPIView):
    serializer_class = PrivateWeEmployeeBankingInformationListSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"

    # def get_queryset(self):
    #     return EmployeeBankingInformation.objects.filter(
    #         employee__uid=self.kwargs.get("uid", None)
    #     )


class PrivateWeEmployeeBankingInformationDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeEmployeeBankingInformationDetailsSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"

    def get_object(self):
        return get_object_or_404(
            EmployeeBankingInformation.objects.filter(
                employee__uid=self.kwargs.get("uid", None),
                employee__company=self.request.user.get_active_company(),
                uid=self.kwargs.get("banking_information_uid", None),
            )
        )


class PrivateWeEmployeeTaxList(CreateAPIView):
    serializer_class = PrivateWeEmployeeTaxListSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"

    # def get_queryset(self):
    #     return EmployeeTax.objects.filter(
    #         employee__uid=self.kwargs.get("uid", None)
    #     )


class PrivateWeEmployeeTaxDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeEmployeeTaxDetailsSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"

    def get_object(self):
        return get_object_or_404(
            EmployeeTax.objects.filter(
                employee__uid=self.kwargs.get("uid", None),
                employee__company=self.request.user.get_active_company(),
                uid=self.kwargs.get("tax_uid_uid", None),
            )
        )


class PrivateWeEmployeeEarningList(ListCreateAPIView):
    serializer_class = PrivateWeEmployeeEarningListSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"

    def get_queryset(self):
        return EmployeeEarning.objects.filter(
            employee__uid=self.kwargs.get("uid", None),
            employee__company=self.request.user.get_active_company(),
        )


class PrivateWeEmployeeEarningDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeEmployeeEarningDetilsSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"

    def get_object(self):
        return get_object_or_404(
            EmployeeEarning.objects.filter(
                employee__uid=self.kwargs.get("uid", None),
                employee__company=self.request.user.get_active_company(),
                uid=self.kwargs.get("earning_uid", None),
            )
        )


class PrivateWeEmployeeDeductionContributionList(ListCreateAPIView):
    serializer_class = PrivateWeEmployeeDeductionContributionListSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"

    def get_queryset(self):
        return EmployeeDeductionContribution.objects.filter(
            employee__uid=self.kwargs.get("uid", None),
            employee__company=self.request.user.get_active_company(),
        )


class PrivateWeEmployeeDeductionContributionDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeEmployeeDeductionContributionDetailsSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"

    def get_object(self):
        return get_object_or_404(
            EmployeeDeductionContribution.objects.filter(
                employee__uid=self.kwargs.get("uid", None),
                employee__company=self.request.user.get_active_company(),
                uid=self.kwargs.get("deduction_and_contribution_uid", None),
            )
        )


class PrivateWeEmployeeGarnishmentList(ListCreateAPIView):
    serializer_class = PrivateWeEmployeeGarnishmentListSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"

    def get_queryset(self):
        return EmployeeGarnishment.objects.filter(
            employee__uid=self.kwargs.get("uid", None),
            employee__company=self.request.user.get_active_company(),
        )


class PrivateWeCompanyGarnishmentList(ListAPIView):
    serializer_class = PrivateWeEmployeeGarnishmentListSerializer
    permission_classes = [HaveSubscription]
    pagination_class = None
    required_feature = "is_employees"

    def get_queryset(self):
        return EmployeeGarnishment.objects.filter(
            employee__company=self.request.user.get_active_company()
        )


class PrivateWeEmployeeGarnishmentDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeEmployeeGarnishmentDetailsSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"

    def get_object(self):
        return get_object_or_404(
            EmployeeGarnishment.objects.filter(
                employee__uid=self.kwargs.get("uid", None),
                employee__company=self.request.user.get_active_company(),
                uid=self.kwargs.get("garnishment_uid", None),
            )
        )


class PrivateWeEmployeeDocumentList(ListCreateAPIView):
    serializer_class = PrivateWeEmployeeDocuementListSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"

    def get_queryset(self):
        return FileItem.objects.filter(
            fileitemconnector__employee__uid=self.kwargs.get("uid", None),
            fileitemconnector__employee__company=self.request.user.get_active_company(),
        )


class PrivateWeEmployeeDocumentDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeEmployeeDocuementDetailsSerializer
    permission_classes = [HaveSubscription]
    required_feature = "is_employees"

    def get_object(self):
        return get_object_or_404(
            FileItem.objects.filter(
                fileitemconnector__employee__uid=self.kwargs.get("uid", None),
                fileitemconnector__employee__company=self.request.user.get_active_company(),
                uid=self.kwargs.get("document_uid", None),
            )
        )


# all employees list
class PrivateWeEmployeeListAll(ListAPIView):
    serializer_class = PrivateWeEmployeeListAllSerializer
    permission_classes = [HaveSubscription]
    pagination_class = None
    required_feature = "is_employees"
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    ordering_fields = ["created_at"]
    search_fields = [
        "email",
        "name",
    ]

    def get_queryset(self):
        return Employee.objects.filter(
            company=self.request.user.get_active_company()
        )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        if request.query_params.get("is_excel", None) == "true":
            return self._generate_excel_with_pandas(queryset)

        return super().list(request, *args, **kwargs)

    def _generate_excel_with_pandas(self, queryset):
        """Generate Excel using pandas for better performance"""
        # Convert queryset to list of dicts
        data = []
        
        # Convert queryset to list for easier manipulation
        employees_list = list(queryset)
        
        for i, employee in enumerate(employees_list):
            user_data = {
                "employee_id": employee.employee_id,
                "name": employee.user.name,
                "email": employee.user.email,
                "date": "",
                "check_in": "",
                "check_out": "",
                "worked_hour_count": "",
                "remark": "",
            }
            
            # Add sample attendance data for the first employee
            if i == 0:
                user_data.update({
                    "date": "Sample Data- 2025-10-30",
                    "check_in": "Sample Data- 09:00:00",
                    "check_out": "Sample Data- 17:00:00",
                    "worked_hour_count": "Sample Data- 8.0",
                    "remark": "Sample attendance remark",
                })
            
            data.append(user_data)

        # Create DataFrame and Excel file
        df = pd.DataFrame(data)
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Employees", index=False)

        buffer.seek(0)

        response_obj = HttpResponse(
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response_obj["Content-Disposition"] = 'attachment; filename="employees.xlsx"'
        return response_obj
