from rest_framework import filters
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from companyio.models import CompanyShift

from companyio.choices import CompanyShiftStatusChoices

from ..serializers.company_shifts import (
    PrivateWeCompanyShiftListSerializer,
    PrivateWeCompanyShiftDetailsSerializer,
)


class PrivateWeCompanyShiftList(ListCreateAPIView):
    serializer_class = PrivateWeCompanyShiftListSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    ordering_fields = ["created_at"]
    search_fields = ["title", "code"]

    def get_queryset(self):
        return CompanyShift.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeCompanyShiftDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeCompanyShiftDetailsSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            CompanyShift.objects.get_status_all().filter(
                company=self.request.user.get_active_company(),
                uid=self.kwargs.get("uid", None),
            )
        )

    def perform_destroy(self, instance):
        instance.status = CompanyShiftStatusChoices.REMOVED
        instance.save()
