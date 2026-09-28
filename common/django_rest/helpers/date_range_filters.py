from decimal import Decimal, InvalidOperation

from django.db.models import DecimalField, F, Q, Value
from django.db.models.functions import Coalesce

ZERO_AMOUNT = Value(Decimal("0.000"), output_field=DecimalField(max_digits=19, decimal_places=3))

from rest_framework.filters import BaseFilterBackend
from rest_framework.exceptions import ValidationError
from datetime import datetime, timedelta
import calendar
import pytz


class DateFromToRangeFilter(BaseFilterBackend):
    """Filter ``created_at`` with YYYY-MM-DD in UTC; same after/before = full calendar day."""

    def filter_queryset(self, request, queryset, view):
        date_0 = request.query_params.get("created_at_after")
        date_1 = request.query_params.get("created_at_before")

        if date_0:
            date_0 = self.validate_date(date_0, "created_at_after")
        if date_1:
            date_1 = self.validate_date(date_1, "created_at_before")

        if date_0 and date_1:
            if date_0 == date_1:
                day_end = date_0 + timedelta(days=1)
                queryset = queryset.filter(created_at__gte=date_0, created_at__lt=day_end)
            else:
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


class LedgerDateRangeFilter(BaseFilterBackend):
    """Filter a ledger by transaction date, not by when the row was typed.

    `DateFromToRangeFilter` filters `created_at`, and 31 modules mount it, so it
    stays as it is. It is the wrong filter for a ledger three times over:

    * **Wrong column.** `JournalEntryConnector.date` is the transaction date and
      `created_at` is the keystroke. A document dated in March and entered in
      June belongs in March -- the contract `ledger_balances` states in its
      module docstring, and the column a register is ordered by. Filtering one
      column while ordering by another is how a register loses rows out of the
      middle of a range.
    * **Loses the last day.** `created_at__lte=<date>` compares a timestamp
      against midnight, so everything keyed during the closing day falls out.
    * **Wrong timezone.** It pinned `pytz.UTC` while the project runs
      `Asia/Dhaka`, so a boundary moved six hours.

    All three vanish against a `DateField`, where an inclusive comparison is
    exactly what it looks like.

    Accepts `date_after`/`date_before`, and keeps `created_at_after`/
    `created_at_before` working as aliases -- clients already send those, and a
    filter that silently stops applying is worse than one that is misnamed.
    """

    field = "date"

    def filter_queryset(self, request, queryset, view):
        after = self._read(request, ("date_after", "created_at_after"))
        before = self._read(request, ("date_before", "created_at_before"))

        if after:
            queryset = queryset.filter(**{f"{self.field}__gte": after})
        if before:
            queryset = queryset.filter(**{f"{self.field}__lte": before})
        return queryset

    @staticmethod
    def _read(request, names):
        for name in names:
            raw = request.query_params.get(name)
            if not raw:
                continue
            try:
                return datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                raise ValidationError(
                    {name: "Invalid date format. Expected format is YYYY-MM-DD"}
                )
        return None


class ReconciliationStatusFilter(BaseFilterBackend):
    """Filter a ledger by U / C / R across the whole account, not the page.

    The pair of columns is the status, as `undo_reconciliation` states it:
    reconciled means pointing at a *closed* session, cleared means carrying a
    tick date and no session. R is therefore decided by the session's status
    and never by the FK alone -- a line can be left pointing at an UNDONE
    session, because undo releases through `candidate_connectors`, which also
    filters on `journal__status` and the statement date.

    Accepts `?reconciliation_status=R`, `C`, `U`, or a comma-separated set. The
    register filtered this client-side over the loaded page only, so a status
    filter silently meant "on this page".
    """

    CLOSED = "CLOSED"

    def filter_queryset(self, request, queryset, view):
        raw = request.query_params.get("reconciliation_status")
        if not raw:
            return queryset

        wanted = {value.strip().upper() for value in raw.split(",") if value.strip()}
        unknown = wanted - {"U", "C", "R"}
        if unknown:
            raise ValidationError(
                {
                    "reconciliation_status": (
                        f"Unknown status {', '.join(sorted(unknown))}. "
                        "Use U, C or R."
                    )
                }
            )

        reconciled = Q(reconciliation__status=self.CLOSED)
        cleared = ~reconciled & Q(cleared_on__isnull=False)
        unmarked = ~reconciled & Q(cleared_on__isnull=True)

        lookup = Q(pk__in=[])
        for status, clause in (("R", reconciled), ("C", cleared), ("U", unmarked)):
            if status in wanted:
                lookup |= clause
        return queryset.filter(lookup)


