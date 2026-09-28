"""
Build Form 941 PDF field payloads from finalized payroll and federal tax settings.

PDF template field names use AcroForm indices (``f1_1[0]``, ``c1_1[2]``, etc.) — see
``docs/payroll/f941.pdf``. ``prepare_f941_form_data`` normalizes legacy keys without
``[0]`` before ``fill_f941_pdf`` runs.

Consumers:
- ``GET /we/pdf/941/?quarter=Q3&year=2026`` → generates PDF, returns ``pdf_url``
- ``GET /payroll/tax-center/filing-preview?pay_quarter=Q3&year=2026`` → same ``pdf_url``
"""

import os
import re
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum

from payrollio.choicess import (
    PayrollFederalTaxInfoSettingChoices,
    PayrollFederalTaxInfoTaxFormChoices,
)
from payrollio.django_rest.helpers.federal_tax_setting_items import (
    get_current_federal_tax_item,
)
from payrollio.django_rest.helpers.payroll_journal_mappings import (
    FEDERAL_TAXES_941_943_944_PAYROLL_TYPES,
    quantize_money,
)
from payrollio.django_rest.helpers.tax_ein_sync import normalize_ein
from payrollio.django_rest.helpers.form_941_common import money_parts, pdf_field
from payrollio.django_rest.helpers.form_941_pdf_fields import (
    EIN_DIGITS_META_KEY,
    HEADER_NAME_LINE1,
    HEADER_NAME_LINE2,
    LINE_1_EMPLOYEE_COUNT,
    LINE_4_NO_SS_MEDICARE,
    assign_header_address,
    assign_money_pair,
    remap_legacy_f941_fields,
)
from payrollio.models import (
    PayrollFederalTaxInfoSetting,
    PayrollGeneralTaxSetting,
    PayrollSalaryComponent,
)

QUARTER_MONTHS = {
    "Q1": (1, 3),
    "Q2": (4, 6),
    "Q3": (7, 9),
    "Q4": (10, 12),
}

VALID_FORM_941_QUARTERS = frozenset(QUARTER_MONTHS)

QUARTER_CHECKBOX_FIELDS = {
    "Q1": "c1_1[0]",
    "Q2": "c1_1[1]",
    "Q3": "c1_1[2]",
    "Q4": "c1_1[3]",
}

F941_NON_FORM_KEYS = frozenset(
    {
        "summary",
        "form_type",
        "form_941_fields",
        "employee_id",
        "company_id",
        "pay_quarter",
        "employee_count",
        "wages_total",
        "federal_tax_total",
        "tax_totals",
        "breakdown_lines",
        "action",
        "__ein_digits__",
    }
)

_LEGACY_FIELD_KEY = re.compile(r"^(f\d+_\d+|c\d+_\d+)$")


def get_form_941_template_path():
    """Blank IRS Form 941 PDF template (``docs/payroll/f941.pdf``)."""
    return os.path.join(settings.BASE_DIR, "docs", "payroll", "f941.pdf")


def _quarter_date_range(quarter, year):
    start_month, end_month = QUARTER_MONTHS[quarter]
    start_date = date(year, start_month, 1)
    if end_month == 12:
        end_date = date(year, 12, 31)
    else:
        end_date = date(year, end_month + 1, 1) - timedelta(days=1)
    return start_date, end_date


def _split_ein_digits(ein):
    normalized = normalize_ein(ein) or ""
    digits = [character for character in normalized if character.isdigit()]
    while len(digits) < 9:
        digits.append("")
    return digits[:9]


def _aggregate_quarter_components(company, quarter, year):
    start_date, end_date = _quarter_date_range(quarter, year)
    from payrollio.choicess import PayrollSalaryProcessStatusChoices

    return PayrollSalaryComponent.objects.filter(
        payroll__pay_date__range=(start_date, end_date),
        payroll__employee__user__companyuser__company=company,
        payroll__status=PayrollSalaryProcessStatusChoices.FINALIZED,
    )


def _sum_component_totals(components, *payroll_types):
    """Sum ``current`` for one or more ``payroll_type`` values."""
    if not payroll_types:
        return Decimal("0.00")
    return quantize_money(
        components.filter(payroll_type__in=payroll_types).aggregate(
            total=Sum("current")
        )["total"]
        or 0
    )


def _sum_ss_tips_wages(components):
    """Taxable social security tips (line 5b column 1) from tip payroll types."""
    return _sum_component_totals(
        components,
        "PAYCHECK_TIPS",
        "CASH_TIPS",
        "SOCIAL_SECURITY_TIPS",
    )


