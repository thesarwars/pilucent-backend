from datetime import date, datetime

from rest_framework.serializers import ModelSerializer, ValidationError, FloatField
from rest_framework.generics import get_object_or_404

from accounts.django_rest.serializers.common import PriateUserSlimSerializer

from attendanceio.choices import DailyTimeTrackingStatusChoices
from attendanceio.models import Attendance, DailyTimeTracking, DailyTimeTrackingSession

from companyio.django_rest.serializers.common import (
    PrivateCompanyShiftSlimSerializer,
)
from companyio.models import CompanyUser


class PrivateMeDailyTimeTrackingListSerializer(ModelSerializer):
    # Shift
    shift = PrivateCompanyShiftSlimSerializer(read_only=True)
    worked_hour_count = FloatField(source="get_worked_hour_count", read_only=True)

    class Meta:
        model = DailyTimeTracking
        fields = [
            "uid",
            "date",
            "shift",
            "status",
            "worked_hour_count",
            "check_in",
            "check_out",
            "is_tracked",
            "remark",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "date",
            "status",
            "check_in",
            "check_out",
            "is_tracked",
            "created_at",
            "updated_at",
        ]

    def validate(self, validated_data):
        _date = date.today()
        user = self.context["request"].user

        company_user = CompanyUser.objects.filter(user=user)
        if not company_user:
            raise ValidationError("You dont have any permission")

        # `get_employee()` returns None when the signed-in user has no employee
        # record for the active company -- and it can, because employees are
        # per-company and a user may belong to a company without one. Reading
        # `.shift` off it was the first statement in this method, so that case
        # was a 500 on `/me/daily-time-trackings` rather than a message the
        # clock-in screen could show.
        #
        # The two checks below were already here and already correct; they were
        # simply unreachable, because the dereference happened above them. Order
        # matters as much as the guard: confirm the user is in the company, then
        # that they are an employee of it, then that the employee has a shift.
        employee = user.get_employee()
        if employee is None:
            raise ValidationError(
                "You are not set up as an employee of this company, so "
                "attendance cannot be recorded. Ask an administrator to add "
                "your employee record."
            )

        shift = employee.shift
        if not shift:
            raise ValidationError("You dont have any shift")
        if DailyTimeTracking.objects.filter(
            date=str(_date), employee=employee
        ).exists():
            raise ValidationError({"message": "Attendance already exists.."})
        validated_data["date"] = _date
        validated_data["created_by"] = user
        validated_data["employee"] = employee
        validated_data["company"] = user.get_active_company()
        validated_data["shift"] = shift
        return super().validate(validated_data)

    def create(self, validated_data):
        validated_data["is_tracked"] = True
        return DailyTimeTracking.objects.create(
            status=DailyTimeTrackingStatusChoices.PRESENT,
            check_in=datetime.now().time(),
            **validated_data,
        )


class PrivateMeDailyTimeTrackingDetailsSerializer(ModelSerializer):
    # Shift
    shift = PrivateCompanyShiftSlimSerializer(read_only=True)
    worked_hour_count = FloatField(source="get_worked_hour_count", read_only=True)

    class Meta:
        model = DailyTimeTracking
        fields = [
            "uid",
            "date",
            "shift",
            "status",
            "check_in",
            "check_out",
            "worked_hour_count",
            "remark",
            "is_tracked",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "uid",
            "date",
            "status",
            "check_in",
            "is_tracked",
            "created_at",
            "updated_at",
        ]

    def update(self, instance, validated_data):
        user = self.context["request"].user
        validated_data["is_tracked"] = True
        if attendance := Attendance.objects.filter(
            date=instance.date, employee=instance.employee
        ).first():
            attendance.check_out = validated_data["check_out"]
            attendance.save()
        return super().update(instance, validated_data)


class PrivateMeDailyTimeTrackingSessionListSerializer(ModelSerializer):
    user = PriateUserSlimSerializer(read_only=True)

    class Meta:
        model = DailyTimeTrackingSession
        fields = [
            "uid",
            "check_in",
            "check_out",
            "worked_hour",
            "kind",
            "remark",
            "user",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["user"]

    def create(self, validated_data):
        user = self.context["request"].user
        validated_data["created_by"] = user
        validated_data["employee"] = user.get_employee()
        validated_data["daily_time_tracking"] = get_object_or_404(
            DailyTimeTracking.objects.filter(
                uid=self.context["view"].kwargs.get("uid"),
                employee=validated_data["employee"],
            )
        )
        return super().create(validated_data)


class PrivateMeDailyTimeTrackingSessionDetailsSerializer(ModelSerializer):
    class Meta:
        model = DailyTimeTrackingSession
        fields = [
            "uid",
            "check_in",
            "check_out",
            "worked_hour",
            "kind",
            "remark",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "check_in",
            "created_at",
            "updated_at",
        ]
