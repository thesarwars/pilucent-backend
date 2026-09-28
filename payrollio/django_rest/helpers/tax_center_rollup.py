"""
Build QuickBooks-style Tax Center liability rows from finalized payroll runs.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from payrollio.choicess import (
    PayrollFederalTaxInfoSettingChoices,
    PayrollFederalTaxInfoTaxFormChoices,
)
from payrollio.django_rest.helpers.federal_tax_setting_items import (
    get_current_federal_tax_item,
)
from payrollio.django_rest.helpers.accounting_preferences_setup import (
    normalize_us_state,
)
from payrollio.django_rest.helpers.payroll_journal_mappings import (
    FEDERAL_TAXES_941_943_944_PAYROLL_TYPES,
    FEDERAL_UNEMPLOYMENT_940_PAYROLL_TYPES,
    payroll_types_for_group,
    quantize_money,
    state_employment_tax_group_key,
    state_income_tax_group_key,
)

FEDERAL_TYPE_TO_BREAKDOWN_KEY = {
    "FEDERAL_INCOME_TAX": "federal_income_tax",
    "SOCIAL_SECURITY": "social_security",
    "SOCIAL_SECURITY_EMPLOYER": "social_security_employer",
    "MEDICARE": "medicare",
    "MEDICARE_EMPLOYER": "medicare_employer",
}

FEDERAL_BREAKDOWN_LABELS = {
    "federal_income_tax": "Federal Income Tax",
    "social_security": "Social Security",
    "social_security_employer": "Social Security Employer",
    "medicare": "Medicare",
    "medicare_employer": "Medicare Employer",
}

DEFAULT_FEDERAL_FREQUENCY = PayrollFederalTaxInfoSettingChoices.MONTHLY
DEFAULT_FEDERAL_TAX_FORM = PayrollFederalTaxInfoTaxFormChoices.FORM_941_EACH_QUARTER

STATE_DUE_DATE_RULES = {
    "NY": relativedelta(days=10),
    "MN": relativedelta(months=1, day=15),
    "AL": relativedelta(months=1, day=31),
    "CA": relativedelta(months=1, day=15),
    "AZ": relativedelta(months=1, day=15),
    "TX": relativedelta(months=1, day=20),
    "FL": relativedelta(months=1, day=31),
}


def parse_pay_period(pay_period):
    """Parse ``MM/DD/YY - MM/DD/YY`` pay period strings."""
    if not pay_period:
        return None, None
    try:
        start_str, end_str = pay_period.split(" - ")
        start_parts = start_str.split("/")
        end_parts = end_str.split("/")

        def _year(two_digit):
            value = int(two_digit)
            return 2000 + value if value < 50 else 1900 + value

        start_date = date(
            _year(start_parts[2]), int(start_parts[0]), int(start_parts[1])
        )
        end_date = date(_year(end_parts[2]), int(end_parts[0]), int(end_parts[1]))
        return start_date, end_date
    except (ValueError, IndexError):
        return None, None


def quarter_label_for_date(value):
    quarter = (value.month - 1) // 3 + 1
    return f"Q{quarter}"


def get_payment_status(due_date, *, today=None):
    today = today or date.today()
    if due_date < today:
        return "Past due"
    if due_date <= today + timedelta(days=7):
        return "Due soon"
    return "Ready to pay"


def calculate_federal_due_date(end_date, frequency, tax_form=None):
    frequency = (frequency or DEFAULT_FEDERAL_FREQUENCY).upper()
    if tax_form == PayrollFederalTaxInfoTaxFormChoices.FORM_941_EACH_QUARTER or (
        frequency == PayrollFederalTaxInfoSettingChoices.QUARTERLY
    ):
        quarter = (end_date.month - 1) // 3 + 1
        if quarter == 1:
            return date(end_date.year, 4, 30)
        if quarter == 2:
            return date(end_date.year, 7, 31)
        if quarter == 3:
            return date(end_date.year, 10, 31)
        return date(end_date.year + 1, 1, 31)
    if frequency == PayrollFederalTaxInfoSettingChoices.MONTHLY:
        return end_date + relativedelta(months=1, day=15)
    return end_date + timedelta(days=3)


def calculate_state_due_date(end_date, state_code):
    offset = STATE_DUE_DATE_RULES.get(
        (state_code or "").upper(), relativedelta(months=1, day=15)
    )
    return end_date + offset


def _empty_federal_breakdown():
    return {
        key: Decimal("0.00")
        for key in FEDERAL_TYPE_TO_BREAKDOWN_KEY.values()
    }


def _sum_federal_breakdown(components):
    breakdown = _empty_federal_breakdown()
    federal_types = set(FEDERAL_TAXES_941_943_944_PAYROLL_TYPES)
    for component in components:
        payroll_type = component.payroll_type
        if payroll_type not in federal_types:
            continue
        key = FEDERAL_TYPE_TO_BREAKDOWN_KEY[payroll_type]
        breakdown[key] += quantize_money(component.current or 0)
    breakdown["total_federal_taxes"] = quantize_money(
        sum(breakdown.values(), Decimal("0.00"))
    )
    return breakdown


def _federal_breakdown_response(breakdown):
    return {
        key: float(breakdown[key])
        for key in FEDERAL_TYPE_TO_BREAKDOWN_KEY.values()
    } | {"total_federal_taxes": float(breakdown["total_federal_taxes"])}


def _breakdown_lines_from_mapping(breakdown, label_map):
    lines = []
    for key, label in label_map.items():
        amount = breakdown.get(key, Decimal("0.00"))
        if amount:
            lines.append({"label": label, "amount": float(amount)})
    total = breakdown.get("total_federal_taxes") or breakdown.get("total_state_taxes")
    if total is None:
        total = sum(
            (quantize_money(v) for k, v in breakdown.items() if k.startswith(("federal_", "social_", "medicare", "state_"))),
            Decimal("0.00"),
        )
    return lines, float(total or 0)


def _resolve_active_federal_schedule(federal_tax_setting, period_end):
    if federal_tax_setting:
        items = list(federal_tax_setting.items.all())
        if items:
            current = get_current_federal_tax_item(
                items,
                PayrollFederalTaxInfoTaxFormChoices.FORM_941_EACH_QUARTER,
                reference_date=period_end,
            )
            if current:
                return current
            return max(items, key=lambda item: item.effective_date or date.min)
    return None


def build_federal_tax_periods(queryset, federal_tax_setting, *, today=None):
    """Return federal deposit liability rows from finalized payroll."""
    today = today or date.today()
    pay_period_groups = defaultdict(
        lambda: {
            "payrolls": [],
            "period_start": None,
            "period_end": None,
            "components": [],
        }
    )

    for payroll in queryset:
        start_date, end_date = parse_pay_period(payroll.pay_period)
        if not start_date or not end_date:
            continue
        period_data = pay_period_groups[payroll.pay_period]
        period_data["payrolls"].append(payroll)
        period_data["components"].extend(list(payroll.payroll_components.all()))
        if not period_data["period_start"]:
            period_data["period_start"] = start_date
            period_data["period_end"] = end_date

    federal_tax_periods = []
    for period_key, period_data in pay_period_groups.items():
        breakdown = _sum_federal_breakdown(period_data["components"])
        if breakdown["total_federal_taxes"] <= 0:
            continue

        start_date = period_data["period_start"]
        end_date = period_data["period_end"]
        schedule = _resolve_active_federal_schedule(federal_tax_setting, end_date)
        frequency = (
            schedule.payment_frequency if schedule else DEFAULT_FEDERAL_FREQUENCY
        )
        tax_form = schedule.tax_form if schedule else DEFAULT_FEDERAL_TAX_FORM

        if frequency == PayrollFederalTaxInfoSettingChoices.QUARTERLY:
            quarter = quarter_label_for_date(start_date)
            quarter_num = int(quarter[1])
            quarter_end = {
                1: date(start_date.year, 3, 31),
                2: date(start_date.year, 6, 30),
                3: date(start_date.year, 9, 30),
                4: date(start_date.year, 12, 31),
            }[quarter_num]
            due_date = calculate_federal_due_date(quarter_end, frequency, tax_form)
            tax_type = f"Federal Taxes (941/943/944) - {quarter}"
            period_label = f"{period_key} ({quarter})"
        elif frequency == PayrollFederalTaxInfoSettingChoices.MONTHLY:
            month_end = date(
                start_date.year,
                start_date.month,
                (
                    date(start_date.year, start_date.month, 1)
                    + relativedelta(months=1, days=-1)
                ).day,
            )
            due_date = calculate_federal_due_date(month_end, frequency, tax_form)
            tax_type = "Federal Taxes (941/943/944)"
            period_label = f"{start_date.strftime('%m/%d/%Y')} – {end_date.strftime('%m/%d/%Y')} ({quarter_label_for_date(start_date)})"
        else:
            due_date = calculate_federal_due_date(end_date, frequency, tax_form)
            tax_type = "Federal Taxes (941/943/944)"
            period_label = period_key

        lines, _ = _breakdown_lines_from_mapping(
            breakdown,
            FEDERAL_BREAKDOWN_LABELS,
        )

        federal_tax_periods.append(
            {
                "period_key": f"FEDERAL-{period_key}",
                "period_label": period_label,
                "period_start": start_date.isoformat(),
                "period_end": end_date.isoformat(),
                "due_date": due_date.isoformat(),
                "status": get_payment_status(due_date, today=today),
                "tax_type": tax_type,
                "tax_category": "FEDERAL",
                "account_type": "Federal Tax Liability",
                "action": "pay",
                "tax_breakdown": _federal_breakdown_response(breakdown),
                "breakdown_lines": lines,
                "payroll_count": len(period_data["payrolls"]),
            }
        )

    return federal_tax_periods


def build_futa_tax_periods(queryset, *, today=None):
    """Annual Form 940 (FUTA) liability row from finalized payroll for the year.

    Form 940 is filed once per calendar year. This returns a single row per year
    with the full-year FUTA total (not per-quarter deposit rows).
    """
    today = today or date.today()
    futa_types = set(FEDERAL_UNEMPLOYMENT_940_PAYROLL_TYPES)
    by_year = defaultdict(
        lambda: {
            "payrolls": set(),
            "components": [],
        }
    )

    for payroll in queryset:
        ref_date = getattr(payroll, "pay_date", None)
        if not ref_date:
            _, end_date = parse_pay_period(payroll.pay_period)
            ref_date = end_date
        if not ref_date:
            continue
        bucket = by_year[ref_date.year]
        bucket["payrolls"].add(payroll.pk)
        bucket["components"].extend(list(payroll.payroll_components.all()))

    futa_periods = []
    for year, bucket in sorted(by_year.items()):
        total = Decimal("0.00")
        quarterly = {
            "Q1": Decimal("0.00"),
            "Q2": Decimal("0.00"),
            "Q3": Decimal("0.00"),
            "Q4": Decimal("0.00"),
        }
        for component in bucket["components"]:
            if component.payroll_type not in futa_types:
                continue
            amount = quantize_money(component.current or 0)
            total += amount
            pay_date = component.payroll.pay_date
            if pay_date:
                quarter_key = f"Q{(pay_date.month - 1) // 3 + 1}"
                quarterly[quarter_key] += amount

        if total <= 0:
            continue

        due_date = date(year + 1, 1, 31)
        breakdown_lines = [{"label": "FUTA Employer", "amount": float(total)}]

        futa_periods.append(
            {
                "period_key": f"FUTA-{year}",
                "period_label": f"Annual {year}",
                "period_start": date(year, 1, 1).isoformat(),
                "period_end": date(year, 12, 31).isoformat(),
                "due_date": due_date.isoformat(),
                "status": get_payment_status(due_date, today=today),
                "tax_type": "Federal Unemployment (940)",
                "tax_category": "FEDERAL",
                "account_type": "Federal Unemployment Tax Liability",
                "action": "pay_and_file",
                "form_type": "940",
                "year": year,
                "tax_breakdown": {
                    "futa_employer": float(total),
                    "total_federal_unemployment_taxes": float(total),
                    "total_federal_taxes": float(total),
                },
                "breakdown_lines": breakdown_lines,
                "quarterly_futa_liability": {
                    key: float(value) for key, value in quarterly.items() if value > 0
                },
                "payroll_count": len(bucket["payrolls"]),
            }
        )

    return futa_periods


def _state_income_types(state_code):
    # Same expansion the journal poster uses, so every liability the journal
    # credits for a state also shows up in its Tax Center periods. Unrecognized
    # codes keep the old narrow behavior so the generic "_INCOME_TAX" engine
    # key can't be aggregated under a garbage state bucket.
    group_key = state_income_tax_group_key(state_code)
    if normalize_us_state(state_code):
        return set(payroll_types_for_group(group_key))
    return {group_key}


def _state_employment_types(state_code):
    group_key = state_employment_tax_group_key(state_code)
    if normalize_us_state(state_code):
        return set(payroll_types_for_group(group_key))
    return set()


def _employment_line_label(payroll_type, state_code):
    labels = {
        "NY_REEMPLOYMENT_TAX": "NY Re-employment",
        "NY_SUI_EMPLOYER": "NY SUI Employer",
        "NYS_UI_EMPLOYER": "NY SUI Employer",
        "NY_RSF": "NY RSF",
        "MN_UI_EMPLOYER": "MN UI Employer",
        "MN_WORKFORCE_DEVELOPMENT_FEE": "MN Workforce Development Fee",
        "MN_ADDITIONAL_ASSESSMENT": "MN Additional Assessment",
        "MN_PAID_LEAVE_EMPLOYER": "MN Paid Leave Employer",
    }
    if payroll_type in labels:
        return labels[payroll_type]
    normalized = (payroll_type or "").replace("_", " ").title()
    if "Sui" in normalized:
        normalized = normalized.replace("Sui", "SUI")
    return normalized


def build_state_tax_periods(queryset, *, today=None):
    today = today or date.today()
    grouped_data = defaultdict(
        lambda: {
            "payroll_processes": [],
            "period_info": {},
            "state_code": None,
            "income_by_type": defaultdict(Decimal),
            "employment_by_type": defaultdict(Decimal),
        }
    )

    for payroll_entry in queryset:
        work_location = payroll_entry.employee.work_locations
        if not work_location:
            continue
        # Mirror the journal poster's state resolution (normalize, keep raw
        # for unrecognized) so ledger and Tax Center bucket the same way.
        raw_state = work_location.location_state or ""
        state_code = normalize_us_state(raw_state) or raw_state.upper()
        if not state_code:
            continue

        start_date, end_date = parse_pay_period(payroll_entry.pay_period)
        if not start_date or not end_date:
            continue

        period_key = f"{state_code}-{payroll_entry.pay_period}"
        period_data = grouped_data[period_key]
        period_data["payroll_processes"].append(payroll_entry)
        period_data["state_code"] = state_code

        if not period_data["period_info"]:
            due_date = calculate_state_due_date(end_date, state_code)
            period_data["period_info"] = {
                "period_key": period_key,
                "period_label": payroll_entry.pay_period,
                "start_date": start_date,
                "end_date": end_date,
                "due_date": due_date,
                "status": get_payment_status(due_date, today=today),
                "quarter": quarter_label_for_date(end_date),
            }

        income_types = _state_income_types(state_code)
        employment_types = _state_employment_types(state_code)

        for component in payroll_entry.payroll_components.all():
            payroll_type = component.payroll_type
            amount = quantize_money(component.current or 0)
            if not amount:
                continue
            if payroll_type in income_types:
                period_data["income_by_type"][payroll_type] += amount
            elif payroll_type in employment_types:
                period_data["employment_by_type"][payroll_type] += amount

    state_tax_periods = []
    for period_key, period_data in grouped_data.items():
        state_code = period_data["state_code"]
        info = period_data["period_info"]
        income_total = quantize_money(
            sum(period_data["income_by_type"].values(), Decimal("0.00"))
        )
        employment_total = quantize_money(
            sum(period_data["employment_by_type"].values(), Decimal("0.00"))
        )

        if income_total > 0:
            income_lines = [
                {
                    "label": f"{state_code} Income Tax"
                    if payroll_type in ("_INCOME_TAX", f"{state_code}_INCOME_TAX")
                    else payroll_type.replace("_", " ").title(),
                    "amount": float(amount),
                }
                for payroll_type, amount in period_data["income_by_type"].items()
                if amount
            ]
            if len(income_lines) == 1:
                income_lines[0]["label"] = f"{state_code} Income Tax"

            state_tax_periods.append(
                {
                    "period_key": f"{info['period_key']}-INCOME",
                    "period_label": f"{info['period_label']} ({info['quarter']})",
                    "period_start": info["start_date"].isoformat(),
                    "period_end": info["end_date"].isoformat(),
                    "due_date": info["due_date"].isoformat(),
                    "status": info["status"],
                    "tax_type": f"{state_code} Income Tax",
                    "tax_category": "STATE",
                    "account_type": f"{state_code} Income Tax Liability",
                    "action": "pay",
                    "tax_breakdown": {
                        "state_income_tax": float(income_total),
                        "state_unemployment_tax": 0.0,
                        "state_disability_tax": 0.0,
                        "state_employment_security_assessment": 0.0,
                        "total_state_taxes": float(income_total),
                    },
                    "breakdown_lines": income_lines,
                    "payroll_count": len(period_data["payroll_processes"]),
                }
            )

        if employment_total > 0:
            employment_lines = [
                {
                    "label": _employment_line_label(payroll_type, state_code),
                    "amount": float(amount),
                }
                for payroll_type, amount in period_data["employment_by_type"].items()
                if amount
            ]
            tax_type = (
                f"{state_code} Employment Taxes"
                if state_code == "NY"
                else f"{state_code} Unemployment Tax"
            )
            state_tax_periods.append(
                {
                    "period_key": f"{info['period_key']}-EMPLOYMENT",
                    "period_label": f"{info['period_label']} ({info['quarter']})",
                    "period_start": info["start_date"].isoformat(),
                    "period_end": info["end_date"].isoformat(),
                    "due_date": info["due_date"].isoformat(),
                    "status": info["status"],
                    "tax_type": tax_type,
                    "tax_category": "STATE",
                    "account_type": f"{state_code} Unemployment Tax Liability",
                    "action": "pay_and_file",
                    "tax_breakdown": {
                        "state_income_tax": 0.0,
                        "state_unemployment_tax": float(employment_total),
                        "state_disability_tax": 0.0,
                        "state_employment_security_assessment": 0.0,
                        "total_state_taxes": float(employment_total),
                    },
                    "breakdown_lines": employment_lines,
                    "payroll_count": len(period_data["payroll_processes"]),
                }
            )

    return state_tax_periods


def _period_liability_total(period_row):
    breakdown = period_row.get("tax_breakdown") or {}
    for key in (
        "total_federal_taxes",
        "total_state_taxes",
        "total_federal_unemployment_taxes",
    ):
        value = breakdown.get(key)
        if value not in (None, ""):
            return float(value)
    return 0.0


def get_tax_period_payments(company, period_keys=None, year=None):
    """Sum paid amounts keyed by ``liability_period`` (matches ``period_key``).

    One grouped SQL query; optional filters keep the lookup scoped to the
    periods shown on the current tax center report.
    """
    from django.db.models import Q, Sum

    from payrollio.models import TaxCenterPayMethod

    rows = TaxCenterPayMethod.objects.filter(
        Q(tax_liability_account__company=company)
        | Q(tax_record_account__company=company),
        is_paid=True,
    )
    if period_keys:
        rows = rows.filter(liability_period__in=period_keys)
    if year is not None:
        rows = rows.filter(payment_date__year=year)
    rows = rows.values("liability_period").annotate(total_paid=Sum("tax_amount"))
    return {
        row["liability_period"]: float(row["total_paid"] or 0)
        for row in rows
        if row["liability_period"]
    }


def apply_tax_period_payments(tax_periods, company, year=None):
    """Attach payment totals and paid status to tax center period rows."""
    period_keys = [period.get("period_key") for period in tax_periods if period.get("period_key")]
    paid_by_period = get_tax_period_payments(
        company, period_keys=period_keys or None, year=year
    )
    for period in tax_periods:
        period_key = period.get("period_key")
        total = _period_liability_total(period)
        paid = float(paid_by_period.get(period_key, 0))
        balance = max(0.0, round(total - paid, 2))
        period["amount_paid"] = round(paid, 2)
        period["amount_due"] = balance
        period["is_paid"] = paid > 0 and balance <= 0
        if period["is_paid"]:
            period["status"] = "Paid"
        elif paid > 0:
            period["status"] = "Partially paid"
    return tax_periods


def parse_report_year(request, default=None):
    default = default or datetime.now().year
    raw = request.query_params.get("year") if request else None
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
