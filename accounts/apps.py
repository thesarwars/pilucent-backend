from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        from .django_rest.signals import chart_of_accounts
        from .django_rest.signals.group_seeds import handle_post_migrate
        from .django_rest.signals.group_permission_sync import (
            connect as connect_group_permission_sync,
        )

        post_migrate.connect(handle_post_migrate)
        connect_group_permission_sync()
