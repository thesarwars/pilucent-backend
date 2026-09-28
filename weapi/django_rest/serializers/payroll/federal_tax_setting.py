from rest_framework import serializers
from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)
from rest_framework.serializers import (
    SlugRelatedField,
)
from rest_framework.fields import JSONField
from payrollio.models import (
    PayrollFederalTaxInfoSetting,
    PayrollFederalTaxInfoSettingItems,
)

from payrollio.django_rest.serializer.common import (
    PrivateWePayrollFederalTaxInfoSettingItemsSlimSerializer,
)
from payrollio.django_rest.helpers.federal_tax_setting_items import (
    normalize_federal_tax_effective_date,
    upsert_federal_tax_setting_item,
    validate_payment_frequency_value,
    validate_tax_form_payment_frequency,
    validate_tax_form_value,
)
from payrollio.django_rest.helpers.tax_ein_sync import sync_company_federal_ein


class PrivateWePayrollFederalTaxInfoSettingListCreateSerializer(
    serializers.ModelSerializer
):
    federal_items = JSONField(
        required=False,
        write_only=True,
        help_text="List of federal tax items, each containing 'tax_form', 'payment_frequency', and 'effective_date'.",
    )
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    federal_item = PrivateWePayrollFederalTaxInfoSettingItemsSlimSerializer(
        many=True, read_only=True, source="items"
    )

    class Meta:
        model = PayrollFederalTaxInfoSetting
        fields = [
            "uid",
            "ein_number",
            "created_by",
            "federal_items",
            "federal_item",
        ]
        read_only_fields = ["uid", "created_by"]

    def validate_federal_items(self, value):
        if not value:
            return value
        for index, item in enumerate(value):
            try:
                validate_tax_form_value(item.get("tax_form"))
            except serializers.ValidationError as exc:
                detail = exc.detail
                if isinstance(detail, dict):
                    raise serializers.ValidationError(
                        {f"federal_items[{index}].tax_form": detail.get("tax_form", detail)}
                    )
                raise
        return value

    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        federal_items_data = validated_data.pop("federal_items", [])
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = user.get_active_company()
        instance = super().create(validated_data)
        for item_data in federal_items_data:
            upsert_federal_tax_setting_item(
                instance,
                tax_form=item_data.get("tax_form"),
                payment_frequency=item_data.get("payment_frequency"),
                effective_date=item_data.get("effective_date"),
            )
        if "ein_number" in validated_data:
            sync_company_federal_ein(validated_data["company"], instance.ein_number)
        return instance


class PrivateWePayrollFederalTaxInfoSettingDetailUpdateSerializer(
    serializers.ModelSerializer
):
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)

    class Meta:
        model = PayrollFederalTaxInfoSetting
        fields = [
            "uid",
            "ein_number",
            "created_by",
        ]
        read_only_fields = ["uid", "created_by"]

    def update(self, instance, validated_data):
        request = self.context["request"]
        user = request.user
        validated_data["created_by"] = user.get_employee()
        company = user.get_active_company()
        validated_data["company"] = company
        instance = super().update(instance, validated_data)
        if "ein_number" in validated_data:
            sync_company_federal_ein(company, instance.ein_number)
        return instance


