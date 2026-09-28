from celery import Celery
from celery.signals import task_prerun, task_postrun
import os
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "master.settings")

app = Celery("master")

app.config_from_object(settings, namespace="CELERY")
app.autodiscover_tasks()


# Celery workers are long-lived processes that hold thread-local Django DB
# connections between tasks. With CONN_MAX_AGE=0 Django only closes connections
# on the request_started/finished signals -- which never fire inside a worker --
# so a stale/dead connection can linger and a fresh one be opened on top of it,
# slowly consuming RDS connection slots. Close any unusable/old connections
# around every task so a worker holds at most one live connection at a time.
@task_prerun.connect
@task_postrun.connect
def _close_old_db_connections(*args, **kwargs):
    from django.db import close_old_connections

    close_old_connections()


try:
    from transactionio.tasks import (  # noqa: F401
        apply_transaction_rule_task,
        apply_all_transaction_rules_for_company_task,
        apply_rules_for_new_transactions_task,
    )
except ImportError:
    pass

@app.task
def send_email(email):
    from django.core.mail import send_mail
    from django.conf import settings

    subject = "Welcome to Master"
    message = "Thank you for signing up!"
    from_email = settings.DEFAULT_HOST_USER
    recipient_list = [email]

    send_mail(subject, message, from_email, recipient_list)
    
    return f"Email sent to {email}"
