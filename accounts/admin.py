from django.contrib import admin

from auditlog.registry import auditlog

from .models import ChartOfAccount, User, OTP


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    model = User
    list_display = ["uid", "email", "name", "phone", "status"]
    list_filter = ["is_superuser", "is_staff", "status"]
    search_fields = ["phone", "name", "email"]
    readonly_fields = ["uid", "slug"]
    ordering = ("-created_at",)



@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    model = OTP
    list_display = ["user", "otp", "created_at", "is_consumed"]
    list_filter = ["is_consumed"]
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


@admin.register(ChartOfAccount)
class ChartOfAccountAdmin(admin.ModelAdmin):
    model = ChartOfAccount
    list_display = [
        "uid",
        "title",
        "status",
        "opening_balance",
        "created_at",
        "company",
    ]
    list_filter = ["status", "date", "company__name"]
    search_fields = list_filter + ["uid", "title", "opening_balance", "currency"]
    ordering = ("-created_at",)
    autocomplete_fields = ["detail_type", "account_type", "parent"]


# Auditlog related
auditlog.register(User)
auditlog.register(OTP)
auditlog.register(ChartOfAccount)
