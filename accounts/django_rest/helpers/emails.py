"""
To add celery is our next plan as time is short now
"""

import logging

from django.core.mail import EmailMultiAlternatives, send_mail

from django.conf import settings

from django.template.loader import render_to_string

from common.django_rest.helpers.tasks import send_email

# from master.celeryapp import app

logger = logging.getLogger(__name__)


def send_forget_password_link_email(to_email, uid, token, reply_to=None):
    subject = f"{settings.PRODUCT_NAME} reset password link"
    send_email(
        {
            "url": f"{settings.SELF_SERVICE_URL}/password/{uid}?token={token}"
        },
        "emails/forget_password/reset_password.html",
        to_email,
        subject
    )

