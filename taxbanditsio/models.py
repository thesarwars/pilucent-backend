from autoslug import AutoSlugField

from django.db import models

from common.models import BaseModelWithUID

from taxbanditsio.django_rest.helpers.slug_helpers import (
    get_tax_bandits_business_account_slug,
    get_tax_bandits_return_940_slug,
    get_tax_bandits_return_941_slug,
)
from taxbanditsio.choices import (
    TaxBanditsBusinessAccountStatusChoices,
    TaxBandits940StatusChoices,
    TaxBandits941StatusChoices,
)


class TaxBanditsBusinessAccount(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_tax_bandits_business_account_slug,
        unique=True,
        always_update=False,
    )
    payer_ref = models.CharField(max_length=64, blank=True, null=True)
    legal_name = models.CharField(max_length=255, blank=True, null=True)
    ein_or_ssn = models.CharField(max_length=15, blank=True, null=True)
    contact_name = models.CharField(max_length=255, blank=True, null=True)
    contact_phone = models.CharField(max_length=25, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address1 = models.CharField(max_length=255, blank=True, null=True)
    address2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=255, blank=True, null=True)
    state = models.CharField(max_length=20, blank=True, null=True)
    zip = models.CharField(max_length=10, blank=True, null=True)
    tb_business_id = models.CharField(max_length=64, blank=True, null=True)
    status = models.CharField(
        choices=TaxBanditsBusinessAccountStatusChoices.choices,
        max_length=250,
        default=TaxBanditsBusinessAccountStatusChoices.ACTIVE,
    )
    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return self.legal_name or str(self.uid)


class TaxBanditsReturn940(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_tax_bandits_return_940_slug,
        unique=True,
        always_update=False,
    )
    tax_year = models.IntegerField(blank=True, null=True)
    record_id = models.CharField(max_length=64, blank=True, null=True)  # from Create
    submission_id = models.CharField(max_length=64, blank=True, null=True)
    status = models.CharField(
        choices=TaxBandits940StatusChoices.choices,
        max_length=250,
        default=TaxBandits940StatusChoices.DRAFT,
    )  # Draft/Transmitted/Accepted/Rejected
    pdf_url = models.URLField(blank=True, null=True)
    filing_reference = models.JSONField(blank=True, null=True)
    from_940_status = models.CharField(
        max_length=64, blank=True, null=True
    )  # from Get940Status

    # FK
    business_account = models.ForeignKey(
        TaxBanditsBusinessAccount, on_delete=models.CASCADE, null=True, blank=True
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return str(self.tax_year) + " - " + str(self.record_id)


class TaxBanditsReturn941(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_tax_bandits_return_941_slug,
        unique=True,
        always_update=False,
    )
    tax_year = models.IntegerField(blank=True, null=True)
    quarter = models.CharField(max_length=10, blank=True, null=True)
    record_id = models.CharField(max_length=64, blank=True, null=True)
    submission_id = models.CharField(max_length=64, blank=True, null=True)
    status = models.CharField(
        choices=TaxBandits941StatusChoices.choices,
        max_length=250,
        default=TaxBandits941StatusChoices.DRAFT,
    )  # Draft/Transmitted/Accepted/Rejected
    form941_payload = models.JSONField(default=dict, blank=True)

    pdf_url = models.URLField(blank=True, null=True)
    filing_reference = models.JSONField(blank=True, null=True)
    from_941_status = models.CharField(
        max_length=64, blank=True, null=True
    )  # from Get940Status

    # FK
    business_account = models.ForeignKey(
        TaxBanditsBusinessAccount, on_delete=models.CASCADE, null=True, blank=True
    )
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "employeeio.Employee", on_delete=models.SET_NULL, null=True, blank=True
    )

    def __str__(self):
        return str(self.tax_year) + " - " + str(self.record_id)