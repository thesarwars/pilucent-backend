from attendanceio.choices import AttendanceStatusChoices


def get_attendance_status(check_in, check_out, shift):
    if check_in >= shift.in_time and not check_out:
        return AttendanceStatusChoices.LATE_ARRIVAL
    elif check_out and check_out < shift.out_time:
        return AttendanceStatusChoices.EARLY_DEPARTURE
    return AttendanceStatusChoices.PRESENT
