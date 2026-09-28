from django_filters.rest_framework import DjangoFilterBackend
from adminio.mixins import IsSuperAdmin
from rest_framework.permissions import AllowAny

from rest_framework.generics import (
    CreateAPIView,
    RetrieveUpdateDestroyAPIView,
    ListAPIView,
    get_object_or_404,
)

from livedemoio.models import LiveDemo

from publicapi.django_rest.serializers.live_demo import (
    PublicWeLiveDemoCreateSerializer,
    PublicWeLiveDemoListSerializer,
    PublicWeLiveDemoDetailsSerializer,
)


class PublicWeLiveDemoCreate(CreateAPIView):
    serializer_class = PublicWeLiveDemoCreateSerializer
    permission_classes = [AllowAny]


class PublicWeLiveDemoList(ListAPIView):
    serializer_class = PublicWeLiveDemoListSerializer
    permission_classes = [IsSuperAdmin]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["email", "company_name", "phone_number", "request_type"]

    def get_queryset(self):
        return LiveDemo.objects.all()


class PublicWeLiveDemoDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PublicWeLiveDemoDetailsSerializer
    permission_classes = [IsSuperAdmin]

    def get_object(self):
        return get_object_or_404(LiveDemo, uid=self.kwargs["uid"])
