from rest_framework import filters
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)
from adminio.django_rest.helpers.group_permissions import IsGroupPermission

from attendanceio.choices import HolidayStatusChoices
from attendanceio.models import Holiday, HolidayDetails
from weapi.django_rest.serializers.holidays import (
    HolidayCreateSerializer,
    HolidayUpdateSerializer,
    HolidayDetailsCreateSerializer,
    HolidayDetailUpdateSerializer,
)


class PrivateWeHolidayListCreateView(ListCreateAPIView):
    serializer_class = HolidayCreateSerializer
    permission_classes = [IsGroupPermission]

    def get_queryset(self):
        return Holiday.objects.get_status_all().filter(
            company=self.request.user.get_active_company(),
            status=HolidayStatusChoices.ACTIVE,
        )


class PrivateWeHolidayDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = HolidayUpdateSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            Holiday.objects.get_status_all(),
            company=self.request.user.get_active_company(),
            uid=self.kwargs["uid"],
        )

    def perform_destroy(self, instance):
        instance.status = HolidayStatusChoices.REMOVED
        instance.save()


class PrivateWeHolidayDetailsListCreateView(ListCreateAPIView):
    serializer_class = HolidayDetailsCreateSerializer
    permission_classes = [IsGroupPermission]

    def get_queryset(self):
        return get_object_or_404(
            Holiday.objects.filter(
                company=self.request.user.get_active_company(),
                uid=self.kwargs["uid"],
            ).exclude(status=HolidayStatusChoices.REMOVED)
        ).details.all()


class PrivateWeHolidayDetailsDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = HolidayDetailUpdateSerializer
    permission_classes = [IsGroupPermission]

    def get_object(self):
        return get_object_or_404(
            get_object_or_404(
                Holiday.objects.filter(
                    company=self.request.user.get_active_company(),
                    uid=self.kwargs["uid"],
                ).exclude(status=HolidayStatusChoices.REMOVED)
            ).details.filter(
                uid=self.kwargs["detail_uid"],
            )
        )
