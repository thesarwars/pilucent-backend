from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce

from rest_framework.generics import get_object_or_404, RetrieveAPIView, ListAPIView
from rest_framework.response import Response

from attendanceio.choices import AttendanceStatusChoices

from employeeio.models import Employee

from ..serializers.employee_job_cards import PrivateWeEmployeeJobCardOverviewSerializer


class PrivateWeEmployeeJobCardOverView(RetrieveAPIView):
    serializer_class = PrivateWeEmployeeJobCardOverviewSerializer

    def retrieve(self, request, *args, **kwargs):
        start_date = request.query_params.get("start_date", None)
        end_date = request.query_params.get("end_date", None)

        employee = get_object_or_404(
            Employee.objects.filter(
                uid=self.kwargs.get("uid"),
                company=self.request.user.get_active_company(),
            )
        )
        attendances = employee.attendance_set.all()

        paid_leave_hour_count = 0
        un_paid_leave_hour_count = 0
        if start_date and end_date:
            attendances = attendances.filter(date__range=[start_date, end_date])
            un_paid_leave_hour_count = employee.get_un_paid_leave_hour_count([start_date, end_date])
            paid_leave_hour_count = employee.get_paid_leave_hour_count([start_date, end_date])

        card_overview = attendances.aggregate(
            present_in_time_count=Count(
                "id", filter=Q(status=AttendanceStatusChoices.PRESENT)
            ),
            early_out_count=Count(
                "id", filter=Q(status=AttendanceStatusChoices.EARLY_DEPARTURE)
            ),
            late_count=Count(
                "id",
                filter=Q(status=AttendanceStatusChoices.LATE_ARRIVAL),
            ),
            absent_count=Count("id", filter=Q(status=AttendanceStatusChoices.ABSENT)),
            leave_count=Count("id", filter=Q(status=AttendanceStatusChoices.LEAVE)),
            worked_hour_count=Coalesce(Sum("worked_hour_count"), 0.0),
        )
        workable_hour_count = card_overview["workable_hour_count"] = sum(
            attendance.shift.get_workable_hour()
            for attendance in attendances.select_related("shift")
            if attendance.shift
        )
        card_overview["difference_hour_count"] = (
            card_overview["worked_hour_count"] - workable_hour_count
        )
        card_overview["ot_hour_count"] = (
            card_overview["difference_hour_count"]
            if card_overview["difference_hour_count"] > 0
            else 0
        )
        card_overview["un_paid_leave_hour_count"] = un_paid_leave_hour_count
        card_overview["paid_leave_hour_count"] = paid_leave_hour_count
        final_counts = {**card_overview}
        serializer = self.serializer_class(final_counts)
        return Response(serializer.data)