class LedgerAmountRangeFilter(BaseFilterBackend):
    """Filter ledger lines by how big the transaction is.

    A leg carries its amount in whichever of `debit`/`credit` it posted on and
    zero in the other, so the magnitude is their sum -- there is no single
    "amount" column to range over, which is why the register had no amount
    filter at all and a user hunting a payment they half-remember had to page.

    Deliberately the magnitude and not the signed movement: someone looking for
    "about five hundred" means five hundred either way, and asking them to know
    which side it posted on is asking them to know double-entry.

    `amount_min` / `amount_max`, either or both.
    """

    def filter_queryset(self, request, queryset, view):
        bounds = {
            "amount_min": "gte",
            "amount_max": "lte",
        }
        applied = {}
        for name, lookup in bounds.items():
            raw = request.query_params.get(name)
            if not raw:
                continue
            try:
                applied[lookup] = Decimal(raw)
            except (InvalidOperation, ValueError):
                raise ValidationError({name: "Must be a number."})

        if not applied:
            return queryset

        queryset = queryset.annotate(
            _amount=Coalesce(F("debit"), ZERO_AMOUNT)
            + Coalesce(F("credit"), ZERO_AMOUNT)
        )
        for lookup, value in applied.items():
            queryset = queryset.filter(**{f"_amount__{lookup}": value})
        return queryset


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
            queryset = queryset.filter(created_at__range=[start_date, end_date])
        elif date_range == "this_month":
            start_date = today.replace(day=1)
            end_date = today.replace(
                day=calendar.monthrange(today.year, today.month)[1]
            )
            queryset = queryset.filter(created_at__range=[start_date, end_date])
        elif date_range == "this_year":
            start_date = today.replace(month=1, day=1)
            end_date = today.replace(
                month=12, day=calendar.monthrange(today.year, 12)[1]
            )
            queryset = queryset.filter(created_at__range=[start_date, end_date])
        elif date_range == "previous_week":
            start_date = today - timedelta(days=today.weekday() + 7)
            end_date = start_date + timedelta(days=6)
            queryset = queryset.filter(created_at__range=[start_date, end_date])
        elif date_range == "previous_month":
            first_day_of_current_month = today.replace(day=1)
            last_day_of_previous_month = first_day_of_current_month - timedelta(days=1)
            start_date = last_day_of_previous_month.replace(day=1)
            end_date = last_day_of_previous_month
            queryset = queryset.filter(created_at__range=[start_date, end_date])
        elif date_range == "previous_year":
            start_date = today.replace(year=today.year - 1, month=1, day=1)
            end_date = today.replace(year=today.year - 1, month=12, day=31)
            queryset = queryset.filter(created_at__range=[start_date, end_date])
        return queryset


class AuditLogDateRangeFilter(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        time_period = request.query_params.get("time_period")

        if time_period:
            queryset = self.get_time_period(time_period, queryset)

        return queryset

    def get_time_period(self, time_period, queryset):
        today = datetime.now().date()
        tz = pytz.UTC
        if time_period == "this_week":
            start_date = today - timedelta(days=today.weekday())
            end_date = start_date + timedelta(days=6)
            queryset = queryset.filter(timestamp__range=[start_date, end_date])
        elif time_period == "this_month":
            start_date = today.replace(day=1)
            end_date = today.replace(
                day=calendar.monthrange(today.year, today.month)[1]
            )
            queryset = queryset.filter(timestamp__range=[start_date, end_date])
        elif time_period == "today":
            queryset = queryset.filter(timestamp__date=today)
        elif time_period == "yesterday":
            queryset = queryset.filter(timestamp__date=today - timedelta(days=1))
        elif time_period == "this_quarter":
            current_month = today.month
            start_month = current_month - (current_month - 1) % 3
            start_date = tz.localize(datetime(today.year, start_month, 1))
            end_month = start_month + 2
            end_date = tz.localize(
                datetime(
                    today.year, end_month, calendar.monthrange(today.year, end_month)[1]
                )
            )
            queryset = queryset.filter(timestamp__range=[start_date, end_date])
        elif time_period == "this_fiscal_quarter":
            fiscal_start_month = 10  # Assuming fiscal year starts in October
            if today.month >= fiscal_start_month:
                start_date = tz.localize(datetime(today.year, fiscal_start_month, 1))
                end_date = tz.localize(
                    datetime(
                        today.year,
                        fiscal_start_month + 2,
                        calendar.monthrange(today.year, fiscal_start_month + 2)[1],
                    )
                )
            else:
                start_date = tz.localize(
                    datetime(today.year - 1, fiscal_start_month, 1)
                )
                end_date = tz.localize(
                    datetime(
                        today.year - 1,
                        fiscal_start_month + 2,
                        calendar.monthrange(today.year - 1, fiscal_start_month + 2)[1],
                    )
                )
            queryset = queryset.filter(timestamp__range=[start_date, end_date])

        return queryset
    


def get_dates_of_ranges(start_date, end_date):
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

    return [
        (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range((end_date - start_date).days + 1)
    ]
