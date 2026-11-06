"""Django email backend that sends through Resend's HTTP API.

Every email in the app goes through Django's mail layer (send_mail,
EmailMultiAlternatives), so setting EMAIL_BACKEND to this class moves all of
it to Resend without touching the call sites. It is switched on in settings
when RESEND_API_KEY is present.
"""

import base64
import logging
import mimetypes

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


class ResendEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, api_key=None, timeout=None, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = api_key or getattr(settings, "RESEND_API_KEY", None)
        self.timeout = timeout or getattr(settings, "RESEND_TIMEOUT", 15)

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        if not self.api_key:
            if self.fail_silently:
                return 0
            raise RuntimeError("RESEND_API_KEY is not set")
        sent = 0
        with requests.Session() as session:
            session.headers["Authorization"] = f"Bearer {self.api_key}"
            for message in email_messages:
                try:
                    response = session.post(RESEND_URL, json=self._payload(message), timeout=self.timeout)
                    if response.status_code >= 400:
                        raise RuntimeError(f"Resend rejected the email ({response.status_code}): {response.text[:500]}")
                    sent += 1
                except Exception:
                    logger.exception("Resend: sending %r to %s failed", message.subject, message.to)
                    if not self.fail_silently:
                        raise
        return sent

    def _payload(self, message):
        payload = {
            "from": message.from_email or settings.DEFAULT_FROM_EMAIL,
            "to": list(message.to),
            "subject": message.subject,
        }
        if message.cc:
            payload["cc"] = list(message.cc)
        if message.bcc:
            payload["bcc"] = list(message.bcc)
        if message.reply_to:
            payload["reply_to"] = list(message.reply_to)
        if message.extra_headers:
            payload["headers"] = {k: str(v) for k, v in message.extra_headers.items()}

        html = None
        for content, mimetype in getattr(message, "alternatives", None) or []:
            if mimetype == "text/html":
                html = content
        if getattr(message, "content_subtype", "plain") == "html":
            html = message.body
        else:
            payload["text"] = message.body
        if html is not None:
            payload["html"] = html

        attachments = [self._attachment(a) for a in message.attachments]
        attachments = [a for a in attachments if a]
        if attachments:
            payload["attachments"] = attachments
        return payload

    @staticmethod
    def _attachment(attachment):
        # Django keeps attachments as (filename, content, mimetype) tuples or
        # as MIMEBase parts; Resend wants base64 content with a filename.
        if isinstance(attachment, tuple):
            filename, content, mimetype = attachment[0], attachment[1], attachment[2]
            if isinstance(content, str):
                content = content.encode()
            item = {"filename": filename or "attachment", "content": base64.b64encode(content).decode()}
            mimetype = mimetype or mimetypes.guess_type(filename or "")[0]
            if mimetype:
                item["content_type"] = mimetype
            return item
        filename = attachment.get_filename()
        content = attachment.get_payload(decode=True)
        if content is None:
            return None
        return {"filename": filename or "attachment", "content": base64.b64encode(content).decode()}