def _line1_employee_count(components, quarter):
    """Employees paid in the month that contains the 12th (line 1 pay-period rule)."""
    pay_period_month = QUARTER_MONTHS[quarter][1]
    month_count = (
        components.filter(
            payroll__pay_date__month=pay_period_month,
            payroll_category="PAY",
        )
        .values("payroll__employee")
        .distinct()
        .count()
    )
    if month_count:
        return month_count
    start_month, end_month = QUARTER_MONTHS[quarter]
    best = 0
    for month in range(start_month, end_month + 1):
        best = max(
            best,
            components.filter(
                payroll__pay_date__month=month,
                payroll_category="PAY",
            )
            .values("payroll__employee")
            .distinct()
            .count(),
        )
    return best


def _get_company_ein_number(company, general_tax=None, federal_setting=None):
    """EIN from general tax settings, falling back to federal tax settings."""
    if general_tax is None:
        general_tax = PayrollGeneralTaxSetting.objects.filter(company=company).first()
    if general_tax and general_tax.ein_number:
        return general_tax.ein_number
    if federal_setting is None:
        federal_setting = PayrollFederalTaxInfoSetting.objects.filter(
            company=company
        ).first()
    return (federal_setting.ein_number if federal_setting else "") or ""


def _get_company_address_parts(company, general_tax=None):
    if general_tax is None:
        general_tax = PayrollGeneralTaxSetting.objects.filter(company=company).first()
    if general_tax and general_tax.address:
        return {
            "lines": [
                part
                for part in [general_tax.address]
                if part
            ],
            "city": general_tax.city or "",
            "state": general_tax.state or "",
            "zip": general_tax.zip_code or "",
        }

    addresses = company.company_addresses or {}
    street = addresses.get("address") or addresses.get("street") or ""
    line2 = addresses.get("address_line_2") or addresses.get("line2") or ""
    lines = [part for part in [street, line2] if part]
    return {
        "lines": lines,
        "city": addresses.get("city") or "",
        "state": addresses.get("state") or "",
        "zip": addresses.get("zip_code") or addresses.get("zip") or "",
    }


def _apply_quarter_checkboxes(payload, quarter):
    for q, field_name in QUARTER_CHECKBOX_FIELDS.items():
        payload[field_name] = quarter == q


def prepare_f941_form_data(data):
    """
    Normalize API payload for ``fill_f941_pdf``.

    - Unwrap ``form_941_fields``
    - Append ``[0]`` to legacy text/checkbox keys (``f1_10`` → ``f1_10[0]``)
    - Set quarter checkboxes from ``quarter`` / ``pay_quarter``
  """
    if not isinstance(data, dict):
        return {}

    if isinstance(data.get("form_941_fields"), dict):
        data = {**data, **data["form_941_fields"]}

    form_data = {}
    quarter = data.get("quarter") or data.get("pay_quarter")
    ein_digits_meta = data.get(EIN_DIGITS_META_KEY)

    for key, value in data.items():
        if key == EIN_DIGITS_META_KEY:
            continue
        if key in F941_NON_FORM_KEYS or key in ("quarter", "year"):
            continue
        if key in QUARTER_CHECKBOX_FIELDS.values():
            form_data[key] = value
            continue
        if _LEGACY_FIELD_KEY.match(key):
            form_data[pdf_field(key)] = value
        else:
            form_data[key] = value

    if quarter in QUARTER_CHECKBOX_FIELDS:
        _apply_quarter_checkboxes(form_data, quarter)

    form_data = remap_legacy_f941_fields(form_data)
    if ein_digits_meta is not None:
        digits = [
            str(digit) if digit not in (None, "") else ""
            for digit in ein_digits_meta
        ]
        while len(digits) < 9:
            digits.append("")
        form_data[EIN_DIGITS_META_KEY] = digits[:9]
    return form_data


def parse_form_941_quarter(data=None, request=None):
    """Read quarter from JSON body or query string."""
    quarter = None
    if isinstance(data, dict):
        quarter = data.get("pay_quarter") or data.get("quarter")
    if not quarter and request is not None:
        quarter = request.query_params.get("pay_quarter") or request.query_params.get(
            "quarter"
        )
    return quarter


def parse_form_941_year(data=None, request=None, default=None):
    """Read year from JSON body or query string."""
    from datetime import datetime

    default = default or datetime.now().year
    raw = None
    if isinstance(data, dict):
        raw = data.get("year")
    if raw is None and request is not None:
        raw = request.query_params.get("year")
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def build_form_941_download_payload(company, quarter, year, overrides=None):
    """Build PDF field dict from payroll DB; optional ``overrides`` patch fields."""
    payload = build_form_941_pdf_payload(company, quarter, year)
    payload.pop("summary", None)
    if isinstance(overrides, dict):
        merged = prepare_f941_form_data(overrides)
        merged.pop(EIN_DIGITS_META_KEY, None)
        payload.update(merged)
    return payload


