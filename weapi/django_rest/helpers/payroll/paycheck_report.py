"""
Helpers for the paycheck report API (employee-wise payroll run listing).

Used by ``PaycheckReportListView`` and ``PaycheckReportDetailView`` to group
``PayrollSalaryProcess`` rows by employee, apply date filters, and build
response payloads for the frontend paycheck report screens.
"""

from collections import defaultdict
from decimal import Decimal

from django.db.models import Max, Sum
from django.utils.dateparse import parse_date
from rest_framework.exceptions import ValidationError

from payrollio.choicess import PayrollComponentCategoryChoice

from weapi.django_rest.serializers.payroll.salary_process import (
    EmployeePayrollBaseSerializer,
)


def format_money(value):
    """
    Format a monetary amount as a fixed two-decimal string for API responses.

    Paycheck report serializers expose gross/net amounts as strings (e.g.
    ``"3010.00"``) so the frontend receives consistent decimal formatting.

    Args:
        value: A ``Decimal``, float, int, or None from a model field or aggregate.

    Returns:
        str: Amount formatted with two fractional digits, or ``"0.00"`` when
        ``value`` is None.
    """
    if value is None:
        return "0.00"
    return f"{Decimal(value):.2f}"


def format_currency_pdf(value):
    """Format a monetary amount with a leading dollar sign for PDF templates."""
    amount = format_money(value)
    return f"${amount}"


def format_pay_period_range(start_date, end_date):
    """
    Build a human-readable pay-period label for the report date filter.

    Shown on each employee header in the list response so users see which
    calendar window the totals and ``processed_data`` runs belong to.

    Args:
        start_date: Inclusive range start (``date`` or None).
        end_date: Inclusive range end (``date`` or None).

    Returns:
        str: e.g. ``"01/01/26 - 12/31/26"``, a single date, ``"From …"`` /
        ``"Through …"``, or an empty string when both bounds are missing.
    """
    if start_date and end_date:
        if start_date == end_date:
            return start_date.strftime("%m/%d/%y")
        return (
            f"{start_date.strftime('%m/%d/%y')} - {end_date.strftime('%m/%d/%y')}"
        )
    if start_date:
        return f"From {start_date.strftime('%m/%d/%y')}"
    if end_date:
        return f"Through {end_date.strftime('%m/%d/%y')}"
    return ""


def _split_address_lines(address_text):
    if not address_text:
        return []
    if "\n" in address_text:
        return [line.strip() for line in address_text.splitlines() if line.strip()]
    return [part.strip() for part in str(address_text).split(",") if part.strip()]


def format_address_model_lines(address):
    """Build printable address lines from an ``addressio.Address`` instance."""
    if not address:
        return []
    lines = _split_address_lines(address.full_address) if address.full_address else []
    if not lines and address.street:
        lines.append(address.street.strip())
    locality = ", ".join(
        part
        for part in (address.city, address.province, address.postal_code)
        if part
    )
    if locality and locality not in " ".join(lines):
        lines.append(locality)
    return lines


def get_employee_address_lines(employee):
    """
    Resolve employee mailing address lines from ``addressio.Address`` records.

    Prefers non-work addresses when multiple connectors exist.
    """
    prefetched = getattr(employee, "_prefetched_objects_cache", {}).get(
        "addressconnector_set"
    )
    if prefetched is not None:
        addresses = [
            connector.address
            for connector in employee.addressconnector_set.all()
            if connector.address_id
        ]
        if addresses:
            addresses.sort(
                key=lambda addr: (
                    addr.is_work_address,
                    -(addr.created_at.timestamp() if addr.created_at else 0),
                )
            )
            return format_address_model_lines(addresses[0])
        return []

    address = employee.get_addresses().order_by("is_work_address", "-created_at").first()
    return format_address_model_lines(address)


def parse_pay_period_bounds(pay_period):
    """Split stored pay_period text into beginning and ending display strings."""
    if not pay_period:
        return "", ""
    if " - " in pay_period:
        beginning, ending = pay_period.split(" - ", 1)
        return beginning.strip(), ending.strip()
    return pay_period.strip(), pay_period.strip()


def _format_display_date(value):
    if not value:
        return ""
    return f"{value.month}/{value.day}/{value.year}"


def _sum_component_field(components, field_name):
    return sum((Decimal(getattr(component, field_name) or 0) for component in components), Decimal("0"))


