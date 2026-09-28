from rest_framework.serializers import ModelSerializer

from ...models import Attendance, Holiday, HolidayDetails


class AttendanceBaseSerializer(ModelSerializer):
    class Meta:
        model = Attendance
        fields = [
            "date",
            "check_in",
            "check_out",
            "worked_hour",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PrivateAttendanceSlimSerializer(AttendanceBaseSerializer):

    class Meta:
        model = AttendanceBaseSerializer.Meta.model
        fields = ["uid"] + AttendanceBaseSerializer.Meta.fields
        read_only_fields = fields


class PublicAttendanceSlimSerializerSlimSerializer(AttendanceBaseSerializer):

    class Meta:
        model = AttendanceBaseSerializer.Meta.model
        fields = ["slug"] + AttendanceBaseSerializer.Meta.fields
        read_only_fields = fields


# class AttendanceSessionBaseSerializer(ModelSerializer):
#     class Meta:
#         model = AttendanceSession
#         fields = [
#             "date",
#             "check_in",
#             "check_out",
#             "worked_hour",
#             "created_at",
#             "updated_at",
#         ]
#         read_only_fields = fields


# class PrivateAttendanceSessionSlimSerializer(AttendanceSessionBaseSerializer):

#     class Meta:
#         model = AttendanceSessionBaseSerializer.Meta.model
#         fields = ["uid"] + AttendanceSessionBaseSerializer.Meta.fields
#         read_only_fields = fields


# class PublicAttendanceSessionSlimSerializer(AttendanceSessionBaseSerializer):

#     class Meta:
#         model = AttendanceSessionBaseSerializer.Meta.model
#         fields = ["slug"] + AttendanceSessionBaseSerializer.Meta.fields
#         read_only_fields = fields


class PrivateHolidaySlimSerializer(ModelSerializer):
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
        ]
        read_only_fields = fields


class PrivateHolidayDetailsSlimSerializer(ModelSerializer):
    class Meta:
        model = HolidayDetails
        fields = ["uid", "type", "date", "description"]
        read_only_fields = fields
