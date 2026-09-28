from decimal import Decimal, InvalidOperation

from django.db import transaction as db_transaction

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    update_opening_balance,
)
from journalio.choices import JournalEntryConnectorKindChoices
from common.django_rest.helpers.id_generator import get_unique_id
from journalio.choices import (
    JournalEntryConnectorRequestKindChoices,
    JournalEntryKindChoices,
    JournalEntryStatusChoices,
)
from journalio.django_rest.services.journals import JournalEntryService
from journalio.models import JournalEntry

from transactionio.choices import (
    ParamsFieldChoices,
    TransactionStatusChoices,
    TrxRuleTypeChoices,
)
from transactionio.models import TransactionInformation, TransactionRules


OPERATION_MAP = {
    "contains": lambda left, right: right.lower() in left.lower(),
    "not_contains": lambda left, right: right.lower() not in left.lower(),
    "is_exactly": lambda left, right: left == right,
    "equal": lambda left, right: left == right,
    "not_equal": lambda left, right: left != right,
    "greater_than": lambda left, right: left > right,
    "less_than": lambda left, right: left < right,
}


def get_amount(trx, rule_type):
    if rule_type == TrxRuleTypeChoices.SPENT:
        return trx.spent or Decimal("0")
    return trx.received or Decimal("0")


def get_model_field_and_value(param, rule_type):
    field_choice = (
        param.field.upper()
        if hasattr(param.field, "upper")
        else str(param.field).upper()
    )
    value = param.value

    if field_choice == ParamsFieldChoices.AMOUNT:
        try:
            value = Decimal(str(value))
        except (TypeError, ValueError, InvalidOperation):
            return None, None
        model_field = "spent" if rule_type == TrxRuleTypeChoices.SPENT else "received"
        return model_field, value

    if field_choice in (ParamsFieldChoices.DESCRIPTION, ParamsFieldChoices.BANK_TEXT):
        return "description", str(value or "")

    # Extensible fallback for future rule fields (reference, date, etc.)
    return field_choice.lower(), value


def evaluate_single_condition(left_value, operation, right_value):
    operation_key = (operation or "").strip().lower()
    evaluator = OPERATION_MAP.get(operation_key)
    if evaluator is None:
        return False

    if left_value is None:
        left_value = ""
    if right_value is None:
        right_value = ""

    if operation_key in {"contains", "not_contains"}:
        return evaluator(str(left_value), str(right_value))
    return evaluator(left_value, right_value)


def is_param_match(trx, param, rule_type):
    model_field, value = get_model_field_and_value(param, rule_type)
    if model_field is None:
        return False
    left_value = getattr(trx, model_field, None)
    return evaluate_single_condition(left_value, param.operation, value)


def is_rule_match(trx, params, is_all, rule_type):
    checks = [is_param_match(trx, param, rule_type) for param in params]
    if not checks:
        return False
    return all(checks) if is_all else any(checks)


def get_rule_journal_kind(assign):
    kind_map = {
        "EXPENSE": JournalEntryKindChoices.EXPENSE,
        "CHECK": JournalEntryKindChoices.CHEQUE,
        "DEPOSIT": JournalEntryKindChoices.BANK_DEPOSIT,
    }
    return kind_map.get(
        (assign.trx_type or "").upper(),
        JournalEntryKindChoices.CHART_OF_ACCOUNT,
    )


def build_connector_data_for_rule(trx, rule, assign, amount):
    bank_coa = trx.chart_of_account
    assign_coa = assign.chart_of_account

    # The two legs are opposite sides of one transaction: money out credits the
    # bank and debits wherever it went; money in debits the bank and credits
    # wherever it came from. Resolve each action from the side it has to land
    # on, per that account's kind.
    #
    # Hard-coding the action instead is what this used to do -- "addition" for
    # the category leg in BOTH directions -- and `get_debit_or_credit` maps
    # "addition" to a different side per kind, so it only landed correctly when
    # the categorised account happened to be the expected kind. Five of the ten
    # direction x kind combinations put BOTH legs on the same side and the entry
    # went out by twice the amount: money in to an ASSETS or EXPENSES account,
    # money out to LIABILITIES, INCOMES or EQUITIES. Paying down a loan and
    # taking an owner draw are ordinary, not exotic.
    #
    # `action_for_side` exists for exactly this and says so in its docstring.
    # `16acf904` swept the sales engine's thirteen legs for the same bug and
    # this file was missed.
    if rule.transaction_type == TrxRuleTypeChoices.SPENT:
        bank_side = JournalEntryConnectorKindChoices.CREDIT
        category_side = JournalEntryConnectorKindChoices.DEBIT
    else:
        bank_side = JournalEntryConnectorKindChoices.DEBIT
        category_side = JournalEntryConnectorKindChoices.CREDIT

    bank_action = action_for_side(bank_coa.kind, bank_side)
    category_action = action_for_side(assign_coa.kind, category_side)

    # Derived from the action rather than stated again, so the stored running
    # balance cannot drift from the journal leg the way it could when the two
    # were written out independently.
    bank_balance_op = balance_operation_for_action(bank_action)
    category_balance_op = balance_operation_for_action(category_action)

    update_opening_balance(bank_coa, bank_balance_op, amount, 0)
    update_opening_balance(assign_coa, category_balance_op, amount, 0)

    return [
        (bank_coa, bank_action, amount, bank_coa.opening_balance, None),
        (assign_coa, category_action, amount, assign_coa.opening_balance, None),
    ]


def get_party_name(assign):
    party = assign.payee or assign.customer
    if not party:
        return None
    for attr in ("name", "title", "display_name"):
        value = getattr(party, attr, None)
        if value:
            return value
    return str(party)


