from rest_framework import filters

from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from django_filters.rest_framework import DjangoFilterBackend

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.permissions.company_subscription import HaveSubscription

from termio.models import Term
from termio.choicess import TermStatusChoices

from ..serializers.terms import (
    PrivateWeTermListSerializer,
    PrivateWeTermDetailsSerializer,
)


class PrivateWeTermList(ListCreateAPIView):
    serializer_class = PrivateWeTermListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_terms"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title", "days"]
    filterset_fields = ["status", "is_active"]

    def get_queryset(self):
        return Term.objects.get_status_all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeTermDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeTermDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_terms"

    def get_object(self):
        return get_object_or_404(
            Term.objects.filter(
                company=self.request.user.get_active_company(),
                uid=self.kwargs["uid"],
            )
        )

    def perform_destroy(self, instance):
        instance.status = TermStatusChoices.REMOVED
        instance.save()
