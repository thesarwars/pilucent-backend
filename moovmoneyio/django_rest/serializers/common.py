from rest_framework.serializers import ModelSerializer

from ...models import MoovBankAccountSettings


class MoovBankAccountSettingsSerializer(ModelSerializer):
    class Meta:
        model = MoovBankAccountSettings
        fields = ["uid", "account_number", "bank_account_uid"]


class PrivateWeMoovBankAccountDetailsSerializer(ModelSerializer):
    class Meta:
        model = MoovBankAccountSettings
        fields = [
            "uid",
            "account_number",
            "bank_account_uid",
            "account_type",
            "account_holder_name",
            "account_holder_type",
            "bank_name",
        ]
        read_only_fields = fields
