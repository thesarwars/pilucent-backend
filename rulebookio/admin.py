from django.contrib import admin

from .models import RuleSet


@admin.register(RuleSet)
class RuleSetAdmin(admin.ModelAdmin):
    list_display = ("jurisdiction", "family", "version", "effective_from", "effective_to", "status")
    list_filter = ("jurisdiction", "family", "status")
    readonly_fields = ("uid", "created_at", "updated_at")
