def get_leave_type_slug(instance):
    return f"leave-type-{str(instance.uid).split('-')[0]}"