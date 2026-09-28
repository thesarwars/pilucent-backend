from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from transactionio.models import TransactionInformation
from transactionio.choices import TransactionStatusChoices
from transactionio.tasks import apply_rules_for_new_transactions_task





@receiver(post_save, sender=TransactionInformation)
def transaction_information_post_save(sender, instance, created, **kwargs):
    if instance.transaction_status != TransactionStatusChoices.FOR_REVIEW:
        return
    if not instance.chart_of_account_id:
        return
    if not instance.company_id:
        return
    company_uid = str(instance.company.uid)
    transaction_uid = str(instance.uid)
    transaction.on_commit(
        lambda: apply_rules_for_new_transactions_task.delay(
            company_uid, [transaction_uid]
        )
    )
    