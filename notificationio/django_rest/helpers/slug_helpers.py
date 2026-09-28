def get_notification_slug(instance):
    return f"notification-{str(instance.uid).split('-')[0]}"

def get_notification_setting_slug(instance):
    return f"notification-settings-{str(instance.uid).split('-')[0]}"