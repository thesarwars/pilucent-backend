from autoslug import AutoSlugField

import calendar
from datetime import date, timedelta

from decimal import Decimal

from dateutil.relativedelta import relativedelta

from salesio.models import Sale, SaleItem

from django.db.models.functions import Coalesce
from django.db.models import Q, Sum, F, ExpressionWrapper, DecimalField
from django.db import models

from common.models import BaseModelWithUID, BaseModelWithoutTitle

from .choices import (
    AgencyFillingFrequencyChoices,
    AgencyReportingMethod,
    AgencyStatusChoices,
    AgencyStartOfPeriodChoices,
)
from .django_rest.helpers.slug_helpers import (
    get_agency_slug,
    get_agency_tax_slug,
    get_group_tax_slug,
)
from .managers import AgencyQuerySet


class Agency(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_agency_slug, unique=True, db_index=True)
    filling_frequency = models.CharField(
        max_length=50, choices=AgencyFillingFrequencyChoices
    )
    reporting_method = models.CharField(
        max_length=50, choices=AgencyReportingMethod.choices
    )
    status = models.CharField(max_length=50, choices=AgencyStatusChoices)
    date = models.DateField(default=date.today)
    start_of_period = models.CharField(
        max_length=50, choices=AgencyStartOfPeriodChoices, blank=True, null=True
    )
    state = models.CharField(max_length=100, blank=True, null=True)

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    objects = AgencyQuerySet.as_manager()

    def _fiscal_start_month(self):
        """Fiscal-year start month number (1-12); defaults to January."""
        if not self.start_of_period:
            return 1
        try:
            return list(calendar.month_name).index(self.start_of_period)
        except ValueError:
            return 1

    def _fiscal_year_start(self, today):
        """First day of the fiscal year that ``today`` falls in."""
        anchor = self._fiscal_start_month()
        start = date(today.year, anchor, 1)
        if start > today:
            start = date(today.year - 1, anchor, 1)
        return start

    def current_period_bounds(self, today=None):
        """(start_date, end_date) of the agency's CURRENT open filing period.

        Anchored on ``filling_frequency``; QUARTERLY/ANNUALLY use
        ``start_of_period`` as the fiscal-year start month. The basis
        (accrual vs cash) doesn't change the window, only which sales fall in it.
        """
        today = today or date.today()
        freq = self.filling_frequency

        if freq == AgencyFillingFrequencyChoices.DAILY:
            return today, today

        if freq == AgencyFillingFrequencyChoices.WEEKLY:
            start = today - timedelta(days=today.weekday())  # Monday
            return start, start + timedelta(days=6)

        if freq == AgencyFillingFrequencyChoices.QUARTERLY:
            fy_start = self._fiscal_year_start(today)
            months = (today.year - fy_start.year) * 12 + (today.month - fy_start.month)
            start = fy_start + relativedelta(months=(months // 3) * 3)
            return start, start + relativedelta(months=3) - timedelta(days=1)

        if freq == AgencyFillingFrequencyChoices.ANNUALLY:
            start = self._fiscal_year_start(today)
            return start, start + relativedelta(years=1) - timedelta(days=1)

        # MONTHLY (and the safe default)
        start = today.replace(day=1)
        return start, start + relativedelta(months=1) - timedelta(days=1)

    def get_sale_overview(self, today=None):
        """Taxable / non-taxable / gross / tax-owed for the CURRENT open filing
        period, plus the effective combined rate.

        Computed on **accrual** basis (recognised on the sale/document date);
        cash basis is a follow-up. ``tax_owed`` sums ``Sale.total_tax`` for the
        period — matching how the tax-tracker computes each period's tax, so the
        hero card and the filing-periods table agree. ``combined_rate`` is the
        effective decimal rate (tax_owed / taxable, 0 when there are no taxable
        sales). Reconciles: ``gross == taxable + non_taxable``.
        """
        start, end = self.current_period_bounds(today)
        agency_taxes = AgencyTax.objects.filter(tax_groups__agency=self)

        decimal_total = DecimalField(max_digits=19, decimal_places=3)
        line_totals = SaleItem.objects.filter(
            tax__in=agency_taxes,
            sale__date__gte=start,
            sale__date__lte=end,
        ).aggregate(
            total_taxable_sale=Coalesce(
                Sum(
                    ExpressionWrapper(F("total"), output_field=decimal_total),
                    filter=Q(is_tax=True),
                ),
                Decimal("0.000"),
            ),
            total_non_taxable_sale=Coalesce(
                Sum(
                    ExpressionWrapper(F("total"), output_field=decimal_total),
                    filter=Q(is_tax=False),
                ),
                Decimal("0.000"),
            ),
            total_gross_sale=Coalesce(
                Sum(ExpressionWrapper(F("total"), output_field=decimal_total)),
                Decimal("0.000"),
            ),
        )

        # Tax owed = sum of each period sale's total_tax, once per sale. Resolve
        # the distinct sale ids first so a sale with several agency-taxed lines
        # isn't multiplied by the saleitem join.
        period_sale_ids = (
            Sale.objects.filter(
                company=self.company,
                date__gte=start,
                date__lte=end,
                saleitem__tax__in=agency_taxes,
            )
            .values_list("id", flat=True)
            .distinct()
        )
        tax_owed = Sale.objects.filter(id__in=period_sale_ids).aggregate(
            total=Coalesce(Sum("total_tax"), Decimal("0.000"))
        )["total"] or Decimal("0.000")

        taxable = line_totals["total_taxable_sale"] or Decimal("0.000")
        combined_rate = (
            (tax_owed / taxable).quantize(Decimal("0.0001"))
            if taxable
            else Decimal("0.0000")
        )

        return {
            "total_taxable_sale": taxable,
            "total_non_taxable_sale": line_totals["total_non_taxable_sale"],
            "total_gross_sale": line_totals["total_gross_sale"],
            "tax_owed": tax_owed.quantize(Decimal("0.01")),
            "combined_rate": combined_rate,
        }

    def __str__(self):
        return f"ID: {self.id}, Filling Frequency: {self.filling_frequency}"


# class AgencyTax(BaseModelWithUID):
#     slug = AutoSlugField(populate_from=get_agency_tax_slug, unique=True, db_index=True)
#     rate = models.FloatField()
#     is_single = models.BooleanField(default=True)
#     parent = models.ForeignKey(
#         'self',
#         null=True,
#         blank=True,
#         on_delete=models.SET_NULL,
#         related_name='children'
#     )

#     # FK
#     agency = models.ForeignKey(Agency, on_delete=models.CASCADE)
#     sales_tax_account = models.ForeignKey(
#         "accounts.ChartOfAccount",
#         on_delete=models.CASCADE,
#         related_name="sales_tax_account_set",
#     )
#     purchase_tax_account = models.ForeignKey(
#         "accounts.ChartOfAccount",
#         on_delete=models.CASCADE,
#         related_name="purchase_tax_account_set",
#         blank=True, null=True
#     )

#     def __str__(self):
#         return f"ID: {self.id}, Title: {getattr(self, 'title', self.slug)}"


# class AgencyTaxGroup(BaseModelWithoutTitle):
#     name = models.CharField(max_length=100)
#     taxes = models.ManyToManyField('AgencyTax', related_name='tax_groups', blank=True)


#     def __str__(self):
#         return f"ID: {self.id}, Name: {self.name}"


#     @property
#     def total_rate(self):
#         return sum(t.rate for t in self.taxes.all())


class AgencyTax(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_agency_tax_slug, unique=True, db_index=True)
    is_single = models.BooleanField(default=True)
    total_rate = models.FloatField(default=0.0)
    company = models.ForeignKey(
        "companyio.Company", on_delete=models.CASCADE, blank=True, null=True
    )
    # FK
    # agency = models.ForeignKey(Agency, on_delete=models.CASCADE)

    def __str__(self):
        return f"ID: {self.id}, Title: {self.title}"

    def get_sale_overview(self):
        return self.saleitem_set.aggregate(
            total_taxable_sale=Coalesce(
                Sum(
                    ExpressionWrapper(
                        F("total"),
                        output_field=DecimalField(max_digits=19, decimal_places=3),
                    ),
                    filter=Q(is_tax=True),
                ),
                Decimal("0.000"),
            ),
            total_non_taxable_sale=Coalesce(
                Sum(
                    ExpressionWrapper(
                        F("total"),
                        output_field=DecimalField(max_digits=19, decimal_places=3),
                    ),
                    filter=Q(is_tax=False),
                ),
                Decimal("0.000"),
            ),
            total_gross_sale=Coalesce(
                Sum(
                    ExpressionWrapper(
                        F("sale_price") * F("quantity"),
                        output_field=DecimalField(max_digits=19, decimal_places=3),
                    )
                ),
                Decimal("0.000"),
            ),
        )


class AgencyTaxSet(BaseModelWithoutTitle):
    slug = AutoSlugField(populate_from=get_group_tax_slug, unique=True, db_index=True)
    nickname = models.CharField(max_length=100, blank=True, null=True)
    rate = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    taxes = models.ForeignKey(
        "AgencyTax", related_name="tax_groups", on_delete=models.CASCADE, blank=True
    )
    agency = models.ForeignKey("Agency", on_delete=models.CASCADE)
    sales_tax_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        on_delete=models.CASCADE,
        related_name="sales_tax_account_set",
    )
    # purchase_tax_account = models.ForeignKey(
    #     "accounts.ChartOfAccount",
    #     on_delete=models.CASCADE,
    #     related_name="purchase_tax_account_set",
    #     blank=True, null=True
    # )

    def __str__(self):
        return f"ID: {self.id}, Name: {self.nickname}"
