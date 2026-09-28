from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from auditlog.registry import auditlog

from .models import Currency, CurrencyConnector


@admin.register(Currency)
class CurrencyAdmin(SimpleHistoryAdmin):
    list_display = ["uid", "kind", "status", "exchange_rate", "created_at"]
    search_fields = list_display
    list_filter = ["status", "kind"]


@admin.register(CurrencyConnector)
class CurrencyConnectorAdmin(SimpleHistoryAdmin):
    list_display = ["uid", "model_kind", "created_at"]
    search_fields = list_display


auditlog.register(Currency)
