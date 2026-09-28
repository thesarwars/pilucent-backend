def get_thread_slug(instance):
    return f"thread-{str(instance.uid).split('-')[0]}"

def get_inbox_slug(instance):
    return f"inbox-{str(instance.uid).split('-')[0]}"
