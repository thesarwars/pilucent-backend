from payrollio.models import PaySchedule

from rest_framework import serializers

from common.django_rest.helpers.decorators import set_auditlog_actor


class PayScheduleListCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaySchedule
        fields = [
            "uid",
            "title",
            "pay_frequency",
            "status",
            "is_default",
            "first_payday",
            "first_end_day",
            "first_month",
            "first_day",
            "second_payday",
            "second_end_day",
            "second_month",
            "second_day",
            "next_pay_date",
            "end_of_next_pay_period",
        ]

    @set_auditlog_actor
    def create(self, validated_data):
        company = self.context["request"].user.get_active_company()
        is_default = validated_data.get("is_default", False)
        if is_default:
            PaySchedule.objects.filter(company=company, is_default=is_default).update(
                is_default=False
            )
        return PaySchedule.objects.create(company=company, **validated_data)


class PayScheduleListUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaySchedule
        fields = PayScheduleListCreateSerializer.Meta.fields

    @set_auditlog_actor
    def update(self, instance, validated_data):
        company = self.context["request"].user.get_active_company()
        is_default = validated_data.get("is_default", False)
        if is_default:
            PaySchedule.objects.filter(company=company, is_default=True).exclude(
                id=instance.id
            ).update(is_default=False)
        return super().update(instance, validated_data)


class PayScheduleWithEmployeeCountSerializer(serializers.ModelSerializer):
    employee_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = PaySchedule
        fields = [
            "uid",
            "title",
            "employee_count",
            "pay_frequency",
            "next_pay_date",
        ]
        read_only_fields = fields
