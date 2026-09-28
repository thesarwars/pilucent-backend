"""
Build Form 940 PDF field payloads from finalized payroll and company settings.

Template: ``docs/payroll/f940.pdf``
Reference fill: ``docs/940_fillup_quickbooks.pdf``
"""

import os
from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum

from payrollio.choicess import PayrollSalaryProcessStatusChoices
from payrollio.django_rest.helpers.form_941_builder import (
    _get_company_address_parts,
    _get_company_ein_number,
    _split_ein_digits,
)
from payrollio.django_rest.helpers.form_940_pdf_fields import (
    EIN_DIGITS_META_KEY,
    HEADER_NAME_LINE1,
    HEADER_NAME_LINE2,
    LINE_1B_MULTI_STATE,
    LINE_2_CREDIT_REDUCTION,
    PART6_DESIGNEE_NO,
    assign_header_address,
    assign_money_pair,
    assign_quarter_liability,
    assign_state_abbreviation,
    prepare_f940_form_data,
)
from payrollio.django_rest.helpers.payroll_journal_mappings import (
    FEDERAL_UNEMPLOYMENT_940_PAYROLL_TYPES,
    quantize_money,
)
from payrollio.models import (
    PayrollFederalTaxInfoSetting,
    PayrollGeneralTaxSetting,
    PayrollSalaryComponent,
)

FUTA_WAGE_BASE = Decimal("7000")
FUTA_RATE = Decimal("0.006")


def get_form_940_template_path():
    return os.path.join(settings.BASE_DIR, "docs", "payroll", "f940.pdf")


def parse_form_940_year(data=None, request=None, default=None):
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


def _aggregate_year_components(company, year):
    return PayrollSalaryComponent.objects.filter(
        payroll__pay_date__year=year,
        payroll__employee__user__companyuser__company=company,
        payroll__status=PayrollSalaryProcessStatusChoices.FINALIZED,
    )


def _employee_wage_totals(components):
    totals = defaultdict(lambda: Decimal("0.00"))
    for component in components.filter(payroll_category="PAY"):
        totals[component.payroll.employee_id] += quantize_money(component.current or 0)
    return totals


def _futa_amounts(components):
    """Compute Form 940 Part 2 lines 3–8 from finalized payroll."""
    employee_wages = _employee_wage_totals(components)
    line_3 = quantize_money(sum(employee_wages.values(), Decimal("0.00")))
    line_4 = Decimal("0.00")
    line_5 = quantize_money(
        sum(
            (max(Decimal("0.00"), wages - FUTA_WAGE_BASE) for wages in employee_wages.values()),
            Decimal("0.00"),
        )
    )
    line_6 = quantize_money(line_4 + line_5)
    line_7 = quantize_money(max(Decimal("0.00"), line_3 - line_6))
    line_8 = quantize_money(line_7 * FUTA_RATE)

    futa_from_payroll = quantize_money(
        components.filter(payroll_type__in=FEDERAL_UNEMPLOYMENT_940_PAYROLL_TYPES).aggregate(
            total=Sum("current")
        )["total"]
        or 0
    )
    if futa_from_payroll > 0 and line_8 <= 0:
        line_8 = futa_from_payroll

    return {
        "line_3_total_payments": float(line_3),
        "line_4_exempt_payments": float(line_4),
        "line_5_excess_wages": float(line_5),
        "line_6_subtotal": float(line_6),
        "line_7_taxable_futa_wages": float(line_7),
        "line_8_futa_before_adj": float(line_8),
        "futa_tax_from_payroll": float(futa_from_payroll),
    }


def _quarterly_futa_totals(components):
    totals = {"Q1": Decimal("0.00"), "Q2": Decimal("0.00"), "Q3": Decimal("0.00"), "Q4": Decimal("0.00")}
    for component in components.filter(
        payroll_type__in=FEDERAL_UNEMPLOYMENT_940_PAYROLL_TYPES
    ):
        pay_date = component.payroll.pay_date
        if not pay_date:
            continue
        quarter = (pay_date.month - 1) // 3 + 1
        totals[f"Q{quarter}"] += quantize_money(component.current or 0)
    return {key: float(value) for key, value in totals.items()}


