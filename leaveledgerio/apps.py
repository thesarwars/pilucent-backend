from django.apps import AppConfig


class LeaveledgerioConfig(AppConfig):
    """BD leave (docs/backend/leave-backend.md). Separate from `leaveio`, the
    original product's leave, which stores a balance and edits it in place --
    the opposite of a ledger whose balance is always a sum."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "leaveledgerio"
    verbose_name = "Leave (BD)"
