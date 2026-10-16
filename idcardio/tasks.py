from celery import shared_task


@shared_task(name="idcardio.render_print_job")
def render_print_job(job_id):
    from .models import PrintJob
    from .services.ops import render_job

    job = PrintJob.objects.select_related("company").filter(pk=job_id).first()
    if job is not None and job.status == "QUEUED":
        render_job(job)


@shared_task(name="idcardio.daily")
def daily():
    """Expiry notices, photo retention and the 90-day print artifacts."""
    from companyio.models import Company

    from .services.ops import apply_retention, emit_expiring

    for company in Company.objects.all():
        emit_expiring(company)
        apply_retention(company)
