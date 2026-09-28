from functools import wraps

from auditlog.context import set_actor


def set_auditlog_actor(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        user = self.context["request"].user
        with set_actor(user):
            return func(self, *args, **kwargs)

    return wrapper
