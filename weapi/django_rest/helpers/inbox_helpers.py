def get_inbox_target(instance, request_user):
    return instance.user if request_user != instance.user else instance.target


def get_inbox_is_seen(instance, request_user):
    last_thread = instance.get_last_thread()
    if last_thread is None:
        return instance.is_seen
    return True if last_thread.author == request_user else instance.is_seen
