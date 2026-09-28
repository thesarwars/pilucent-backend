import logging

from .tasks import send_email

logger = logging.getLogger(__name__)


def send_user_email_verification_otp(to_email, username, otp, reply_to=None):
    logger.info("Balanzify activation email is being sent...")
    subject = "Your Balanzify Email Activation OTP"
    send_email(
        {
            "username" : username,
            "otp": otp,
            "message": subject,
        },
        "emails/otp/verification_email.html",
        to_email,
        subject,
    )


def send_email_to_user(context, template, to_emails, subject, reply_to=None):
    logger.info("Balanzify email is being sent...")
    for to_email in to_emails:
        send_email(context, template, to_email, subject)
