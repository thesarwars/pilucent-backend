from rest_framework import serializers


class PrivateWeEmployeeJobCardOverviewSerializer(serializers.Serializer):
    present_in_time_count = serializers.IntegerField(read_only=True)
    early_out_count = serializers.IntegerField(read_only=True)
    late_count = serializers.IntegerField(read_only=True)
    absent_count = serializers.IntegerField(read_only=True)
    leave_count = serializers.IntegerField(read_only=True)
    workable_hour_count = serializers.FloatField(read_only=True)
    worked_hour_count = serializers.FloatField(read_only=True)
    difference_hour_count = serializers.FloatField(read_only=True)
    ot_hour_count = serializers.FloatField(read_only=True)
    un_paid_leave_hour_count = serializers.FloatField(read_only=True)
    paid_leave_hour_count = serializers.FloatField(read_only=True)