def _serialize_component_row(component, include_hours=False):
    row = {
        "label": (component.payroll_type or "").replace("_", " "),
        "current": format_money(component.current),
        "ytd": format_money(component.ytd),
        "current_display": format_currency_pdf(component.current),
        "ytd_display": format_currency_pdf(component.ytd),
    }
    if include_hours:
        row["hours"] = format_money(component.hours)
        row["rate"] = format_money(component.rate)
    return row


def build_paycheck_detail_pdf_context(payroll_run, company):
    """
    Build the Jinja2 context for the paycheck detail PDF template.

    Args:
        payroll_run: ``PayrollSalaryProcess`` with prefetched ``payroll_components``.
        company: Active ``companyio.Company`` for the request.

    Returns:
        dict: Template variables for ``reports/payrolls/paycheck_details.html``.
    """
    employee = payroll_run.employee
    components = list(payroll_run.payroll_components.all())

    pay_rows = []
    tax_rows = []
    deduction_rows = []
    other_rows = []

    for component in components:
        category = component.payroll_category
        if category == PayrollComponentCategoryChoice.PAY:
            pay_rows.append(_serialize_component_row(component, include_hours=True))
        elif category == PayrollComponentCategoryChoice.EMPLOYEE_TAXES:
            tax_rows.append(_serialize_component_row(component))
        elif category == PayrollComponentCategoryChoice.EMPLOYEE_DEDUCTIONS:
            deduction_rows.append(_serialize_component_row(component))
        elif category in (
            PayrollComponentCategoryChoice.EMPLOYER_TAXES,
            PayrollComponentCategoryChoice.COMPANY_PAID_CONTRIBUTIONS,
        ):
            other_rows.append(_serialize_component_row(component))

    pay_components = [c for c in components if c.payroll_category == PayrollComponentCategoryChoice.PAY]
    tax_components = [
        c for c in components if c.payroll_category == PayrollComponentCategoryChoice.EMPLOYEE_TAXES
    ]
    deduction_components = [
        c
        for c in components
        if c.payroll_category == PayrollComponentCategoryChoice.EMPLOYEE_DEDUCTIONS
    ]

    check_number = ""
    if payroll_run.pay_method == "PAPER_CHECK":
        bank_info = employee.get_bank_information()
        if bank_info and bank_info.check_number:
            check_number = bank_info.check_number

    period_beginning, period_ending = parse_pay_period_bounds(payroll_run.pay_period)

    return {
        "company_name": company.name,
        "company_address_lines": _split_address_lines(company.legal_address),
        "employee_name": employee.full_name,
        "employee_address_lines": get_employee_address_lines(employee),
        "check_number": check_number,
        "pay_date_display": _format_display_date(payroll_run.pay_date),
        "net_pay_display": format_currency_pdf(payroll_run.net_pay),
        "period_beginning": period_beginning,
        "period_ending": period_ending,
        "memo": (payroll_run.memo or "").strip(),
        "pay_rows": pay_rows,
        "tax_rows": tax_rows,
        "deduction_rows": deduction_rows,
        "other_rows": other_rows,
        "other_current_total": format_currency_pdf(
            _sum_component_field(
                [
                    c
                    for c in components
                    if c.payroll_category
                    in (
                        PayrollComponentCategoryChoice.EMPLOYER_TAXES,
                        PayrollComponentCategoryChoice.COMPANY_PAID_CONTRIBUTIONS,
                    )
                ],
                "current",
            )
        ),
        "other_ytd_total": format_currency_pdf(
            _sum_component_field(
                [
                    c
                    for c in components
                    if c.payroll_category
                    in (
                        PayrollComponentCategoryChoice.EMPLOYER_TAXES,
                        PayrollComponentCategoryChoice.COMPANY_PAID_CONTRIBUTIONS,
                    )
                ],
                "ytd",
            )
        ),
        "summary": {
            "total_pay_current": format_currency_pdf(
                _sum_component_field(pay_components, "current")
                if pay_components
                else payroll_run.gross_pay
            ),
            "total_pay_ytd": format_currency_pdf(_sum_component_field(pay_components, "ytd")),
            "taxes_current": format_currency_pdf(_sum_component_field(tax_components, "current")),
            "taxes_ytd": format_currency_pdf(_sum_component_field(tax_components, "ytd")),
            "deductions_current": format_currency_pdf(_sum_component_field(deduction_components, "current")),
            "deductions_ytd": format_currency_pdf(_sum_component_field(deduction_components, "ytd")),
            "net_pay": format_currency_pdf(payroll_run.net_pay),
        },
    }


