from datetime import timedelta
from datetime import date

from versatileimagefield.serializers import VersatileImageFieldSerializer

from django.db import transaction
from django.utils import timezone

from rest_framework.serializers import (
    CharField,
    DateField,
    DictField,
    FloatField,
    ListField,
    ListSerializer,
    ModelSerializer,
    Serializer,
    SlugRelatedField,
    ValidationError,
    TimeField,
)

from accounts.django_rest.serializers.common import PriateUserSlimSerializer

from attendanceio.choices import (
    AttendanceProcessStatusChoices,
    AttendanceStatusChoices,
    PunchDataDailyTimeStatusChoices,
)
from attendanceio.django_rest.helpers.date_times import get_worked_hours
from attendanceio.models import (
    DailyTimeTracking,
    DailyTimeTrackingSession,
    Attendance,
    AttendanceProcess,
    AttendanceProcessItem,
    PunchDataDailyTime,
)

from companyio.choices import CompanyShiftStatusChoices
from companyio.django_rest.serializers.common import (
    PrivateCompanyShiftSlimSerializer,
    PrivateCompanyDesignationSlimSerializer,
)
from companyio.models import CompanyShift, CompanyUser

from common.django_rest.helpers.decorators import set_auditlog_actor
from common.django_rest.helpers.date_range_filters import get_dates_of_ranges

from employeeio.choices import EmployeeStatusChoices
from employeeio.django_rest.serializers.common import (
    PrivateCompanyEmployeeSlimSerializer,
)
from employeeio.models import Employee

from leaveio.choices import EmployeeLeaveRequestStatusChoices

from ..helpers.attendancess import get_attendance_status


