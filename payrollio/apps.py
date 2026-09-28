from django.apps import AppConfig


class PayrollioConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'payrollio'

    def ready(self):
        from .django_rest.signals.general_tax_setting import (  # noqa: F401
            payroll_general_tax_setting_post_save,
        )
        from .django_rest.signals.work_location import (  # noqa: F401
            payroll_work_location_post_save,
        )