class PrivateWePayrollFederalTaxInfoSettingItemsListCreateSerializer(serializers.ModelSerializer):
    payroll_federal_tax_info_uid = SlugRelatedField(
        slug_field="uid",
        queryset=PayrollFederalTaxInfoSetting.objects.all(),
        write_only=True,
        required=False,
    )
    class Meta:
        model = PayrollFederalTaxInfoSettingItems
        fields = [
            "uid",
            "payroll_federal_tax_info_uid",
            "tax_form",
            "payment_frequency",
            "effective_date",
        ]
        read_only_fields = ["uid"]
        extra_kwargs = {
            "tax_form": {"required": True},
            "payment_frequency": {"required": True},
            "effective_date": {"required": True},
        }

    def validate_tax_form(self, value):
        return validate_tax_form_value(value)

    def validate_payment_frequency(self, value):
        return validate_payment_frequency_value(value)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        tax_form = attrs.get("tax_form")
        payment_frequency = attrs.get("payment_frequency")
        effective_date = attrs.get("effective_date")
        if tax_form and payment_frequency:
            attrs["payment_frequency"] = validate_tax_form_payment_frequency(
                tax_form, payment_frequency
            )
        if tax_form and payment_frequency and effective_date:
            attrs["effective_date"] = normalize_federal_tax_effective_date(
                tax_form,
                attrs["payment_frequency"],
                effective_date,
            )
        return attrs

    def create(self, validated_data):
        payroll_federal_tax_info = validated_data.pop("payroll_federal_tax_info_uid", None)
        if not payroll_federal_tax_info:
            payroll_federal_tax_info = self.context.get("payroll_federal_tax_info")
        if not payroll_federal_tax_info:
            raise serializers.ValidationError(
                "Payroll Federal Tax Info UID is required."
            )
        item, action = upsert_federal_tax_setting_item(
            payroll_federal_tax_info,
            tax_form=validated_data.get("tax_form"),
            payment_frequency=validated_data.get("payment_frequency"),
            effective_date=validated_data.get("effective_date"),
        )
        self.context["upsert_action"] = action
        return item
    

class PrivateWePayrollFederalTaxInfoSettingItemsDetailUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollFederalTaxInfoSettingItems
        fields = [
            "uid",
            "tax_form",
            "payment_frequency",
            "effective_date",
        ]
        read_only_fields = ["uid"]
        extra_kwargs = {
            "tax_form": {"required": True},
            "payment_frequency": {"required": True},
            "effective_date": {"required": True},
        }

    def validate_tax_form(self, value):
        return validate_tax_form_value(value)

    def validate_payment_frequency(self, value):
        return validate_payment_frequency_value(value)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = getattr(self, "instance", None)
        tax_form = attrs.get("tax_form", getattr(instance, "tax_form", None))
        payment_frequency = attrs.get(
            "payment_frequency",
            getattr(instance, "payment_frequency", None),
        )
        effective_date = attrs.get(
            "effective_date",
            getattr(instance, "effective_date", None),
        )
        if tax_form and payment_frequency:
            attrs["payment_frequency"] = validate_tax_form_payment_frequency(
                tax_form, payment_frequency
            )
        if tax_form and payment_frequency and effective_date:
            attrs["effective_date"] = normalize_federal_tax_effective_date(
                tax_form,
                attrs["payment_frequency"],
                effective_date,
            )
        return attrs

    def update(self, instance, validated_data):
        tax_form = validate_tax_form_value(
            validated_data.get("tax_form", instance.tax_form)
        )
        if tax_form != instance.tax_form:
            raise serializers.ValidationError(
                {
                    "tax_form": (
                        "Cannot change the tax form on an existing schedule. "
                        "Delete this row and POST a new schedule for the other form."
                    )
                }
            )

        payment_frequency = validated_data.get(
            "payment_frequency", instance.payment_frequency
        )
        effective_date = validated_data.get("effective_date", instance.effective_date)

        payment_frequency = validate_tax_form_payment_frequency(
            tax_form, payment_frequency
        )
        normalized_date = normalize_federal_tax_effective_date(
            tax_form, payment_frequency, effective_date
        )
        conflict = (
            instance.payroll_federal_tax_info.items.filter(
                tax_form=tax_form,
                effective_date=normalized_date,
            )
            .exclude(pk=instance.pk)
            .exists()
        )
        if conflict:
            raise serializers.ValidationError(
                {
                    "effective_date": (
                        "Another schedule already exists for this tax form on "
                        f"{normalized_date.isoformat()}."
                    )
                }
            )

        instance.payment_frequency = payment_frequency
        instance.effective_date = normalized_date
        instance.save(
            update_fields=["payment_frequency", "effective_date", "updated_at"]
        )
        return instance