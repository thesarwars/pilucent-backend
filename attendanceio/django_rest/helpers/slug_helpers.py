def get_attendance_slug(instance):
    return f"attendance-{instance.date}"


def get_daily_time_tracking_slug(instance):
    return f"daily-time-tracking-{instance.date}"

def get_punch_data_daily_time_slug(instance):
    return f"punch-data-daily-time-{instance.uid}"

def get_daily_time_tracking_session_slug(instance):
    return f"daily-time-tracking-session-{str(instance.uid)[0]}"

def get_holiday_slug(instance):
    return f"holiday-{str(instance.uid).split('-')[0]}"

def get_holiday_details_slug(instance):
    return f"holiday-details-{str(instance.uid).split('-')[0]}"

def get_attendance_process_slug(instance):
    return f"attendance-process-{str(instance.uid).split('-')[0]}"

def get_attendance_process_item_slug(instance):
    return f"attendance-process-item-{str(instance.uid).split('-')[0]}"
