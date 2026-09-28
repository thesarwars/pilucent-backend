from rest_framework import filters

from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from companyio.models import CompanyDepartment

from companyio.choices import CompanyDepartmentStatusChoices

from ..serializers.company_departments import (
    PrivateWeCompanyDepartmenListSerializer,
    PrivateWeCompanyDepartmenDetailsSerializer,
)


class PrivateWeCompanyDepartmentList(ListCreateAPIView):
    serializer_class = PrivateWeCompanyDepartmenListSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    ordering_fields = ["created_at"]
    search_fields = ["title", "code"]

    def get_queryset(self):
        return CompanyDepartment.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeCompanyDepartmentDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeCompanyDepartmenDetailsSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            CompanyDepartment.objects.get_status_all().filter(
                company=self.request.user.get_active_company(),
                uid=self.kwargs.get("uid", None),
            )
        )

    def perform_destroy(self, instance):
        instance.status = CompanyDepartmentStatusChoices.REMOVED
        instance.save()