class PrivateAttendanceEmployeeSerializer(ModelSerializer):
    image = VersatileImageFieldSerializer(
        sizes=[
            ("original", "url"),
            ("at350x350", "crop__350x350"),
        ],
        source="get_image",
    )
    designation = PrivateCompanyDesignationSlimSerializer(read_only=True)
    first_name = CharField(source="user.first_name", read_only=True)
    middle_name = CharField(source="user.middle_name", read_only=True)
    last_name = CharField(source="user.last_name", read_only=True)

    class Meta:
        model = Employee
        fields = [
            "uid",
            "first_name",
            "middle_name",
            "last_name",
            "employee_id",
            "image",
            "designation",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PrivateWeAttendanceListSerializer(ModelSerializer):
    employee_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Employee.objects.filter(),
        write_only=True,
        required=False,
    )
    employee = PrivateAttendanceEmployeeSerializer(read_only=True)
    check_in = TimeField(required=True)
    shift = PrivateCompanyShiftSlimSerializer(read_only=True)
    late_hour_count = FloatField(source="get_late_hour_count", read_only=True)
    ot_hour_count = FloatField(source="get_ot_hour_count", read_only=True)

    class Meta:
        model = Attendance
        fields = [
            "uid",
            "date",
            "employee",
            "employee_uid",
            "check_in",
            "check_out",
            "status",
            "shift",
            "worked_hour_count",
            "late_hour_count",
            "ot_hour_count",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        user = self.context["request"].user
        employee = validated_data.pop("employee_uid") or user.get_employee()
        validated_data["employee"] = employee
        validated_data["company"] = user.get_active_company()
        validated_data["shift"] = employee.shift
        return super().create(validated_data)


class PrivateWeAttendanceDetailsSerializer(ModelSerializer):
    employee = PrivateAttendanceEmployeeSerializer(read_only=True)

    class Meta:
        model = Attendance
        fields = [
            "uid",
            "date",
            "employee",
            "check_in",
            "check_out",
            "status",
            "worked_hour_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["uid", "employee", "created_at", "updated_at"]


class PrivateWeDailyTimeTrackingListSerializer(ModelSerializer):
    # Shift
    shift = PrivateCompanyShiftSlimSerializer(read_only=True)
    shift_uid = SlugRelatedField(
        slug_field="uid",
        queryset=CompanyShift.objects.filter(status=CompanyShiftStatusChoices.ACTIVE),
        write_only=True,
    )

    # Employee
    employee = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    employee_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Employee.objects.filter(status=EmployeeStatusChoices.ACTIVE),
        write_only=True,
    )

    # Designation
    designation = PrivateCompanyDesignationSlimSerializer(
        source="employee.designation", read_only=True
    )

    class Meta:
        model = DailyTimeTracking
        fields = [
            "uid",
            "date",
            "employee",
            "employee_uid",
            "shift",
            "shift_uid",
            "status",
            "worked_hour",
            "check_in",
            "check_out",
            "remark",
            "designation",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "employee",
            "shift",
            "worked_hour",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        date = attrs["date"]
        employee = attrs.pop("employee_uid", None)
        shift = attrs.pop("shift_uid", None)
        if DailyTimeTracking.objects.filter(
            date=date, employee=employee, shift=shift
        ).exists():
            raise ValidationError({"message": "Attendance already exists."})

        attrs["employee"] = employee
        attrs["shift"] = shift
        return super().validate(attrs)

    def create(self, validated_data):
        check_in = validated_data["check_in"]
        check_out = validated_data["check_out"]
        user = self.context["request"].user
        validated_data["created_by"] = user
        validated_data["company"] = user.get_active_company()
        if check_in and check_out:
            validated_data["worked_hour"] = get_worked_hours(
                validated_data["date"], check_in, check_out, 0
            )
        return super().create(validated_data)


class PrivateWeDailyTimeTrackingDetailsSerializer(ModelSerializer):
    # Shift
    shift = PrivateCompanyShiftSlimSerializer(read_only=True)
    shift_uid = SlugRelatedField(
        slug_field="uid",
        queryset=CompanyShift.objects.filter(status=CompanyShiftStatusChoices.ACTIVE),
        write_only=True,
    )

    # Employee
    employee = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    employee_uid = SlugRelatedField(
        slug_field="uid",
        queryset=Employee.objects.filter(status=EmployeeStatusChoices.ACTIVE),
        write_only=True,
    )

    # Designation
    designation = PrivateCompanyDesignationSlimSerializer(
        source="employee.designation", read_only=True
    )

    class Meta:
        model = DailyTimeTracking
        fields = [
            "uid",
            "date",
            "employee",
            "employee_uid",
            "shift",
            "shift_uid",
            "designation",
            "status",
            "worked_hour",
            "check_in",
            "check_out",
            "remark",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uid",
            "employee",
            "shift",
            "designation",
            "created_at",
            "updated_at",
        ]

    def update(self, instance, validated_data):
        date = validated_data.get("date", None)
        shift = validated_data.pop("shift_uid", None)
        employee = validated_data.pop("employee_uid", None)

        if (
            date
            and DailyTimeTracking.objects.filter(
                date=date, shift=instance.shift, employee=instance.employee
            ).exists()
        ):
            raise ValidationError({"message": "Already exist with same date!"})

        if shift:
            validated_data["shift"] = shift
        if employee:
            validated_data["employee"] = employee
        return super().update(instance, validated_data)


class DailyTimeTrackingSessionListSerializer(ModelSerializer):
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
        read_only_fields = fields

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        return super().create(validated_data)


class DailyTimeTrackingSessionDetailsSerializer(ModelSerializer):
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
            "check_out",
            "worked_hour",
            "kind",
            "created_at",
            "updated_at",
        ]


class ParivateWeAttendanceProcessListSerializer(ModelSerializer):
    created_by = PrivateCompanyEmployeeSlimSerializer(read_only=True)
    last_process_date = DateField(source="get_last_process_date", read_only=True)

    class Meta:
        model = AttendanceProcess
        fields = [
            "uid",
            "start_date",
            "end_date",
            "start_time",
            "end_time",
            "last_process_date",
            "status",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "start_time", "end_time"]

    def validate(self, validated_data):
        start_date = validated_data.get("start_date")
        end_date = validated_data.get("end_date")

        today = date.today()

        request = self.context["request"]
        user = request.user
        company = user.get_active_company()

        if start_date and end_date and start_date > end_date:
            raise ValidationError(
                {"message": "End date cannot be earlier than start date."}
            )

        if end_date and end_date > today:
            raise ValidationError({"message": f"End date cannot be later than today."})

        last_process = (
            AttendanceProcess.objects.filter(company=company)
            .exclude(status=AttendanceProcessStatusChoices.DRAFT)
            .exclude(end_date=today)
            .order_by("-end_date")
            .first()
        )
        last_process_date = last_process.end_date if last_process else None

        if last_process_date and start_date != today:
            expected_next_date = last_process.end_date + timedelta(days=1)

            if start_date != expected_next_date:
                raise ValidationError(
                    {
                        "message": (
                            f"Sequential processing is required. The next allowed start date is {expected_next_date.strftime('%d-%m-%Y')}."
                        )
                    }
                )
        return super().validate(validated_data)

    @transaction.atomic
    @set_auditlog_actor
    def create(self, validated_data):
        validated_data["start_time"] = timezone.now()

        start_date = validated_data.get("start_date")
        end_date = validated_data.get("end_date")

        dates = get_dates_of_ranges(start_date, end_date)

        request = self.context["request"]
        user = request.user
        employee = user.get_employee()
        company = user.get_active_company()
        employees = company.get_employees()

        validated_data["created_by"] = employee
        validated_data["company"] = company
        validated_data["status"] = AttendanceProcessStatusChoices.COMPLETED

        # Creating attendance process
        attendance_process = AttendanceProcess.objects.create(**validated_data)

        for employee in employees:
            for date in dates:
                daily_time_tracking = DailyTimeTracking.objects.filter(
                    date=date, employee=employee
                ).first()
                punch_data = PunchDataDailyTime.objects.filter(
                    date=date, employee=employee
                ).first()
                employee_shift = employee.shift

                # Creating attendances
                defaults = {
                    "date": date,
                    "status": AttendanceStatusChoices.ABSENT,
                    "company": company,
                    "shift": employee_shift,
                }
                holiday = None
                employee_leave = None
                if daily_time_tracking:
                    if worked_hour_count := daily_time_tracking.get_worked_hour_count():
                        defaults["worked_hour_count"] = worked_hour_count

                    if check_in := daily_time_tracking.check_in:
                        defaults["check_in"] = check_in

                    if check_out := daily_time_tracking.check_out:
                        defaults["check_out"] = check_out

                    defaults["status"] = get_attendance_status(
                        check_in, check_out, employee_shift
                    )
                elif punch_data:
                    if worked_hour_count := punch_data.get_worked_hour_count():
                        defaults["worked_hour_count"] = worked_hour_count

                    if check_in := punch_data.check_in:
                        defaults["check_in"] = check_in

                    if check_out := punch_data.check_out:
                        defaults["check_out"] = check_out

                    defaults["status"] = get_attendance_status(
                        check_in, check_out, employee_shift
                    )
                elif employee_holiday := employee.holiday:
                    if holiday_details := employee_holiday.details.filter(date=date):
                        defaults["status"] = holiday_details.first().type
                        holiday = employee_holiday
                elif employee_leave := employee.leaverequest_set.filter(
                    status=EmployeeLeaveRequestStatusChoices.APPROVED,
                    from_date__lte=date,
                    to_date__gte=date,
                ).first():
                    defaults["status"] = AttendanceStatusChoices.LEAVE

                # Creating attendances
                attendance, _ = Attendance.objects.update_or_create(
                    date=date, employee=employee, company=company, defaults=defaults
                )

                # Update or creating new attendance process item
                AttendanceProcessItem.objects.update_or_create(
                    attendance=attendance,
                    defaults={
                        "attendance_process": attendance_process,
                        "holiday": holiday,
                        "leave": employee_leave,
                    },
                )

        attendance_process.end_time = timezone.now()
        attendance_process.save()
        return validated_data


class PrivateWePunchDataDailyTimeListCreateSerializer(Serializer):
    data = ListField(child=DictField(), write_only=True)

    @transaction.atomic
    def create(self, validated_data):
        data_list = validated_data["data"]
        user = self.context["request"].user
        company = user.get_active_company()

        # First pass: validate all data and collect errors
        validation_errors = {}
        processed_items = []

        for index, item in enumerate(data_list):
            errors = []

            # Check user permissions
            company_user = CompanyUser.objects.filter(user=user)
            if not company_user:
                validation_errors[f"item_{index}"] = ["You don't have any permission"]
                continue

            # Get employee
            employee_id = item.get("employee_id")
            try:
                if employee_id:
                    employee = Employee.objects.get(employee_id=employee_id)
                else:
                    employee = user.get_employee()
            except (Employee.DoesNotExist, ValueError):
                validation_errors[f"item_{index}"] = [
                    f"Invalid employee ID: {employee_id}"
                ]
                continue

            # Check if employee has a shift
            if not employee.shift:
                validation_errors[f"item_{index}"] = [
                    f"Employee '{employee.user.name}' (ID: {employee.employee_id}) does not have a shift assigned"
                ]
                continue

            # Check for duplicate punch data
            date = item.get("date")
            if PunchDataDailyTime.objects.filter(
                date=date, shift=employee.shift
            ).exists():
                validation_errors[f"item_{index}"] = [
                    f"Punch data already exists for date {date} and shift {employee.shift.name}"
                ]
                continue

            # Prepare item for creation
            processed_item = {
                "date": item["date"],
                "worked_hour": item.get("worked_hour"),
                "check_in": item.get("check_in"),
                "check_out": item.get("check_out"),
                "remark": item.get("remark"),
                "employee": employee,
                "shift": employee.shift,
                "created_by": user,
                "company": company,
                "is_punch_data": True,
                "status": PunchDataDailyTimeStatusChoices.PRESENT,
            }
            processed_items.append(processed_item)

        # If there are validation errors, raise them all at once
        if validation_errors:
            raise ValidationError(validation_errors)

        # All validation passed, create the records
        instances = PunchDataDailyTime.objects.bulk_create(
            [PunchDataDailyTime(**item) for item in processed_items]
        )
        return {"data": instances, "status_code": 201}
