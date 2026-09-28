from rest_framework.filters import BaseFilterBackend
from rest_framework.exceptions import ValidationError
from datetime import datetime, timedelta
import calendar
import pytz
from dateutil.parser import parse


class DateFromToRangeFilter(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        date_0 = request.query_params.get("created_at_after")
        date_1 = request.query_params.get("created_at_before")

        if date_0:
            date_0 = self.validate_date(date_0, "created_at_after")
        if date_1:
            date_1 = self.validate_date(date_1, "created_at_before")

        if date_0 and date_1:
            queryset = queryset.filter(created_at__range=[date_0, date_1])
        elif date_0:
            queryset = queryset.filter(created_at__gte=date_0)
        elif date_1:
            queryset = queryset.filter(created_at__lte=date_1)

        return queryset

    def validate_date(self, date_val, field_name):
        try:
            date = datetime.strptime(date_val, "%Y-%m-%d").replace(tzinfo=pytz.UTC)
        except ValueError:
            raise ValidationError(
                {field_name: "Invalid date format. Expected format is YYYY-MM-DD"}
            )
        return date


class WeekMonthYearRangeFilter(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        date_range = request.query_params.get("date_range")

        if date_range:
            queryset = self.get_date_range(date_range, queryset)

        return queryset

    def get_date_range(self, date_range, queryset):
        today = datetime.now().date()
        if date_range == "this_week":
            start_date = today - timedelta(days=today.weekday())
            end_date = start_date + timedelta(days=6)
            queryset = queryset.filter(date__range=[start_date, end_date])
        elif date_range == "this_month":
            start_date = today.replace(day=1)
            end_date = today.replace(
                day=calendar.monthrange(today.year, today.month)[1]
            )
            queryset = queryset.filter(date__range=[start_date, end_date])
        elif date_range == "this_year":
            start_date = today.replace(month=1, day=1)
            end_date = today.replace(
                month=12, day=calendar.monthrange(today.year, 12)[1]
            )
            queryset = queryset.filter(date__range=[start_date, end_date])
        elif date_range == "previous_week":
            start_date = today - timedelta(days=today.weekday() + 7)
            end_date = start_date + timedelta(days=6)
            queryset = queryset.filter(date__range=[start_date, end_date])
        elif date_range == "previous_month":
            first_day_of_current_month = today.replace(day=1)
            last_day_of_previous_month = first_day_of_current_month - timedelta(days=1)
            start_date = last_day_of_previous_month.replace(day=1)
            end_date = last_day_of_previous_month
            queryset = queryset.filter(date__range=[start_date, end_date])
        elif date_range == "previous_year":
            start_date = today.replace(year=today.year - 1, month=1, day=1)
            end_date = today.replace(year=today.year - 1, month=12, day=31)
            queryset = queryset.filter(date__range=[start_date, end_date])
        return queryset