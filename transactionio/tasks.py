from celery import shared_task


@shared_task
def apply_transaction_rule_task(rule_uid):
    from transactionio.django_rest.helpers.transaction_rule_apply import (
        apply_transaction_rule,
    )

    return apply_transaction_rule(rule_uid, request=None)


@shared_task
def apply_all_transaction_rules_for_company_task(company_uid):
    from transactionio.django_rest.helpers.transaction_rule_apply import (
        apply_rules_for_transactions,
    )

    return apply_rules_for_transactions(company_uid=company_uid)


@shared_task
def apply_rules_for_new_transactions_task(company_uid, transaction_uids):
    from transactionio.django_rest.helpers.transaction_rule_apply import (
        apply_rules_for_transactions,
    )

    return apply_rules_for_transactions(
        company_uid=company_uid,
        transaction_uids=transaction_uids,
    )
