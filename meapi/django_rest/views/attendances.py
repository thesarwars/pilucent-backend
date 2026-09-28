from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateAPIView,
    get_object_or_404,
)

from attendanceio.models import DailyTimeTracking, DailyTimeTrackingSession

from ..serializer.attendances import (
    PrivateMeDailyTimeTrackingListSerializer,
    PrivateMeDailyTimeTrackingDetailsSerializer,
    PrivateMeDailyTimeTrackingSessionListSerializer,
    PrivateMeDailyTimeTrackingSessionDetailsSerializer,
)


class PrivateMeDailyTimeTrackingList(ListCreateAPIView):
    serializer_class = PrivateMeDailyTimeTrackingListSerializer
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    filterset_fields = ["date"]
    ordering_fields = ["created_at"]
    search_fields = ["title", "date", "shift__title", "status", "check_in", "check_out"]

    def get_queryset(self):
        return DailyTimeTracking.objects.filter(
            employee=self.request.user.get_employee()
        ).select_related("shift")


class PrivateMeDailyTimeTrackingDetails(RetrieveUpdateAPIView):
    serializer_class = PrivateMeDailyTimeTrackingDetailsSerializer

    def get_object(self):
        return get_object_or_404(
            DailyTimeTracking.objects.filter(
                uid=self.kwargs.get("uid"), employee=self.request.user.get_employee()
            ).select_related(
                "shift", "employee", "employee__designation", "employee__user"
            )
        )


class PrivateMeDailyTimeTrackingSessionList(ListCreateAPIView):
    serializer_class = PrivateMeDailyTimeTrackingSessionListSerializer

    def get_queryset(self):
        return DailyTimeTrackingSession.objects.filter(
            daily_time_tracking__uid=self.kwargs.get("uid"),
            daily_time_tracking__employee__user=self.request.user,
        )


class PrivateMeDailyTimeTrackingSessionDetails(RetrieveUpdateAPIView):
    serializer_class = PrivateMeDailyTimeTrackingSessionDetailsSerializer

    def get_object(self):
        uid = self.kwargs.get("uid")
        session_uid = self.kwargs.get("session_uid")
        return get_object_or_404(
            DailyTimeTrackingSession.objects.filter(
                daily_time_tracking__uid=uid,
                daily_time_tracking__employee__user=self.request.user,
                uid=session_uid,
            )
        )
