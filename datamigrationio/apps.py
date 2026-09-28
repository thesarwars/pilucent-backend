from django.apps import AppConfig


class DatamigrationioConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'datamigrationio'

    def ready(self):
        import datamigrationio.django_rest.handlers  # noqa — registers all migration handlers
