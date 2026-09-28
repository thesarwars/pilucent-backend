from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)
from rest_framework import filters

from django_filters.rest_framework import DjangoFilterBackend

from addressio.models import Address

from ..serializers.addresses import (
    PrivateWeAddressListSerializer,
    PrivateWeAddressDetailsSerializer,
)


class PrivateWeAddressList(ListCreateAPIView):
    serializer_class = PrivateWeAddressListSerializer
    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
    ]
    filterset_fields = ["title", "addressconnector__employee__uid"]
    search_fields = ["title"]

    def get_queryset(self):
        return Address.objects.all().filter(
            company=self.request.user.get_active_company()
        )


class PrivateWeAddressDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeAddressDetailsSerializer

    def get_object(self):
        return get_object_or_404(
            Address.objects.all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )
