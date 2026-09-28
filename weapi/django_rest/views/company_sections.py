from rest_framework import filters

from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from companyio.models import CompanySection

from companyio.choices import CompanySectionStatusChoices

from ..serializers.company_sections import (
    PrivateWeCompanySectionListSerializer,
    PrivateWeCompanySectionDetailsSerializer,
)


class PrivateWeCompanySectionList(ListCreateAPIView):
    serializer_class = PrivateWeCompanySectionListSerializer
    permission_classes = [IsGroupPermission]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    ordering_fields = ["created_at"]
    search_fields = ["title", "department__title"]

    def get_queryset(self):
        return CompanySection.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        ).select_related("department")


class PrivateWeCompanySectionDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeCompanySectionDetailsSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            CompanySection.objects.get_status_all().filter(
                company=self.request.user.get_active_company(),
                uid=self.kwargs.get("uid", None),
            )
        )

    def perform_destroy(self, instance):
        instance.status = CompanySectionStatusChoices.REMOVED
        instance.save()
