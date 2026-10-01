import logging

from django.core.mail import EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string
from django.conf import settings

# from master.celeryapp import app

logger = logging.getLogger(__name__)


def send_demo_email(to_email, subject, email_body):
    context = {
        "url": f"{settings.APP_URL}/meet/123456asdwers/"
    }
    html_body = render_to_string(
        "emails/forget_password/reset_password_email.html", context
    )

    # email_from = settings.DEFAULT_HOST_USER
    status = send_mail(subject=subject, message=email_body, from_email=settings.DEFAULT_HOST_USER, recipient_list=[to_email], html_message=email_body)
    print('mail_status', status)
    # status = send_mail(subject=subject, message=email_body, from_email=email_from, recipient_list=[to_email], auth_user=email_from, auth_password=auth_password)
    # msg.send()
    logger.info("Email: {}, Subject: {}".format(to_email, subject))
    return status