"""Celery entry point for the recurring generation job.

A thin wrapper over :func:`recurringio.services.runner.run_due` so the same code
path serves both the management command and a scheduled task. No beat process is
configured in this deployment yet; when one is added, point it here:

    app.conf.beat_schedule = {
        "run-recurring-templates": {
            "task": "recurringio.tasks.run_recurring_templates",
            "schedule": crontab(hour=2, minute=0),
        },
    }
"""

from celery import shared_task

from .services import runner


@shared_task(bind=True)
def run_recurring_templates(self, catch_up_days=None):
    """Fire every due recurring template. Returns the run summary."""
    kwargs = {}
    if catch_up_days is not None:
        kwargs["catch_up_days"] = catch_up_days
    return runner.run_due(**kwargs)