def render_paycheck_detail_pdf(view, payroll_run, company):
    """
    Render the paycheck detail PDF, store it as a ``FileItem``, and return its URL.

    Args:
        view: DRF view instance (passed to ``get_pdf`` for company context).
        payroll_run: Payroll run being exported.
        company: Active company for file storage.

    Returns:
        dict: ``{"file_uid": str, "url": str}`` with the downloadable file URL.
    """
    from common.django_rest.helpers.file_helpers import get_pdf

    context = build_paycheck_detail_pdf_context(payroll_run, company)
    context.update(
        {
            "label": f"paycheck-{payroll_run.uid}",
            "template": "reports/payrolls/paycheck_details.html",
            "is_report": True,
            "title": "Pay Stub Detail",
        }
    )
    file_item = get_pdf(view, True, context)
    file_url = file_item.file.url
    if getattr(view, "request", None):
        file_url = view.request.build_absolute_uri(file_item.file.url)
    return {"file_uid": str(file_item.uid), "url": file_url}


def _sum_payroll_run_amounts(runs, field_name):
    """
    Sum a decimal field across in-memory payroll run instances.

    ``group_paycheck_runs_by_employee`` stores lists, not querysets, so DB
    ``aggregate()`` cannot be used on ``runs``.
    """
    return sum(
        (Decimal(getattr(run, field_name) or 0) for run in runs),
        Decimal("0"),
    )


def build_employee_paycheck_header(employee, runs, start_date, end_date):
    """
    Build the ``employee`` summary object for one row in the paycheck list.

    Aggregates all payroll runs for a single employee within the filtered
    date range. Totals sum gross and net across runs; ``pay_method``, ``status``,
    and ``check_number`` come from the most recent run by ``pay_date``.

    Args:
        employee: ``employeeio.Employee`` instance (with prefetched relations
            used by ``EmployeePayrollBaseSerializer`` when possible).
        runs: List of ``PayrollSalaryProcess`` for this employee (from
            ``group_paycheck_runs_by_employee``). Must be non-empty.
        start_date: Report filter start passed to ``format_pay_period_range``.
        end_date: Report filter end passed to ``format_pay_period_range``.

    Returns:
        dict: Keys match ``PaycheckEmployeeHeaderSerializer`` — ``uid``,
        ``full_name``, ``code``, ``work_locations``, ``employee_bank_info``,
        ``pay_period``, ``total_pay`` (sum of gross), ``net_pay`` (sum of net),
        ``pay_method``, ``check_number`` (banking info when latest run is
        paper check), and ``status``.
    """
    latest_run = max(runs, key=lambda run: run.pay_date)
    total_gross = _sum_payroll_run_amounts(runs, "gross_pay")
    total_net = _sum_payroll_run_amounts(runs, "net_pay")
    employee_payload = EmployeePayrollBaseSerializer(employee).data
    check_number = None
    if latest_run.pay_method == "PAPER_CHECK":
        bank_info = employee.get_bank_information()
        if bank_info:
            check_number = bank_info.check_number or ""

    return {
        "uid": employee.uid,
        "full_name": employee_payload.get("full_name") or employee.full_name,
        "code": employee_payload.get("code") or "",
        "work_locations": employee_payload.get("work_locations"),
        "employee_bank_info": employee_payload.get("employee_bank_info"),
        "pay_period": format_pay_period_range(start_date, end_date),
        "total_pay": format_money(total_gross),
        "net_pay": format_money(total_net),
        "pay_method": latest_run.pay_method,
        "check_number": check_number or "",
        "status": latest_run.status,
    }


