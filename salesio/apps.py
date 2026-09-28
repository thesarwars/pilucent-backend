from django.apps import AppConfig


class SalesioConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'salesio'

    def ready(self):
        from .django_rest.signals import notifications
