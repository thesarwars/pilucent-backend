from django.apps import AppConfig


class SubscriptionioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "subscriptionio"

    def ready(self):
        import subscriptionio.signals  # noqa: F401
