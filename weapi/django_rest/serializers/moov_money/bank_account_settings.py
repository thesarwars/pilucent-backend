from rest_framework import serializers

from moovmoneyio.models import MoovBankAccountSettings


class MoovBankAccountSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = MoovBankAccountSettings
        fields = [
            "slug",
            "moov_account_settings",
            "bank_account_uid",
            "account_type",
            "account_number",
            "routing_number",
            "account_holder_name",
            "account_holder_type",
            "bank_name",
            "status",
            "created_by",
            "bank_account_kind",
        ]
        read_only_fields = ["slug", "bank_account_uid", "created_by", "moov_account_settings"]