def build_form_941_summary(company, quarter, year):
    """Return quarter totals used by Tax Center filing preview."""
    components = _aggregate_quarter_components(company, quarter, year)
    totals = {}
    for payroll_type in FEDERAL_TAXES_941_943_944_PAYROLL_TYPES:
        totals[payroll_type] = quantize_money(
            components.filter(payroll_type=payroll_type).aggregate(
                total=Sum("current")
            )["total"]
            or 0
        )

    employee_count = (
        components.filter(payroll_category="PAY")
        .values("payroll__employee")
        .distinct()
        .count()
    )
    wages_total = quantize_money(
        components.filter(payroll_category="PAY").aggregate(total=Sum("current"))[
            "total"
        ]
        or 0
    )
    federal_tax_total = quantize_money(sum(totals.values(), Decimal("0.00")))

    return {
        "quarter": quarter,
        "year": year,
        "employee_count": employee_count,
        "wages_total": float(wages_total),
        "federal_tax_total": float(federal_tax_total),
        "tax_totals": {key: float(value) for key, value in totals.items()},
    }


def build_form_941_pdf_url_response(request, file_item):
    """Return stored PDF URL after backend generation."""
    return {"pdf_url": request.build_absolute_uri(file_item.file.url)}


def store_form_941_pdf_fileitem(company, pdf_path, filename, quarter, year):
    from django.core.files import File

    from fileroomio.choices import FileItemKindChoices, FileItemStatusChoices
    from fileroomio.models import FileItem

    with open(pdf_path, "rb") as pdf_file:
        return FileItem.objects.create(
            company=company,
            is_report=True,
            file=File(pdf_file, name=filename),
            kind=FileItemKindChoices.PDF,
            status=FileItemStatusChoices.PUBLISHED,
            title=f"Form 941 {quarter} {year}",
        )


def build_form_941_pdf_payload(company, quarter, year):
    """Map payroll + company data to AcroForm field keys for ``fill_f941_pdf``."""
    summary = build_form_941_summary(company, quarter, year)
    components = _aggregate_quarter_components(company, quarter, year)
    general_tax = PayrollGeneralTaxSetting.objects.filter(company=company).first()
    federal_setting = PayrollFederalTaxInfoSetting.objects.filter(
        company=company
    ).first()

    payload = {}
    ein_digits = _split_ein_digits(
        _get_company_ein_number(company, general_tax, federal_setting)
    )
    payload[EIN_DIGITS_META_KEY] = ein_digits

    business_name = (company.legal_name or company.name or "")[:50]
    payload[HEADER_NAME_LINE1] = business_name[:25]
    payload[HEADER_NAME_LINE2] = business_name[25:50]

    address = _get_company_address_parts(company, general_tax)
    assign_header_address(payload, address)

    payload[LINE_1_EMPLOYEE_COUNT] = str(_line1_employee_count(components, quarter))

    wages = summary["wages_total"]
    fit = summary["tax_totals"]["FEDERAL_INCOME_TAX"]
    ss_tax = summary["tax_totals"]["SOCIAL_SECURITY"] + summary["tax_totals"][
        "SOCIAL_SECURITY_EMPLOYER"
    ]
    med_tax = summary["tax_totals"]["MEDICARE"] + summary["tax_totals"][
        "MEDICARE_EMPLOYER"
    ]
    ss_tips_wages = float(_sum_ss_tips_wages(components))
    ss_tips_tax = (
        quantize_money(Decimal(str(ss_tips_wages)) * Decimal("0.124"))
        if ss_tips_wages
        else Decimal("0.00")
    )
    add_med_tax = float(
        _sum_component_totals(components, "MEDICARE_ADDITIONAL")
    )
    add_med_wages = (
        quantize_money(Decimal(str(add_med_tax)) / Decimal("0.009"))
        if add_med_tax
        else Decimal("0.00")
    )
    line_5e = float(
        quantize_money(
            Decimal(str(ss_tax))
            + Decimal(str(ss_tips_tax))
            + Decimal(str(med_tax))
            + Decimal(str(add_med_tax))
        )
    )
    line_5f = 0.0
    line_6 = float(
        quantize_money(
            Decimal(str(fit)) + Decimal(str(line_5e)) + Decimal(str(line_5f))
        )
    )

    assign_money_pair(payload, wages, "line_2_wages")
    assign_money_pair(payload, fit, "line_3_fit")
    payload[LINE_4_NO_SS_MEDICARE] = wages <= 0
    assign_money_pair(payload, wages, "line_5a_ss_wages")
    assign_money_pair(payload, ss_tax, "line_5a_ss_tax")
    assign_money_pair(payload, ss_tips_wages, "line_5b_ss_tips_wages")
    assign_money_pair(payload, float(ss_tips_tax), "line_5b_ss_tips_tax")
    assign_money_pair(payload, wages, "line_5c_medicare_wages")
    assign_money_pair(payload, med_tax, "line_5c_medicare_tax")
    assign_money_pair(payload, float(add_med_wages), "line_5d_add_medicare_wages")
    assign_money_pair(payload, add_med_tax, "line_5d_add_medicare_tax")
    assign_money_pair(payload, line_5e, "line_5e_ss_med_tax_total")
    assign_money_pair(payload, line_5f, "line_5f_unreported_tips")
    assign_money_pair(payload, line_6, "line_6_total_before_adj")
    line_10 = float(summary["federal_tax_total"])
    line_11 = 0.0
    line_12 = float(quantize_money(Decimal(str(line_10)) - Decimal(str(line_11))))
    line_13 = 0.0
    line_14 = float(quantize_money(Decimal(str(line_12)) - Decimal(str(line_13))))
    assign_money_pair(payload, line_10, "line_10_total")
    assign_money_pair(payload, line_12, "line_12_total_after_credits")
    if line_14 > 0:
        assign_money_pair(payload, line_14, "line_14_balance_due")
    assign_money_pair(payload, line_10, "part2_total_tax")

    schedule = None
    if federal_setting:
        items = list(federal_setting.items.all())
        _, end_date = _quarter_date_range(quarter, year)
        schedule = get_current_federal_tax_item(
            items,
            PayrollFederalTaxInfoTaxFormChoices.FORM_941_EACH_QUARTER,
            reference_date=end_date,
        )
        if schedule is None and items:
            schedule = max(items, key=lambda item: item.effective_date or date.min)

    frequency = (
        schedule.payment_frequency
        if schedule
        else PayrollFederalTaxInfoSettingChoices.MONTHLY
    )
    # Part 3 deposit schedule (Line 16): c2_1[1]=monthly, c2_1[2]=semi-weekly.
    payload["c2_1[1]"] = frequency == PayrollFederalTaxInfoSettingChoices.MONTHLY
    payload["c2_1[2]"] = (
        frequency == PayrollFederalTaxInfoSettingChoices.SEMI_WEEKLY
    )

    # Part 4 third-party designee: default to "No".
    payload["c2_4[0]"] = False
    payload["c2_4[1]"] = True

    _apply_quarter_checkboxes(payload, quarter)

    payload["quarter"] = quarter
    payload["year"] = str(year)
    payload["form_type"] = "941"
    payload["summary"] = summary
    return payload


