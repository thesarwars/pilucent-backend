from auditlog.registry import auditlog
from django.contrib import admin
from .models import (
    TransactionMethod,
    TransactionInformation,
    TransactionRules,
    TransactionRuleParams,
    TransactionRuleAssign,
    BankDeposit,
    BankDepositItem,
    BankReconciliation,
)


@admin.register(TransactionMethod)
class TransactionMethodAdmin(admin.ModelAdmin):
    list_display = ["uid", "status", "created_at"]
    search_fields = ["status", "company__name", "company__uid"]
    list_filter = ["status"]


@admin.register(TransactionInformation)
class TransactionInformationAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "date",
        "received",
        "spent",
        "category",
        "is_spam",
        "transaction_status",
        "company",
    ]
    search_fields = ["date", "category", "is_spam", "company__name"]
    list_filter = ["is_spam", "category"]
    readonly_fields = ["uid", "created_at", "updated_at"]
    autocomplete_fields = ["chart_of_account"]


class TrxRulesParamsInline(admin.TabularInline):
    model = TransactionRuleParams
    extra = 1


class TrxRuleAssignInline(admin.TabularInline):
    model = TransactionRuleAssign
    extra = 0


@admin.register(TransactionRules)
class TransactionRulesAdmin(admin.ModelAdmin):
    inlines = [TrxRulesParamsInline, TrxRuleAssignInline]
    list_display = ["uid", "title", "transaction_type"]
    readonly_fields = ["uid", "created_at", "updated_at"]


@admin.register(BankDeposit)
class BankDepositAdmin(admin.ModelAdmin):
    list_display = ["uid", "date", "status", "company"]
    search_fields = ["date", "company__name"]
    list_filter = ["status"]
    readonly_fields = ["uid", "created_at", "updated_at"]
    
@admin.register(BankDepositItem)
class BankDepositItemAdmin(admin.ModelAdmin):
    list_display = ["uid", "amount", "payment_method", "type"]
    # `payment_method` is a ForeignKey, and a search term is applied with
    # `icontains` -- against a relation that is a FieldError, so searching this
    # changelist was a 500. Traverse to a text column on the far side.
    search_fields = ["amount", "payment_method__title"]
    list_filter = ["type", "payment_method"]
    readonly_fields = ["uid", "created_at", "updated_at"]

@admin.register(BankReconciliation)
class BankReconciliationAdmin(admin.ModelAdmin):
    list_display = ["uid", "bank_account__title", "company__name"]
    # `BankReconciliation` has no `date` field -- it has `statement_ending_date`,
    # `reconciled_on` and `undone_on`. Searching this changelist was a
    # FieldError, so a 500, on every query.
    search_fields = [
        "statement_ending_date",
        "company__name",
        "bank_account__title",
    ]
    readonly_fields = ["uid", "created_at", "updated_at"]
    autocomplete_fields = ["bank_account"]


# BR-26. Field-level history on the banking models.
#
# Every comparable app registers its whole surface -- journalio 2/2, salesio
# 6/6, purchaseio 9/9, accounts 3/3, customerio 1/1 -- and `transactionio` was
# 0/8. Not a decision anyone took: the app was simply missed, and it is the one
# holding reconciliation sessions, statement lines and the rules that post from
# them.
#
# Spec s14 wants old value, new value, actor and time on every money field. This
# is that, for changes that go through the ORM.
#
# **What it does not cover, stated plainly:** `bulk_create` and `bulk_update`
# do not fire the signals auditlog listens to. So a CSV import
# (`csv_transactions.py`, bulk_create), the undo's line release
# (`.update(reconciliation=None)`) and the rule engine's bulk categorisation
# (`transaction_rule_apply.py`) are invisible here. The session lifecycle IS
# covered, because closing and undoing both go through `instance.save()`, and
# that is the part spec s14 names. Auditing the bulk paths means changing how
# they write, which is a larger piece of work than a registration.
auditlog.register(TransactionMethod)
auditlog.register(TransactionInformation)
auditlog.register(TransactionRules)
auditlog.register(TransactionRuleParams)
auditlog.register(TransactionRuleAssign)
auditlog.register(BankDeposit)
auditlog.register(BankDepositItem)
auditlog.register(BankReconciliation)
