from django.apps import AppConfig


class TransactionioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "transactionio"

    def ready(self):
        import transactionio.signal.transaction_rule_apply  # noqa: F401