def get_form_941_sample_payload():
    """Sample JSON aligned with ``docs/payroll/f941.pdf`` layout."""
    sample = {
        EIN_DIGITS_META_KEY: list("123456789"),
        HEADER_NAME_LINE1: "ABC Company",
        HEADER_NAME_LINE2: "Inc.",
        "quarter": "Q1",
        "year": "2025",
        "form_type": "941",
        LINE_1_EMPLOYEE_COUNT: "25",
        LINE_4_NO_SS_MEDICARE: False,
        "c1_1[0]": True,
        "c1_1[1]": False,
        "c1_1[2]": False,
        "c1_1[3]": False,
        "c2_3[0]": True,
        "c2_4[0]": False,
        "c2_4[1]": False,
    }
    assign_header_address(
        sample,
        {
            "lines": ["123 Main Street"],
            "city": "New York",
            "state": "NY",
            "zip": "10001",
        },
    )
    assign_money_pair(sample, 125000, "line_2_wages")
    assign_money_pair(sample, 18750, "line_3_fit")
    assign_money_pair(sample, 125000, "line_5a_ss_wages")
    assign_money_pair(sample, 15500, "line_5a_ss_tax")
    assign_money_pair(sample, 0, "line_5b_ss_tips_wages")
    assign_money_pair(sample, 0, "line_5b_ss_tips_tax")
    assign_money_pair(sample, 125000, "line_5c_medicare_wages")
    assign_money_pair(sample, 3625, "line_5c_medicare_tax")
    assign_money_pair(sample, 0, "line_5d_add_medicare_wages")
    assign_money_pair(sample, 0, "line_5d_add_medicare_tax")
    assign_money_pair(sample, 19125, "line_5e_ss_med_tax_total")
    assign_money_pair(sample, 0, "line_5f_unreported_tips")
    assign_money_pair(sample, 37875, "line_6_total_before_adj")
    assign_money_pair(sample, 37875, "line_10_total")
    assign_money_pair(sample, 37875, "part2_total_tax")
    return remap_legacy_f941_fields(sample)
