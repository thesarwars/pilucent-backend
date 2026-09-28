from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from attendanceio.models import DailyTimeTracking

from ..serializers.attendances import (
    PrivateWeDailyTimeTrackingListSerializer,
    PrivateWeDailyTimeTrackingDetailsSerializer,
)


class PrivateWeDailyTimeTrackingList(ListCreateAPIView):
    serializer_class = PrivateWeDailyTimeTrackingListSerializer

    def get_queryset(self):
        return DailyTimeTracking.objects.filter(
            company=self.request.user.get_active_company()
        ).select_related("shift", "employee", "employee__designation", "employee__user")


class PrivateWeDailyTimeTrackingDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeDailyTimeTrackingDetailsSerializer

    def get_object(self):
        return get_object_or_404(
            DailyTimeTracking.objects.filter(
                company=self.request.user.get_active_company(),
                uid=self.kwargs.get("uid"),
            ).select_related(
                "shift", "employee", "employee__designation", "employee__user"
            )
        )
