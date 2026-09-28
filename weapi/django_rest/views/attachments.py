from rest_framework import filters
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from common.django_rest.permissions.company_subscription import HaveSubscription

from django_filters.rest_framework import DjangoFilterBackend

from fileroomio.choices import FileItemStatusChoices
from fileroomio.models import FileItem

from ..serializers.attachments import (
    PrivateWeAttachmentListSerializer,
    PrivateWeAttachmentDetailsSerializer,
)


class PrivateWeAttachmentList(ListCreateAPIView):
    serializer_class = PrivateWeAttachmentListSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_attachment"
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["title", "kind"]
    filterset_fields = ["title", "is_report"]

    def get_queryset(self):
        return FileItem.objects.get_status_all().filter(
            company=self.request.user.get_active_company(), is_report=False
        )


class PrivateWeAttachmentDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeAttachmentDetailsSerializer
    permission_classes = [HaveSubscription, IsGroupPermission]
    required_feature = "is_attachment"

    def get_object(self):
        return get_object_or_404(
            FileItem.objects.get_status_all().filter(
                company=self.request.user.get_active_company(), uid=self.kwargs["uid"]
            )
        )

    def perform_destroy(self, instance):
        if instance.is_report == True:
            instance.delete()
        instance.status = FileItemStatusChoices.REMOVED
        instance.save()
