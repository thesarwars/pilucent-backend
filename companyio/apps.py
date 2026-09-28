from django.apps import AppConfig


class CompanyioConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'companyio'

    def ready(self):
        from .django_rest.signals.settings import create_company_setting
