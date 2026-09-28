from auditlog.registry import auditlog

from django.contrib import admin

from .models import (
    PurchaseItem,
    Purchase,
    Expense,
    ExpenseConnector,
    PurchasePayment,
    PurchasePaymentItem,
    PurchaseSetting,
    PayBill,
    PayBillItem,
    PayBillApplication,
)


class PurchaseAdminInline(admin.TabularInline):
    model = PurchaseItem
    extra = 1


class ExpenseAdminInline(admin.TabularInline):
    model = ExpenseConnector
    extra = 1


class PurchasePaymentInline(admin.TabularInline):
    model = PurchasePaymentItem
    extra = 1


class PayBillItemInline(admin.TabularInline):
    model = PayBillItem
    extra = 1


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ["uid", "purchase_id", "total", "status", "discount", "created_at"]
    search_fields = list_display + ["discount_kind"]
    list_filter = ["discount_kind", "status", "company__uid", "company__name"]
    inlines = [PurchaseAdminInline]


@admin.register(PurchaseItem)
class PurchaseItemAdmin(admin.ModelAdmin):
    list_display = ["uid", "total", "status", "kind", "product__title", "quantity", "created_at"]
    search_fields = list_display + ["product__uid", "product__title"]


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ["uid", "total", "status", "created_at"]
    search_fields = list_display + ["supplier__uid"]
    inlines = [ExpenseAdminInline]


@admin.register(ExpenseConnector)
class ExpenseConnectorAdmin(admin.ModelAdmin):
    list_display = ["uid", "created_at"]
    search_fields = list_display + ["purchase__uid"]


@admin.register(PurchasePayment)
class PurchasePaymentAdmin(admin.ModelAdmin):
    list_display = ["uid", "total", "status", "created_at"]
    search_fields = list_display + ["supplier__uid"]
    list_filter = ["status"]
    inlines = [PurchasePaymentInline]


@admin.register(PurchasePaymentItem)
class PurchasePaymentItemAdmin(admin.ModelAdmin):
    list_display = ["uid", "status", "created_at"]
    search_fields = list_display
    list_filter = ["status"]


@admin.register(PurchaseSetting)
class PurchaseSettingAdmin(admin.ModelAdmin):
    list_display = ["uid", "is_purchase_item", "is_tag"]
    search_fields = list_display
    ordering = ("-created_at",)


@admin.register(PayBill)
class PayBillAdmin(admin.ModelAdmin):
    list_display = ["uid", "tracking_number", "date", "status", "total", "created_at"]
    search_fields = list_display
    inlines = [PayBillItemInline]


@admin.register(PayBillItem)
class PayBillItemAdmin(admin.ModelAdmin):
    list_display = [
        "uid",
        "status",
        "applied_credit",
        "total",
        "created_at",
    ]
    search_fields = list_display


auditlog.register(Purchase)
auditlog.register(PurchaseItem)
auditlog.register(Expense)
auditlog.register(ExpenseConnector)
auditlog.register(PurchasePayment)
auditlog.register(PurchasePaymentItem)
auditlog.register(PurchaseSetting)
auditlog.register(PayBill)
auditlog.register(PayBillItem)
# Which bills a payment settled is a subledger fact, so it is audited like the
# payment itself. BR-26's coverage test caught this the run it was added.
auditlog.register(PayBillApplication)
