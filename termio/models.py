from autoslug import AutoSlugField

from django.db import models

from common.models import BaseModelWithUID

from .choicess import TermStatusChoices, TermKindChoices

from .django_rest.helpers.slug_helpers import get_term_connector_slug


from .managers import TermsQuerySet


class Term(BaseModelWithUID):
    days = models.FloatField()
    is_active = models.BooleanField(default=False)
    status = models.CharField(
        max_length=50,
        choices=TermStatusChoices.choices,
        default=TermStatusChoices.ACTIVE,
    )
    objects = TermsQuerySet.as_manager()

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    def __str__(self):
        return f"ID: {self.id}, Status: {self.status}, Active: {self.is_active}"


class TermConnector(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_term_connector_slug, unique=True, db_index=True
    )
    kind = models.CharField(choices=TermKindChoices.choices, max_length=50)

    # FK
    supplier = models.ForeignKey(
        "supplierio.Supplier", on_delete=models.CASCADE, null=True, blank=True
    )
    customer = models.ForeignKey(
        "customerio.Customer", on_delete=models.CASCADE, null=True, blank=True
    )
    sale = models.ForeignKey(
        "salesio.Sale", on_delete=models.CASCADE, null=True, blank=True
    )
    purchase = models.ForeignKey(
        "purchaseio.Purchase", on_delete=models.CASCADE, null=True, blank=True
    )
    term = models.ForeignKey("termio.Term", on_delete=models.CASCADE)

    def __str__(self):
        return f"ID: {self.pk}, Kind: {self.kind}"
