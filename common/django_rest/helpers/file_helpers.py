import os
import uuid

from datetime import datetime

from jinja2 import Template

from weasyprint import HTML

from django.conf import settings
from django.core.files import File

from fileroomio.models import FileItem, FileItemConnector
from fileroomio.choices import FileItemKindChoices, FileItemStatusChoices


def file_url(file_field, request=None):
    """Absolute URL for a stored file.

    With S3 media storage ``.url`` is already absolute, so callers must NOT
    prefix it with the request host -- doing so produced
    ``https://api.example.com/https://bucket.s3...`` in every document email.
    Falls back to building an absolute URL from the request only when storage
    is local and ``.url`` is a site-relative path.
    """
    if not file_field:
        return ""
    url = file_field.url
    if url.startswith(("http://", "https://")):
        return url
    if request is not None and hasattr(request, "build_absolute_uri"):
        return request.build_absolute_uri(url)
    return url


def link_file_to(file_item, obj, model_kind):
    """Attach a generated PDF to the document it belongs to.

    Without this the file is orphaned: it exists in storage but no endpoint can
    find it, so the document's Download action returns nothing. That was the
    state for 345 of 349 generated PDFs.
    """
    if file_item is None or obj is None or not model_kind:
        return None
    connector = FileItemConnector(model_kind=model_kind, file_item=file_item)
    field = {
        "SALE": "sale",
        "PURCHASE": "purchase",
        "CREDIT_NOTE": "credit_note",
        "SALE_PAYMENT_RECEIVE": "sale_payment_receive",
        "PURCHASE_PAYMENT": "purchase_payment",
        "PAY_BILL": "pay_bill",
        "BANK_DEPOSIT": "bank_deposit",
    }.get(str(model_kind))
    if field is None:
        return None
    setattr(connector, field, obj)
    connector.save()
    return connector


REPORT_WORKING_DIR = os.path.join("media", "reports")


def report_file_names(company, label, date_time):
    """The name a user downloads, and a scratch path to build the file at.

    Deliberately two different strings. They used to be one --
    ``media/reports/{label}-{timestamp}.pdf``, with second granularity and no
    company anywhere in it -- and both PDF generators used the same scheme, so
    any two of them could collide.

    Two people in **different companies** generating the same kind of document
    in the same second raced on one path: the second write overwrote the first,
    the first request then opened that path and attached the *other company's*
    PDF to its own ``FileItem``, removed the file, and the second request got a
    ``FileNotFoundError``. A cross-tenant document leak and a 500, out of a
    filename. It is also what made this test suite unable to run in parallel.

    The working path is a uuid because uniqueness is all it needs. The stored
    name keeps the company, so a downloaded report says whose it is.
    """
    parts = [
        str(part)
        for part in (getattr(company, "name", None), label, date_time)
        if part
    ]
    stored_name = f"{'-'.join(parts)}.pdf" if parts else f"{uuid.uuid4().hex}.pdf"
    return stored_name, os.path.join(REPORT_WORKING_DIR, f"{uuid.uuid4().hex}.pdf")


def get_pdf(self, is_from_view, context):
    now = datetime.now()
    date_time = now.strftime("%dth %B %Y, %H:%M:%S").lower()

    label = context.get("label")

    # Adding date-time in context
    context["date_time"] = date_time
    template = context["template_path"] = os.path.join(
        settings.BASE_DIR, "templates", context["template"]
    )
    company = None
    if self and is_from_view == True:
        company = self.request.user.get_active_company()
        context["company_name"] = company.name
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")
        context["as_of"] = (
            {"start_date": start_date, "end_date": end_date}
            if start_date and end_date
            else None
        )
    elif self and is_from_view == False:
        company = self.context["request"].user.get_active_company()
        context["company_name"] = company.name

    # Updating the label
    os.makedirs(REPORT_WORKING_DIR, exist_ok=True)  # Ensure the directory exists
    file_name, pdf_path = report_file_names(company, label, date_time)

    # Load HTML template as string
    with open(template) as f:
        html_template = f.read()

    # Render using Jinja2
    template = Template(html_template)
    html_rendered = template.render(context)

    # Generate PDF
    HTML(string=html_rendered).write_pdf(pdf_path)

    try:
        # Delete all old fileitems
        FileItem.objects.filter(
            company=company, is_report=True, kind=FileItemKindChoices.PDF
        ).delete()

        # Creating fileitem. The stored name is passed explicitly -- without it
        # the file would be saved under the scratch uuid rather than something
        # a person can read.
        with open(pdf_path, "rb") as f:
            file = FileItem.objects.create(
                company=company,
                is_report=context.get("is_report", False),
                file=File(f, name=file_name),
                kind=FileItemKindChoices.PDF,
                status=FileItemStatusChoices.PUBLISHED,
                title=label,
            )
    finally:
        # In a finally so a failure between here and the write does not leave
        # the scratch file behind; these accumulated in media/reports before.
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
    return file


def generate_pdf_direct(company, context):
    """
    Standalone PDF generator for use outside of serializer/view context (e.g. Celery tasks,
    migration importers). Mirrors get_pdf() but accepts the company object directly instead
    of extracting it from self.context["request"].
    """
    now = datetime.now()
    date_time = now.strftime("%dth %B %Y, %H:%M:%S").lower()

    label = context.get("label")

    context["date_time"] = date_time
    context["company_name"] = company.name
    template = context["template_path"] = os.path.join(
        settings.BASE_DIR, "templates", context["template"]
    )

    os.makedirs(REPORT_WORKING_DIR, exist_ok=True)
    file_name, pdf_path = report_file_names(company, label, date_time)

    with open(template) as f:
        html_template = f.read()

    template = Template(html_template)
    html_rendered = template.render(context)

    HTML(string=html_rendered).write_pdf(pdf_path)

    try:
        FileItem.objects.filter(
            company=company, is_report=True, kind=FileItemKindChoices.PDF
        ).delete()

        with open(pdf_path, "rb") as f:
            file = FileItem.objects.create(
                company=company,
                is_report=context.get("is_report", False),
                file=File(f, name=file_name),
                kind=FileItemKindChoices.PDF,
                status=FileItemStatusChoices.PUBLISHED,
                title=label,
            )
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
    return file
