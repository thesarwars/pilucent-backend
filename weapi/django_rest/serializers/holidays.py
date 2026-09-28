from django.db import transaction
from rest_framework import serializers
from rest_framework.fields import JSONField
from rest_framework.serializers import (
    SlugRelatedField,
)
from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)

from attendanceio.models import Holiday, HolidayDetails
from attendanceio.django_rest.serializers.common import (
    PrivateHolidaySlimSerializer,
    PrivateHolidayDetailsSlimSerializer,
)


class HolidayCreateSerializer(serializers.ModelSerializer):
    details = JSONField(
        required=False,
        write_only=True,
        help_text="List of holiday details, each containing 'type', 'date', and 'description'.",
    )
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)

    class Meta:
        model = Holiday
        fields = [
            "uid",
            "title",
            "from_date",
            "to_date",
            "status",
            "color",
            "country",
            "weekend",
            "total_holidays",
            "details",
            "created_by",
        ]
        read_only_fields = ["uid"]

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        validated_data["created_by"] = user.get_employee()
        validated_data["company"] = user.get_active_company()
        details_data = validated_data.pop("details", [])
        holiday = super().create(validated_data)
        holiday_details = []
        for detail in details_data:
            holiday_details.append(
                HolidayDetails(
                    holiday=holiday,
                    type=detail.get("type"),
                    date=detail.get("date"),
                    description=detail.get("description"),
                    created_by=user.get_employee(),
                )
            )
        HolidayDetails.objects.bulk_create(holiday_details)
        return holiday


class HolidayUpdateSerializer(serializers.ModelSerializer):
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    details = PrivateHolidayDetailsSlimSerializer(read_only=True, many=True)

    class Meta:
        model = Holiday
        fields = [
            "uid",
            "title",
            "from_date",
            "to_date",
            "status",
            "color",
            "country",
            "weekend",
            "total_holidays",
            "created_by",
            "details",
        ]
        read_only_fields = ["uid"]

    def update(self, instance, validated_data):
        request = self.context["request"]
        user = request.user
        validated_data["created_by"] = user.get_employee()
        return super().update(instance, validated_data)


class HolidayDetailsCreateSerializer(serializers.ModelSerializer):
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    holiday = PrivateHolidaySlimSerializer(read_only=True)
    holiday_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Holiday.objects.get_status_all(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = HolidayDetails
        fields = [
            "uid",
            "type",
            "date",
            "description",
            "holiday",
            "holiday_uid",
            "created_by",
        ]
        read_only_fields = ["uid"]

    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        validated_data["created_by"] = user.get_employee()
        validated_data["holiday"] = validated_data.pop("holiday_uid", None)
        return super().create(validated_data)


class HolidayDetailUpdateSerializer(serializers.ModelSerializer):
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)

    class Meta:
        model = HolidayDetails
        fields = ["uid", "type", "date", "description", "holiday", "created_by"]
        read_only_fields = ["uid"]

    def update(self, instance, validated_data):
        request = self.context["request"]
        user = request.user
        validated_data["created_by"] = user.get_employee()
        return super().update(instance, validated_data)
