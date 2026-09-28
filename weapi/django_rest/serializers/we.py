from versatileimagefield.serializers import VersatileImageFieldSerializer

from rest_framework.serializers import ModelSerializer, BooleanField, SerializerMethodField

from common.django_rest.helpers.decorators import set_auditlog_actor

from companyio.models import Company, CompanySetting


class PrivateWeDetailsSerializer(ModelSerializer):
    legal_address = SerializerMethodField(read_only=True)

    logo = VersatileImageFieldSerializer(
        sizes=[
            ("original", "url"),
            ("at350x350", "crop__350x350"),
        ],
    )
    is_company_subscription = BooleanField(read_only=True, source="is_company_subscribed")
    is_accountant_subscription = BooleanField(
        read_only=True, source="is_accountant_subscribed"
    )

    class Meta:
        model = Company
        fields = [
            "uid",
            "name",
            "legal_name",
            "kind",
            "status",
            "business_id_no",
            "vat_number",
            "time_zone",
            "email",
            "phone",
            "website",
            "company_addresses",
            "customer_facing_address",
            "legal_address",
            "logo",
            "is_company_subscription",
            "is_accountant_subscription",
            "created_at",
            "updated_at",
        ]
        # This MUST live inside Meta. Declared on the class body (where it sat
        # until now) DRF ignores it completely and every field stays writable.
        #
        # `status` is read-only here on purpose: it accepts REMOVED, which is
        # how a company is deactivated, and this endpoint is reachable by any
        # authenticated member. Leaving it writable let a member evict their own
        # tenant with one PATCH, with no way back -- the undo endpoint resolves
        # through get_active_company(), which returns None once the company is
        # REMOVED. Status changes belong to the superadmin console
        # (adminio AdminCompanyRetrieve), which is where the undo lives too.
        read_only_fields = [
            "uid",
            "status",
            "created_at",
            "updated_at",
            "legal_address",
        ]

    def get_legal_address(self, obj):
        return obj.get_legal_address()

    @set_auditlog_actor
    def update(self, instance, validated_data):
        validated_data.pop("legal_address", None)
        return super().update(instance, validated_data)


class PrivateWeSettingSerializer(ModelSerializer):
    class Meta:
        model = CompanySetting
        fields = [
            "uid",
            # Accounting
            "preffered_first_financial_month",
            "preffered_first_tax_month",
            "accounting_method",
            "preffered_tax",
            # Company type
            "tax_form",
            # Chart or accounts
            "is_chart_of_account",
            # Categories
            "is_track_classes",
            "is_track_location",
            # Automations
            "prefill_forms",
            "auto_invoice_unbilled_activity",
            "auto_apply_bill_payments",
            # Automations
            "is_organized_job_related_activity",
            # # Currency
            "home_currency",
            "multi_currency",
            # Other perfomance
            "is_warn_duplicate_cheque_number",
            "is_warn_duplicate_bill_number",
            "is_warn_duplicate_journal_number",
            "sing_me_out",
            "tax_id",
            # Time
            "preffered_first_day",
            "is_service_field",
            "is_allow_time_to_billable",
            "created_at",
            "updated_at",
        ]

    @set_auditlog_actor
    def update(self, instance, validated_data):
        return super().update(instance, validated_data)
