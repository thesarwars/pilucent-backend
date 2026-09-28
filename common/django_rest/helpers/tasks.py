import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string

# from master.celeryapp import app

logger = logging.getLogger(__name__)


# @app.task
def send_email(context, template, to_email, subject, reply_to=None):
    email_from = settings.DEFAULT_HOST_USER
    html_body = render_to_string(template, context)
    text_body = "Please view this email in an HTML-compatible client."
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=email_from,
        to=[to_email],
        reply_to=[reply_to] if reply_to else None,
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send()
    logger.info("Email: {}, Subject: {}".format(to_email, subject))
    return subject
