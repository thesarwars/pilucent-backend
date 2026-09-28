from rest_framework import filters

from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from companyio.models import CompanyDesignation

from companyio.choices import CompanyDesignationStatusChoices

from ..serializers.company_designations import (
    PrivateWeCompanyDesignationListSerializer,
    PrivateWeCompanyDesignationDetailsSerializer,
)


class PrivateWeCompanyDesignationList(ListCreateAPIView):
    serializer_class = PrivateWeCompanyDesignationListSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    ordering_fields = ["created_at"]
    search_fields = ["title"]

    def get_queryset(self):
        return CompanyDesignation.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeCompanyDesignationDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeCompanyDesignationDetailsSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            CompanyDesignation.objects.get_status_all().filter(
                company=self.request.user.get_active_company(),
                uid=self.kwargs.get("uid", None),
            )
        )

    def perform_destroy(self, instance):
        instance.status = CompanyDesignationStatusChoices.REMOVED
        instance.save()
