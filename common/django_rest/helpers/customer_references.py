"""What still points at a customer, and whether that should stop them retiring.

The sibling of `account_references.py`, and the same discipline: `Customer` has
fifteen reverse relations, and treating them alike gets the feature wrong in
either direction. History does not block — preserving it is the entire point —
while a live mapping does, because it is a promise about future documents.

**Where this deliberately differs from the account version: the balance.**
Deactivating a chart-of-account with a balance is refused, because an inactive
account carries that figure out of sight. A customer is the opposite. From
`CUSTOMER_INDUSTRY_STANDARD.md` §4, and QuickBooks and Xero both:

    Making a customer inactive must not touch the ledger. Their invoices remain
    valid, their balance remains in A/R, and the ageing report still shows them.

A customer you have stopped selling to but who still owes you money is the
ordinary case — refusing to retire them until they have paid would make the
feature useless exactly when it is wanted. So there is no balance precondition
here, and that absence is a decision rather than an omission.

The customer's own attributes — addresses, currency, terms, attachments — are
not references *to* them from elsewhere and never block.
"""

from django.apps import apps


# (app_label, ModelName, field, human label). A mapping is something that will
# generate or route a FUTURE document at this customer.
MAPPING_RELATIONS = [
    ("recurringio", "RecurringTemplate", "customer", "Recurring template"),
    ("recurringio", "RecurringTemplate", "ship_to", "Recurring template ship-to"),
    ("recurringio", "RecurringTemplateLine", "customer", "Recurring template line"),
    ("transactionio", "TransactionRuleAssign", "customer", "Bank rule target"),
]

# Not blocking, with the reason. Listed so the classification is reviewable and
# so the completeness test can assert every relation was considered.
HISTORICAL_RELATIONS = {
    ("salesio", "Sale", "customer"): "issued document",
    ("salesio", "SalePaymentReceive", "customer"): "recorded payment",
    ("creditnoteio", "CreditNote", "customer"): "issued document",
    ("journalio", "JournalEntryConnector", "customer"): "posted ledger line",
    ("transactionio", "BankDepositItem", "customer"): "recorded deposit line",
    ("datamigrationio", "DataMigrationImpactLine", "customer"): "import audit line",
    # The customer's own attributes, not references to them.
    ("addressio", "AddressConnector", "customer"): "the customer's own address",
    ("currencyio", "CurrencyConnector", "customer"): "the customer's own currency",
    ("termio", "TermConnector", "customer"): "the customer's own payment terms",
    ("fileroomio", "FileItemConnector", "customer"): "the customer's own attachment",
    # Sub-customers are the cascade precondition, not a remap target.
    ("customerio", "Customer", "parent"): "sub-customer, handled by cascade",
}


def blocking_references(customer):
    """`[{model, field, label, count, sample}]` for live mappings on this customer.

    Empty means the customer can be retired. Each entry names something to go
    and repoint, so it carries a count and examples.
    """
    found = []
    for app_label, model_name, field, label in MAPPING_RELATIONS:
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:  # pragma: no cover - app removed
            continue

        queryset = _exclude_removed(
            model.objects.filter(**{field: customer}), model
        )
        count = queryset.count()
        if not count:
            continue

        found.append(
            {
                "model": f"{app_label}.{model_name}",
                "field": field,
                "label": label,
                "count": count,
                "sample": [str(obj)[:80] for obj in queryset[:3]],
            }
        )
    return found


def _exclude_removed(queryset, model):
    """Drop soft-deleted rows; a retired template is not a live mapping."""
    if "status" not in {f.name for f in model._meta.fields}:
        return queryset
    return queryset.exclude(status__in=["REMOVED", "DELETED", "ARCHIVED"])


def active_children(customer):
    """Sub-customers that are not themselves retired."""
    from customerio.choices import CustomerStatusChoices as Status

    # `parents` is the reverse accessor for `parent`, so it yields this
    # customer's CHILDREN -- the related_name is backwards on the model, the
    # same way it is on ChartOfAccount.
    return customer.parents.exclude(
        status__in=[Status.REMOVED, Status.INACTIVE]
    )
