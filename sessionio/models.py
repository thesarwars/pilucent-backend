from autoslug import AutoSlugField

from django.db import models

from common.models import BaseModelWithUID

from .choices import (
    TransactionSessionStatusChoices,
    TransactionSessionKindChoices,
    TransactionSessionModelKindChoices,
    TransactionSessionLabelChoices,
)
from .django_rest.helpers.slug_helpers import get_transaction_session_slug


# Create your models here.
class TransactionSession(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_transaction_session_slug, unique=True, db_index=True
    )
    status = models.CharField(
        choices=TransactionSessionStatusChoices,
        default=TransactionSessionStatusChoices.DRAFT,
    )
    kind = models.CharField(
        choices=TransactionSessionKindChoices,
        default=TransactionSessionKindChoices.CREATED,
    )
    model_kind = models.CharField(choices=TransactionSessionModelKindChoices)
    label = models.CharField(choices=TransactionSessionLabelChoices)

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    # purchase related
    purchase = models.ForeignKey(
        "purchaseio.Purchase", on_delete=models.CASCADE, blank=True, null=True
    )
    expense = models.ForeignKey(
        "purchaseio.Expense", on_delete=models.CASCADE, blank=True, null=True
    )
    purchase_payment = models.ForeignKey(
        "purchaseio.PurchasePayment", on_delete=models.CASCADE, blank=True, null=True
    )
    pay_bill = models.ForeignKey(
        "purchaseio.PayBill", on_delete=models.CASCADE, blank=True, null=True
    )

    # sale related
    sale = models.ForeignKey(
        "salesio.Sale", on_delete=models.CASCADE, blank=True, null=True
    )
    sale_payment_receive = models.ForeignKey(
        "salesio.SalePaymentReceive", on_delete=models.CASCADE, blank=True, null=True
    )

    def __str__(self):
        return f"ID: {self.id}"