def transaction_candidates(company_uid, transaction_uids=None):
    queryset = TransactionInformation.objects.filter(
        company__uid=company_uid,
        transaction_status=TransactionStatusChoices.FOR_REVIEW,
        matched_rule__isnull=True,
        journal_entry__isnull=True,
    ).select_related("chart_of_account", "company", "journal_entry")
    if transaction_uids:
        queryset = queryset.filter(uid__in=transaction_uids)
    return list(queryset)


def is_account_allowed(rule, trx):
    if rule.all_account:
        return True
    return any(
        account.uid == trx.chart_of_account.uid for account in rule.bank_accounts.all()
    )


def apply_excluded(rule, matched_transactions):
    for trx in matched_transactions:
        trx.matched_rule = rule
        trx.transaction_status = TransactionStatusChoices.EXCLUDED
    TransactionInformation.objects.bulk_update(
        matched_transactions,
        fields=["matched_rule", "transaction_status", "updated_at"],
    )
    return len(matched_transactions)


def apply_assignment(rule, matched_transactions):
    assign = getattr(rule, "assign", None)
    if not assign or not assign.chart_of_account_id:
        return 0, 0

    applied_count = 0
    auto_confirmed_count = 0
    for trx in matched_transactions:
        amount = get_amount(trx, rule.transaction_type)
        if amount <= 0 or not trx.chart_of_account_id:
            continue
        if trx.journal_entry_id:
            continue

        trx.matched_rule = rule
        trx.category = (
            assign.chart_of_account.title if assign.chart_of_account else trx.category
        )
        party_name = get_party_name(assign)
        if party_name:
            trx.payee = party_name

        if not rule.auto_add:
            trx.save(update_fields=["matched_rule", "category", "payee", "updated_at"])
            applied_count += 1
            continue

        try:
            with db_transaction.atomic():
                connector_data = build_connector_data_for_rule(
                    trx, rule, assign, amount
                )
                journal_entry = JournalEntry.objects.create(
                    entry_number=get_unique_id(
                        JournalEntry, trx.company.id, "entry_number", "JE"
                    ),
                    amount=amount,
                    status=JournalEntryStatusChoices.PUBLISHED,
                    kind=get_rule_journal_kind(assign),
                    is_transaction=True,
                    is_journal_entry=True,
                    company=trx.company,
                    date=trx.date,
                    description=(trx.description or "")[:500] or None,
                )
                JournalEntryService.create_journal_entry_connector(
                    connector_data=connector_data,
                    total=amount,
                    request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
                    journal_entry=journal_entry,
                    created_by=None,
                )
                trx.journal_entry = journal_entry
                trx.transaction_status = TransactionStatusChoices.CATEGORIZED
                trx.save(
                    update_fields=[
                        "matched_rule",
                        "category",
                        "payee",
                        "journal_entry",
                        "transaction_status",
                        "updated_at",
                    ]
                )
                applied_count += 1
                auto_confirmed_count += 1
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.exception(
                "Rule apply failed for tx %s rule %s: %s",
                trx.uid,
                rule.uid,
                e,
            )
            continue
    return applied_count, auto_confirmed_count


def apply_rules_for_transactions(company_uid, transaction_uids=None, rule_uid=None):
    rules_queryset = (
        TransactionRules.objects.filter(company__uid=company_uid)
        .select_related(
            "assign",
            "assign__chart_of_account",
            "assign__payee",
            "assign__customer",
            "company",
        )
        .prefetch_related("params", "bank_accounts")
        .order_by("created_at", "id")
    )
    if rule_uid:
        rules_queryset = rules_queryset.filter(uid=rule_uid)

    rules = list(rules_queryset)
    if not rules:
        return {"success": True, "applied": 0, "auto_confirmed": 0, "excluded": 0}

    transactions = transaction_candidates(
        company_uid, transaction_uids=transaction_uids
    )
    if not transactions:
        return {"success": True, "applied": 0, "auto_confirmed": 0, "excluded": 0}

    matched_uids = set()
    applied_total = 0
    auto_confirmed_total = 0
    excluded_total = 0

    for rule in rules:
        params = list(rule.params.all())
        if not params:
            continue

        matched_transactions = []
        for trx in transactions:
            if trx.uid in matched_uids:
                continue
            if trx.company.uid != rule.company.uid:
                continue
            if not trx.chart_of_account_id:
                continue
            if not is_account_allowed(rule, trx):
                continue
            if get_amount(trx, rule.transaction_type) <= 0:
                continue
            if not is_rule_match(trx, params, rule.is_all, rule.transaction_type):
                continue
            matched_transactions.append(trx)
            matched_uids.add(trx.uid)

        if not matched_transactions:
            continue

        if rule.is_excluded:
            excluded_total += apply_excluded(rule, matched_transactions)
            continue

        applied_count, auto_confirmed_count = apply_assignment(
            rule, matched_transactions
        )
        applied_total += applied_count
        auto_confirmed_total += auto_confirmed_count

    return {
        "success": True,
        "applied": applied_total,
        "auto_confirmed": auto_confirmed_total,
        "excluded": excluded_total,
    }


def apply_transaction_rule(rule_uid, request=None):
    rule = (
        TransactionRules.objects.filter(uid=rule_uid)
        .select_related("company")
        .only("uid", "company__uid")
        .first()
    )
    if not rule:
        return {"success": False, "message": "Rule not found"}
    return apply_rules_for_transactions(
        company_uid=str(rule.company.uid),
        rule_uid=str(rule.uid),
    )
