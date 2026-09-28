from django.apps import AppConfig


class PurchaseioConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'purchaseio'

    def ready(self):
        from .django_rest.signals import notifications
