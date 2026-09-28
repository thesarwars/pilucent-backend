from rest_framework.serializers import CharField, ModelSerializer

from companyio.models import CompanyShift


class PrivateMeShiftDetailsSerializer(ModelSerializer):
    workable_hour = CharField(source="get_workable_hour")

    class Meta:
        model = CompanyShift
        fields = [
            "uid",
            "in_time",
            "out_time",
            "workable_hour",
            "created_at",
            "updated_at",
        ]
