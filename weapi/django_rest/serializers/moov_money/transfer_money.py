from rest_framework import serializers
from moovmoneyio.models import (
    MoovTransfers,
)
from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)
from accounts.django_rest.serializers.common import PriateUserSlimSerializer
from moovmoneyio.django_rest.serializers.common import (
    PrivateWeMoovBankAccountDetailsSerializer,
)


class MoovTransferSerializer(serializers.ModelSerializer):
    class Meta:
        model = MoovTransfers
        fields = [
            "moov_transfer_uid",
            "source_bank_account",
            "destination_bank_account",
            "amount",
            "currency",
            "description",
            "status",
            "created_by",
            "employee",
            "company",
        ]


class MoovTransferListDetailsSerializer(serializers.ModelSerializer):
    created_by = PriateUserSlimSerializer(read_only=True)
    employee = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    source_bank_account = PrivateWeMoovBankAccountDetailsSerializer(read_only=True)
    destination_bank_account = PrivateWeMoovBankAccountDetailsSerializer(read_only=True)

    class Meta:
        model = MoovTransfers
        fields = [
            "uid",
            "moov_transfer_uid",
            "amount",
            "currency",
            "description",
            "source_bank_account",
            "destination_bank_account",
            "status",
            "employee",
            "created_by",
            "created_at",
        ]


