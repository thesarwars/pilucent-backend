"""Admin for sales documents.

Loading notes — the change form used to be very slow because every FK rendered
a full ``<select>``. For one sale that meant roughly 8,700 ``<option>`` elements
and a full-table query per field: 627 customers, 368 employees, **3,576 chart-of
-account rows twice over**, plus all 232 products and 24 tax rates *per inline
row*. Every FK is now a ``raw_id_field`` — a text input with a lookup popup — so
the form loads a fixed, small amount regardless of how much data exists.

List pages join what they display and avoid per-row queries. Note also that
``list_filter`` deliberately does not include product or company *names*: Django
renders one sidebar link per distinct value, so those turned the filter bar into
hundreds of links and their own queries.
"""

from auditlog.registry import auditlog

from django.contrib import admin

from .models import (
    Sale,
    SaleItem,
    SalePaymentReceive,
    SalePaymentReceiveItem,
    SalesTax,
    SaleSetting,
)


class SaleItemAdminInline(admin.TabularInline):
    model = SaleItem
    extra = 0  # was 1: a blank row rendered another full product dropdown
    raw_id_fields = ["product", "tax"]
    readonly_fields = ["uid"]

    def get_queryset(self, request):
        # Each row shows its product and tax; fetch them with the rows.
        return super().get_queryset(request).select_related("product", "tax")


class SalePaymentReceiveItemInline(admin.TabularInline):
    model = SalePaymentReceiveItem
    extra = 0
    raw_id_fields = ["sale", "credit_note"]
    readonly_fields = ["uid"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("sale", "credit_note")


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = [
        "invoice_id",
        "kind",
        "status",
        "date",
        "total",
        "customer_name",
    ]
    # Text columns only. The previous `list_display + [...]` swept in `total`
    # and `date`, and searching a decimal/date column with icontains errors.
    search_fields = [
        "invoice_id",
        "tracking_number",
        "reference_number",
        "customer__display_name",
        "customer__first_name",
    ]
    # Low-cardinality choice fields only -- a FK here renders one sidebar link
    # per related row (every company, every product).
    list_filter = ["kind", "status", "tax_kind", "is_invoice", "is_sale_receipt"]
    date_hierarchy = "date"
    ordering = ["-created_at"]
    readonly_fields = ["uid", "invoice_id", "created_at", "updated_at"]
    inlines = [SaleItemAdminInline]

    # The whole point: 8,700 options and ~10 full-table queries become none.
    raw_id_fields = [
        "customer",
        "created_by",
        "company",
        "source_template",
        "warehouse",
        "payment_method",
        "receivable_charter_account",
        "payable_charter_account",
    ]

    list_per_page = 50
    show_full_result_count = False

    def get_queryset(self, request):
        # Joined here rather than via list_select_related, which only applies to
        # the changelist -- an action or export would otherwise go per-row.
        return super().get_queryset(request).select_related("customer")

    @admin.display(description="Customer", ordering="customer__display_name")
    def customer_name(self, obj):
        customer = obj.customer
        if customer is None:
            return "—"
        return (
            customer.display_name
            or f"{customer.first_name} {customer.last_name or ''}".strip()
        )


@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    list_display = ["uid", "sale", "product", "quantity", "total", "created_at"]
    search_fields = ["product__title", "product__sku", "sale__invoice_id"]
    list_filter = ["status"]  # product__title here was one link per product
    raw_id_fields = ["sale", "product", "tax"]
    readonly_fields = ["uid", "created_at", "updated_at"]
    list_per_page = 50
    show_full_result_count = False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("sale", "product")


@admin.register(SalePaymentReceive)
class SalePaymentReceiveAdmin(admin.ModelAdmin):
    list_display = ["uid", "date", "status", "total", "customer"]
    search_fields = ["customer__display_name", "customer__first_name"]
    list_filter = ["status"]
    date_hierarchy = "date"
    raw_id_fields = [
        "customer",
        "created_by",
        "company",
        "payment_method",
        "deposit_to",
    ]
    readonly_fields = ["uid", "created_at", "updated_at"]
    inlines = [SalePaymentReceiveItemInline]
    list_per_page = 50
    show_full_result_count = False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("customer")


@admin.register(SalePaymentReceiveItem)
class SalePaymentReceiveItemAdmin(admin.ModelAdmin):
    list_display = ["uid", "sale_payment_receive", "model_kind", "status"]
    search_fields = ["sale_payment_receive__uid", "sale__invoice_id"]
    list_filter = ["status", "model_kind"]
    raw_id_fields = ["sale_payment_receive", "sale", "credit_note"]
    readonly_fields = ["uid", "created_at", "updated_at"]
    list_per_page = 50
    show_full_result_count = False

    def get_queryset(self, request):
        return (
            super().get_queryset(request).select_related("sale_payment_receive", "sale")
        )


@admin.register(SalesTax)
class SalesTaxAdmin(admin.ModelAdmin):
    list_display = ["uid", "sales_tax_period", "sales_tax_due_date", "total_sales_tax"]
    search_fields = ["sales_tax_period"]
    list_filter = ["status"]
    readonly_fields = ["uid", "created_at", "updated_at"]
    list_per_page = 50
    show_full_result_count = False


@admin.register(SaleSetting)
class SaleSettingAdmin(admin.ModelAdmin):
    list_display = ["uid", "preferred_delivery_method", "is_shipping"]
    search_fields = ["preferred_delivery_method"]
    ordering = ["-created_at"]
    readonly_fields = ["uid", "created_at", "updated_at"]
    list_per_page = 50
    show_full_result_count = False


# Auditlog related
auditlog.register(Sale)
auditlog.register(SaleItem)
auditlog.register(SalePaymentReceive)
auditlog.register(SalePaymentReceiveItem)
auditlog.register(SalesTax)
auditlog.register(SaleSetting)
