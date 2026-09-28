from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum

from rest_framework import filters, response, status as http_status
from rest_framework.views import APIView

from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)

from attendanceio.models import Attendance, AttendanceProcess, PunchDataDailyTime

from common.django_rest.helpers.file_helpers import get_pdf
from common.django_rest.helpers.date_range_filters import DateFromToRangeFilter

from ..serializers.attendances import (
    PrivateWeAttendanceListSerializer,
    PrivateWeAttendanceDetailsSerializer,
    ParivateWeAttendanceProcessListSerializer,
    PrivateWePunchDataDailyTimeListCreateSerializer,
)
from ..serializers.attendance_bulk import (
    BulkAttendanceInputSerializer,
    process_bulk_attendance,
)


class PrivateWeAttendanceList(ListCreateAPIView):
    serializer_class = PrivateWeAttendanceListSerializer
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
        DateFromToRangeFilter,
    ]
    ordering_fields = ["created_at"]
    search_fields = ["employee__user__name", "employee__code"]
    filterset_fields = ["employee__uid", "date"]

    def get_queryset(self):
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")
        queryset = Attendance.objects.filter(
            company=self.request.user.get_active_company()
        ).select_related(
            "employee", "employee__user", "employee__designation", "shift", "company"
        )
        if start_date and end_date:
            queryset = queryset.filter(date__range=[start_date, end_date])
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        if request.query_params.get("is_pdf", None) == "true":

            # Creating PDF
            pdf = get_pdf(
                self,
                True,
                {
                    "overview": {
                        "worked_hour_count": queryset.aggregate(
                            worked_hour_count=Sum("worked_hour_count")
                        )["worked_hour_count"],
                        "ot_hour_count": sum(
                            data.get_ot_hour_count() for data in queryset
                        ),
                    },
                    "data": self.get_serializer(queryset, many=True).data,
                    "fields": [
                        "SL NO.",
                        "EMP ID",
                        "NAME",
                        "DESIGNATION",
                        "SHIFT",
                        "STATUS",
                        "IN",
                        "OUT",
                        "LATE",
                        "W. HR",
                        "OT HR",
                    ],
                    "label": "daily_attendance",
                    "template": "reports/payrolls/daily_attendances.html",
                    "title": "Daily Attendance",
                    "is_report": True,
                },
            )

            return response.Response(
                {
                    "file_uid": pdf.uid,
                    "url": f"https://{self.request.get_host()}{pdf.file.url}",
                }
            )
        return super().list(request, *args, **kwargs)


class PrivateWeAttendanceDetails(RetrieveUpdateDestroyAPIView):
    serializer_class = PrivateWeAttendanceDetailsSerializer

    def get_object(self):
        return get_object_or_404(
            Attendance.objects.filter(
                company=self.request.user.get_active_company(),
                uid=self.kwargs.get("uid"),
            ).select_related("employee")
        )


class PrivateWeAttendanceProcessList(ListCreateAPIView):
    serializer_class = ParivateWeAttendanceProcessListSerializer
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DateFromToRangeFilter,
    ]

    def get_queryset(self):
        return AttendanceProcess.objects.filter(
            company=self.request.user.get_active_company()
        )


class _BulkAttendanceBaseView(APIView):
    """Shared plumbing for the two-phase bulk manual attendance endpoints."""

    commit = False

    def post(self, request, *args, **kwargs):
        company = request.user.get_active_company()
        if company is None:
            return response.Response(
                {"message": "No active company in context."},
                status=http_status.HTTP_403_FORBIDDEN,
            )

        serializer = BulkAttendanceInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        outcomes, summary = process_bulk_attendance(
            company=company,
            validated=serializer.validated_data,
            commit=self.commit,
        )
        return response.Response(
            {
                "date": serializer.validated_data["date"],
                "committed": self.commit,
                "summary": summary,
                "rows": outcomes,
            },
            status=http_status.HTTP_200_OK,
        )


class PrivateWeBulkAttendancePreview(_BulkAttendanceBaseView):
    """Dry-run: per-row derived outcome + live summary counts, no writes."""

    commit = False


class PrivateWeBulkAttendanceCommit(_BulkAttendanceBaseView):
    """Transactional upsert of the validated bulk rows."""

    commit = True


class PrivateWePunchDataDailyTimeListCreate(ListCreateAPIView):
    serializer_class = PrivateWePunchDataDailyTimeListCreateSerializer
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
        DjangoFilterBackend,
    ]
    filterset_fields = ["date", "status"]
    ordering_fields = ["created_at"]
    search_fields = ["title", "date", "shift__title", "check_in", "check_out"]

    def get_queryset(self):
        return PunchDataDailyTime.objects.filter(
            employee=self.request.user.get_employee()
        ).select_related("shift")