def parse_paycheck_report_dates(request, queryset):
    """
    Resolve the paycheck report's pay-date window from query parameters.

    Query params:
        ``start_date`` / ``end_date`` (``YYYY-MM-DD``), optional.
        ``filter_type=last_pay_date`` — use only the latest ``pay_date`` in scope.
        If no dates and no ``filter_type``, defaults to the latest pay date.

    Args:
        request: DRF request whose ``query_params`` carry filter values.
        queryset: Company-scoped ``PayrollSalaryProcess`` queryset used to
            look up the latest ``pay_date`` when defaults apply.

    Returns:
        tuple[date | None, date | None]: ``(start_date, end_date)`` inclusive
        bounds for ``apply_paycheck_pay_date_filter``.

    Raises:
        ValidationError: If a provided date string is not valid ``YYYY-MM-DD``.
    """
    start_date_str = request.query_params.get("start_date")
    end_date_str = request.query_params.get("end_date")
    filter_type = request.query_params.get("filter_type")

    if filter_type == "last_pay_date":
        last_pay_date = queryset.aggregate(Max("pay_date"))["pay_date__max"]
        return last_pay_date, last_pay_date

    start_date = parse_date(start_date_str) if start_date_str else None
    end_date = parse_date(end_date_str) if end_date_str else None

    if start_date_str and not start_date:
        raise ValidationError({"start_date": "Invalid date format. Use YYYY-MM-DD."})
    if end_date_str and not end_date:
        raise ValidationError({"end_date": "Invalid date format. Use YYYY-MM-DD."})

    if not start_date and not end_date:
        last_pay_date = queryset.aggregate(Max("pay_date"))["pay_date__max"]
        return last_pay_date, last_pay_date

    return start_date, end_date


def apply_paycheck_pay_date_filter(queryset, start_date, end_date):
    """
    Restrict payroll runs to the resolved report pay-date range.

    Args:
        queryset: ``PayrollSalaryProcess`` queryset after company and
            ``PaycheckReportFilter`` filters.
        start_date: Lower bound on ``pay_date``, or None.
        end_date: Upper bound on ``pay_date``, or None.

    Returns:
        Filtered queryset. Uses ``pay_date__range`` when both bounds exist,
        otherwise a single-sided ``gte`` or ``lte`` filter. Returns the
        queryset unchanged when both dates are None.
    """
    if start_date and end_date:
        return queryset.filter(pay_date__range=(start_date, end_date))
    if start_date:
        return queryset.filter(pay_date__gte=start_date)
    if end_date:
        return queryset.filter(pay_date__lte=end_date)
    return queryset


def group_paycheck_runs_by_employee(queryset):
    """
    Group payroll runs by employee for employee-wise report rows.

    Args:
        queryset: Ordered ``PayrollSalaryProcess`` queryset (typically
            ``employee__user__name``, ``-pay_date``).

    Returns:
        defaultdict[int, list]: Maps ``employee_id`` to a list of runs for
        that employee. Order within each list follows the queryset order.
    """
    grouped = defaultdict(list)
    for payroll_run in queryset:
        grouped[payroll_run.employee_id].append(payroll_run)
    return grouped


def build_paycheck_employee_groups(grouped_runs, start_date, end_date):
    """
    Turn grouped runs into the list payload consumed by ``PaycheckEmployeeGroupSerializer``.

    Each item pairs an employee summary (``build_employee_paycheck_header``) with
    that employee's ``processed_data`` run list for the detail drill-down.

    Args:
        grouped_runs: Output of ``group_paycheck_runs_by_employee``.
        start_date: Passed through to the employee header ``pay_period`` label.
        end_date: Passed through to the employee header ``pay_period`` label.

    Returns:
        list[dict]: Sorted by ``employee.full_name`` (case-insensitive). Each
        dict has keys ``employee`` and ``processed_data``.
    """
    results = []
    for runs in grouped_runs.values():
        employee = runs[0].employee
        results.append(
            {
                "employee": build_employee_paycheck_header(
                    employee, runs, start_date, end_date
                ),
                "processed_data": runs,
            }
        )
    results.sort(key=lambda row: row["employee"]["full_name"].lower())
    return results


def aggregate_paycheck_totals(queryset):
    """
    Sum gross and net pay across all runs in the filtered report queryset.

    Used for top-level list response fields ``total_gross_pay`` and
    ``total_net_pay`` alongside per-employee breakdowns.

    Args:
        queryset: Date- and filter-scoped ``PayrollSalaryProcess`` queryset.

    Returns:
        dict: ``{"total_gross_pay": str, "total_net_pay": str}`` with values
        formatted via ``format_money``.
    """
    totals = queryset.aggregate(
        total_net_pay=Sum("net_pay"),
        total_gross_pay=Sum("gross_pay"),
    )
    return {
        "total_gross_pay": format_money(totals.get("total_gross_pay")),
        "total_net_pay": format_money(totals.get("total_net_pay")),
    }
