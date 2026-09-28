"""Tax snapshot aggregations for the v2 dashboard.

This is a high-level rollup for the dashboard card only. The authoritative
federal/state payroll tax breakdown lives in the Tax Center report
(``payrollio/django_rest/helpers/tax_center_rollup.py``); here we summarize:
- sales tax liability (open / overdue / next due) from ``salesio.SalesTax``
- payroll tax liability from FINALIZED payroll runs in the period
"""

from datetime import date, datetime
from decimal import Decimal

from django.db.models import Q, Sum, Count, DecimalField
from django.db.models.functions import Coalesce

from salesio.models import SalesTax
from salesio.choices import SalesTaxStatusChoices

from .hr import payroll_runs_qs

from payrollio.choicess import PayrollSalaryProcessStatusChoices


ZERO = Decimal("0.00")

OPEN_SALES_TAX_STATUSES = [
    SalesTaxStatusChoices.ACTIVE,
    SalesTaxStatusChoices.OPEN,
    SalesTaxStatusChoices.DUE,
    SalesTaxStatusChoices.OVER_DUE,
]


def sales_tax_snapshot(company, today=None):
    today = today or date.today()
    qs = SalesTax.objects.filter(
        company=company, status__in=OPEN_SALES_TAX_STATUSES
    )
    agg = qs.aggregate(
        liability=Coalesce(
            Sum("total_sales_tax"), ZERO, output_field=DecimalField()
        ),
        count=Count("id"),
    )
    overdue = qs.filter(
        Q(status=SalesTaxStatusChoices.OVER_DUE)
        | Q(sales_tax_due_date__lt=today)
    ).aggregate(
        amount=Coalesce(Sum("total_sales_tax"), ZERO, output_field=DecimalField()),
        count=Count("id"),
    )
    next_due = (
        qs.filter(sales_tax_due_date__gte=today)
        .order_by("sales_tax_due_date")
        .values_list("sales_tax_due_date", flat=True)
        .first()
    )
    return {
        "liability": float(agg["liability"]),
        "open_count": agg["count"],
        "overdue_amount": float(overdue["amount"]),
        "overdue_count": overdue["count"],
        "next_due_date": next_due.isoformat() if next_due else None,
    }


def payroll_tax_liability(company, date_from, date_to):
    qs = payroll_runs_qs(company).filter(
        status=PayrollSalaryProcessStatusChoices.FINALIZED,
        pay_date__range=[date_from, date_to],
    )
    agg = qs.aggregate(
        employee_taxes=Coalesce(
            Sum("employee_taxes_deductions"), ZERO, output_field=DecimalField()
        ),
        employer_taxes=Coalesce(
            Sum("employer_taxes_contributions"), ZERO, output_field=DecimalField()
        ),
    )
    return {
        "employee_taxes": float(agg["employee_taxes"]),
        "employer_taxes": float(agg["employer_taxes"]),
        "total": float(agg["employee_taxes"] + agg["employer_taxes"]),
    }


def tax_due(company, today=None):
    """Upcoming/open tax obligation for the Tax Due KPI.

    Uses the open sales-tax liability and its next due date.
    """
    today = today or date.today()
    snapshot = sales_tax_snapshot(company, today=today)
    due_date = None
    if snapshot["next_due_date"]:
        due_date = datetime.strptime(snapshot["next_due_date"], "%Y-%m-%d").date()
    days_until = (due_date - today).days if due_date else None
    return {
        "amount": snapshot["liability"],
        "due_date": due_date,
        "days_until": days_until,
    }


def tax_center_snapshot(company, date_from, date_to, today=None):
    sales = sales_tax_snapshot(company, today=today)
    payroll = payroll_tax_liability(company, date_from, date_to)
    total_liability = sales["liability"] + payroll["total"]
    return {
        "total_liability": round(total_liability, 2),
        "sales_tax": sales,
        "payroll_tax": payroll,
    }