def build_form_940_summary(company, year):
    components = _aggregate_year_components(company, year)
    amounts = _futa_amounts(components)
    quarterly = _quarterly_futa_totals(components)

    line_8 = amounts["line_8_futa_before_adj"]
    line_9 = 0.0
    line_10 = 0.0
    line_11 = 0.0
    line_12 = float(
        quantize_money(
            Decimal(str(line_8))
            + Decimal(str(line_9))
            + Decimal(str(line_10))
            + Decimal(str(line_11))
        )
    )
    line_13 = 0.0
    line_14 = float(
        quantize_money(Decimal(str(line_12)) - Decimal(str(line_13)))
    )

    employee_count = (
        components.filter(payroll_category="PAY")
        .values("payroll__employee")
        .distinct()
        .count()
    )

    return {
        "year": year,
        "employee_count": employee_count,
        **amounts,
        "line_9_adjustment_all_excluded": line_9,
        "line_10_adjustment_some_excluded": line_10,
        "line_11_credit_reduction": line_11,
        "line_12_total_futa_tax": line_12,
        "line_13_deposits": line_13,
        "line_14_balance_due": line_14,
        "quarterly_futa_liability": quarterly,
    }


def build_form_940_pdf_payload(company, year):
    summary = build_form_940_summary(company, year)
    components = _aggregate_year_components(company, year)
    general_tax = PayrollGeneralTaxSetting.objects.filter(company=company).first()
    federal_setting = PayrollFederalTaxInfoSetting.objects.filter(company=company).first()

    payload = {}
    payload[EIN_DIGITS_META_KEY] = _split_ein_digits(
        _get_company_ein_number(company, general_tax, federal_setting)
    )

    business_name = (company.legal_name or company.name or "")[:50]
    payload[HEADER_NAME_LINE1] = business_name[:25]
    payload[HEADER_NAME_LINE2] = business_name[25:50]

    address = _get_company_address_parts(company, general_tax)
    assign_header_address(payload, address)
    assign_state_abbreviation(payload, address.get("state"))

    payload[LINE_1B_MULTI_STATE] = False
    payload[LINE_2_CREDIT_REDUCTION] = False

    assign_money_pair(payload, summary["line_3_total_payments"], "line_3_total_payments")
    assign_money_pair(payload, summary["line_4_exempt_payments"], "line_4_exempt_payments")
    assign_money_pair(payload, summary["line_5_excess_wages"], "line_5_excess_wages")
    assign_money_pair(payload, summary["line_6_subtotal"], "line_6_subtotal")
    assign_money_pair(payload, summary["line_7_taxable_futa_wages"], "line_7_taxable_futa_wages")
    assign_money_pair(payload, summary["line_8_futa_before_adj"], "line_8_futa_before_adj")
    assign_money_pair(payload, summary["line_12_total_futa_tax"], "line_12_total_futa_tax")

    if summary["line_14_balance_due"] > 0:
        assign_money_pair(payload, summary["line_14_balance_due"], "line_14_balance_due")

    line_12 = summary["line_12_total_futa_tax"]
    if line_12 > 500:
        quarterly = summary["quarterly_futa_liability"]
        for quarter in ("Q1", "Q2", "Q3", "Q4"):
            amount = quarterly.get(quarter, 0.0)
            if amount > 0:
                assign_quarter_liability(payload, amount, quarter)
        assign_quarter_liability(payload, line_12, "line_17_total")

    payload[PART6_DESIGNEE_NO] = True
    payload["year"] = str(year)
    payload["form_type"] = "940"
    payload["summary"] = summary
    return payload


def build_form_940_download_payload(company, year, overrides=None):
    payload = build_form_940_pdf_payload(company, year)
    payload.pop("summary", None)
    if isinstance(overrides, dict):
        merged = prepare_f940_form_data(overrides)
        merged.pop(EIN_DIGITS_META_KEY, None)
        payload.update(merged)
    return payload


def build_form_940_pdf_url_response(request, file_item):
    return {"pdf_url": request.build_absolute_uri(file_item.file.url)}


def store_form_940_pdf_fileitem(company, pdf_path, filename, year):
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
            title=f"Form 940 {year}",
        )
