from django.apps import AppConfig


class IdcardioConfig(AppConfig):
    """Employee ID cards (docs/backend/id-cards-done.md): templates in millimetres,
    cards as documents with a lifecycle, print jobs with a stored preflight,
    and a public verification endpoint that leaks nothing."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "idcardio"
    verbose_name = "ID cards (BD)"
