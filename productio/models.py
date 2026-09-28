from autoslug import AutoSlugField
from django.db.models import Q, Sum
from django.db import models

from common.models import BaseModelWithUID

from .choices import (
    ProductKindChoices,
    ProductStatusChoices,
    ProductBundleStatusChoices,
)
from purchaseio.choices import PurchaseStatus, PurchaseItemStatus
from .django_rest.helpers.slug_helpers import get_product_slug, get_product_bundle_slug
from .managers import ProductQuerySet, ProductBundleQuerySet
from purchaseio.models import PurchaseItem


class Product(BaseModelWithUID):
    slug = AutoSlugField(populate_from=get_product_slug, unique=True, db_index=True)
    sku = models.CharField(max_length=100)
    code = models.CharField(blank=True, null=True, max_length=50)
    quantity = models.PositiveIntegerField()
    date = models.DateField()
    reorder_point = models.PositiveIntegerField(blank=True, null=True)
    expired_date = models.DateField(blank=True, null=True)

    description = models.TextField(blank=True, null=True)
    sale_price = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)

    kind = models.CharField(max_length=20, choices=ProductKindChoices)
    status = models.CharField(max_length=20, choices=ProductStatusChoices)
    vat = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)

    is_non_stock = models.BooleanField(default=False)
    is_stock = models.BooleanField(default=False)
    is_purchased = models.BooleanField(default=False)
    is_inventory = models.BooleanField(default=False)

    is_addtional_cost = models.BooleanField(default=False)

    # FK
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)
    asset_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        related_name="asset_account_set",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    income_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        related_name="income_account_set",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    # Cost of sales, alongside the other two. It had no home here: the expense
    # account lived on ProductAdditionalCost, a child row the client only got if
    # it sent a truthy `is_addtional_cost`, so whether an inventory item had a
    # cost-of-sales account at all was the client's choice. Income, inventory
    # asset and cost of sales are the three accounts an inventory item posts to;
    # two of them were first-class and the third was optional metadata.
    #
    # Nullable, and read in preference to the cost row where set. Existing
    # products keep resolving through that row, and through the company's COGS
    # control account when they have none.
    cogs_account = models.ForeignKey(
        "accounts.ChartOfAccount",
        related_name="cogs_account_set",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )

    objects = ProductQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.id}, Title: {self.title}"

    def get_purchase_price(self):
        additional_cost = self.productadditionalcost_set.first()
        return additional_cost.amount if additional_cost else 0

    def save(self, *args, **kwargs):
        # `is_inventory` is derived, not accepted. It is one of four independent
        # client-supplied booleans that between them encode 16 states where at
        # most three are meaningful, and nothing ever normalised them -- which is
        # how production came to hold 20 services flagged as inventory.
        #
        # Item type is a server-controlled attribute, so the flag is set from the
        # type rather than trusted from the payload, and contradictory state
        # stops being representable. `is_non_stock` is left alone: it is a real
        # choice a user makes about a stocked item, and it feeds the derivation
        # rather than following from it.
        self.is_inventory = self.tracks_stock()
        super().save(*args, **kwargs)

    @staticmethod
    def stocked_filter_for(prefix=""):
        """The queryset equivalent of `tracks_stock()`.

        Reports filtered on `is_inventory` while posting decided by item type,
        which is how a service could hold stock the reports never showed -- and,
        on production, how twenty services came to be counted AS inventory. One
        predicate, asked the same way on both sides, is what makes the ledger
        and the reports capable of tying at all.
        """
        path = f"{prefix}__" if prefix else ""
        return Q(**{f"{path}kind": ProductKindChoices.PRODUCT}) & ~Q(
            **{f"{path}is_non_stock": True}
        )

    def tracks_stock(self):
        """Whether this item maintains quantity on hand and cost layers.

        No posting path used to ask. A supplier bill for a Service item ran the
        whole inventory block -- quantity set, a PURCHASE movement appended to
        the ledger, the cost debited to Inventory Asset -- and invoicing that
        service then consumed those layers and posted COGS against them. Since
        the inventory reports filter on `is_inventory`, none of it ever showed:
        stock movement existed that no report could display and that could never
        be reconciled against the Inventory Asset account.

        Gated on `kind`, not on `is_inventory`. All four of those booleans
        default to False and three of them have no readers anywhere, so a
        product whose client never sent them is indistinguishable from one
        deliberately marked non-inventory. Gating on `is_inventory` would
        therefore switch tracking OFF for most existing products -- a far worse
        failure than the one being fixed. `kind` is required and meaningful.

        `is_non_stock` is honoured when it is set, since a caller that took the
        trouble to say so means it.

        The inventory reports ask the same question through
        `stocked_filter_for()`, so posting and reporting cannot disagree about
        what counts as stock. `is_inventory` is left as a client-facing flag with
        no bearing on either.
        """
        if self.is_non_stock:
            return False
        return self.kind == ProductKindChoices.PRODUCT



class ProductAdditionalCost(BaseModelWithUID):
    # TODO : Need to add slug
    amount = models.DecimalField(default=0.00, max_digits=19, decimal_places=3)
    description = models.TextField(blank=True, null=True)

    # FK
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    expense_account = models.ForeignKey(
        "accounts.ChartOfAccount", on_delete=models.CASCADE
    )
    prefferred_supplier = models.ForeignKey(
        "supplierio.Supplier", on_delete=models.CASCADE, blank=True, null=True
    )
    tax = models.ForeignKey(
        "agencyio.AgencyTax",
        # See salesio.SaleItem.tax. This row also carries `expense_account`, which
        # `resolve_cogs_account` reads to post cost of sales, so cascading it away
        # on a tax deletion silently removed a product's cost account too.
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    def __str__(self):
        return (
            f"ID: {self.id}, Title: {self.product.title}, Product: {self.product.title}"
        )


class ProductBundle(BaseModelWithUID):
    slug = AutoSlugField(
        populate_from=get_product_bundle_slug, unique=True, db_index=True
    )
    sku = models.CharField(max_length=100)
    status = models.CharField(
        max_length=20,
        choices=ProductBundleStatusChoices,
        default=ProductBundleStatusChoices.DRAFT,
    )
    description = models.TextField(blank=True, null=True)
    company = models.ForeignKey("companyio.Company", on_delete=models.CASCADE)

    objects = ProductBundleQuerySet.as_manager()

    def __str__(self):
        return f"ID: {self.id}, Title: {self.title}"


class ProductBundleConnector(BaseModelWithUID):
    # TODO : Need to add slug
    products = models.ForeignKey(Product, on_delete=models.CASCADE)
    product_bundle = models.ForeignKey(ProductBundle, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"ID: {self.id}, Product: {self.products.title}, Bundle: {self.product_bundle.title}"
