"""What still points at an account, and whether that should stop it retiring.

Spec BLZ-FIN-COA-SPEC-001 s9.4 precondition B: deactivation is refused while the
account is *a live default mapping*, and the dialog must list what to remap.

The distinction this module exists to make is between two kinds of reference,
because `ChartOfAccount` has **40 reverse relations** and treating them alike
gets the feature backwards in either direction:

**History does not block.** A sale, a bill, a journal line or a finished payroll
run naming the account is exactly what deactivation is designed to preserve --
s9.4 says an inactive account "remains in historical reports, registers, and
audit views". Blocking on history would make the feature useless, since any
account worth retiring has been used.

**Mappings do block.** A product's income account, a tax agency's liability
account, a payroll preference or a recurring template is a promise about
*future* postings. Deactivate underneath one and the next invoice, pay run or
scheduled document either fails or posts somewhere unintended.

So the list below is curated, not derived. A derived list would have to guess,
and guessing wrong in the permissive direction breaks posting silently. Adding a
mapping FK to any model means adding it here; the test suite asserts every
relation is classified, so a new one fails loudly rather than defaulting to
"safe".
"""

from django.apps import apps


# (app_label, ModelName, field, human label). The spec names five families --
# products and services, tax agencies, payroll items, payment methods and
# recurring templates -- plus the per-customer receivable override we added.
MAPPING_RELATIONS = [
    ("productio", "Product", "income_account", "Product income account"),
    ("productio", "Product", "asset_account", "Product inventory asset account"),
    ("productio", "Product", "cogs_account", "Product cost-of-goods account"),
    ("productio", "ProductAdditionalCost", "expense_account", "Product additional cost"),
    ("agencyio", "AgencyTaxSet", "sales_tax_account", "Sales tax agency"),
    ("customerio", "Customer", "charter_account", "Customer receivable override"),
    ("recurringio", "RecurringTemplate", "payment_account", "Recurring template payment account"),
    ("recurringio", "RecurringTemplate", "cash_back_account", "Recurring template cash-back account"),
    ("recurringio", "RecurringTemplateLine", "charter_account", "Recurring template line"),
    ("payrollio", "PayrollAccountingPreferencesSetting", "global_wage_account", "Payroll wage account"),
    ("payrollio", "PayrollAccountingPreferencesSetting", "global_employer_tax_expenses", "Payroll employer-tax account"),
    ("payrollio", "PayrollAccountingPreferencesSetting", "global_contribution_expense_account", "Payroll contribution account"),
    ("payrollio", "PayrollAccountingPreferencesSetting", "paycheck_payroll_tax_expense_account", "Paycheck payroll-tax account"),
    ("payrollio", "PayrollAccountExpenseAccountComponent", "expense_account", "Payroll item mapping"),
    ("payrollio", "TaxCenterPayMethod", "tax_liability_account", "Tax payment method liability account"),
    ("payrollio", "TaxCenterPayMethod", "tax_record_account", "Tax payment method record account"),
    # Bank-feed rules decide where *future* statement lines are categorised, so
    # they are mappings even though they live beside transaction history.
    ("transactionio", "TransactionRules", "bank_accounts", "Bank rule (account scope)"),
    ("transactionio", "TransactionRuleAssign", "chart_of_account", "Bank rule target account"),
]

# Relations deliberately NOT blocking, with the reason. Listed so the
# classification is reviewable and so the completeness test can assert that
# every one of the 40 reverse relations was considered rather than forgotten.
HISTORICAL_RELATIONS = {
    ("journalio", "JournalEntryConnector", "account"): "posted ledger line",
    ("salesio", "Sale", "receivable_charter_account"): "issued document",
    ("salesio", "Sale", "payable_charter_account"): "issued document",
    ("salesio", "SalePaymentReceive", "deposit_to"): "recorded payment",
    ("salesio", "SalesTax", "charter_account"): "recorded tax line",
    ("purchaseio", "Purchase", "charter_account"): "issued document",
    ("purchaseio", "PurchaseItem", "charter_account"): "issued document line",
    ("purchaseio", "Expense", "payment_account"): "recorded expense",
    ("purchaseio", "PayBill", "payment_account"): "recorded payment",
    ("purchaseio", "PurchasePayment", "payment_account"): "recorded payment",
    ("creditnoteio", "CreditNoteItem", "charter_account"): "issued document line",
    ("stockio", "StockAdjustment", "stock_adjustment_account"): "posted adjustment",
    ("transactionio", "BankDeposit", "bank_chart_of_account"): "recorded deposit",
    ("transactionio", "BankDeposit", "cash_back_account"): "recorded deposit",
    ("transactionio", "BankDepositItem", "received_from_account"): "recorded deposit line",
    ("transactionio", "BankReconciliation", "bank_account"): "reconciliation session",
    ("employeeio", "EmployeeExpenseReport", "chart_of_account"): "submitted report",
    ("payrollio", "PayrollSalaryProcess", "funding_account"): "completed pay run",
    ("payrollio", "PayrollSalaryProcess", "payment_account"): "completed pay run",
    ("datamigrationio", "DataMigrationImpactLine", "account"): "import audit line",
    ("transactionio", "TransactionInformation", "chart_of_account"): "bank transaction",
    # The hierarchy is precondition C (COA-152), handled by the cascade rather
    # than reported as a remap target.
    ("accounts", "ChartOfAccount", "parent"): "sub-account, handled by cascade",
}


def blocking_references(account):
    """`[{model, field, label, count, sample}]` for live mappings on this account.

    Empty means s9.4 precondition B is satisfied. Each entry names something a
    person has to go and repoint, so it carries a count and a few examples --
    "3 references" with no clue which is not actionable.
    """
    found = []
    for app_label, model_name, field, label in MAPPING_RELATIONS:
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:  # pragma: no cover - app removed
            continue

        queryset = model.objects.filter(**{field: account})
        queryset = _exclude_removed(queryset, model)

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
    """Drop soft-deleted rows, which are not live mappings.

    Every model here soft-deletes under a `status` field, but not all of them
    spell the retired value the same way, and two have no status at all. Rather
    than hard-code a per-model value, exclude anything whose status looks
    retired -- getting this wrong only ever makes the check stricter, which
    fails safe.
    """
    names = {f.name for f in model._meta.fields}
    if "status" not in names:
        return queryset
    return queryset.exclude(status__in=["REMOVED", "DELETED", "ARCHIVED"])


def active_children(account):
    """Sub-accounts that are not themselves retired (s9.4 precondition C)."""
    from accounts.choices import ChartOfAccountStatusChoices as Status

    # `parents` is the reverse accessor for `parent`, so it yields this
    # account's CHILDREN. The related_name is backwards in the model and
    # renaming it is a migration for another day; assuming the Django default
    # here would simply have raised.
    return account.parents.exclude(status__in=[Status.REMOVED, Status.INACTIVE])
