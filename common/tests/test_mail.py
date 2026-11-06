from unittest import mock

from django.core.mail import EmailMultiAlternatives, get_connection, send_mail
from django.test import SimpleTestCase, override_settings

BACKEND = "common.mail.ResendEmailBackend"


def _ok():
    return mock.Mock(status_code=200, text='{"id":"x"}')


@override_settings(EMAIL_BACKEND=BACKEND, RESEND_API_KEY="re_test")
class ResendBackendTests(SimpleTestCase):
    @mock.patch("common.mail.requests.Session.post", return_value=_ok())
    def test_html_email_with_reply_to_and_attachment(self, post):
        msg = EmailMultiAlternatives(
            subject="Verify", body="plain", from_email="Pilucent <hello@example.com>",
            to=["a@example.com"], reply_to=["r@example.com"],
        )
        msg.attach_alternative("<b>hi</b>", "text/html")
        msg.attach("payslip.pdf", b"%PDF", "application/pdf")
        self.assertEqual(msg.send(), 1)

        url = post.call_args.args[0]
        payload = post.call_args.kwargs["json"]
        self.assertEqual(url, "https://api.resend.com/emails")
        self.assertEqual(payload["from"], "Pilucent <hello@example.com>")
        self.assertEqual(payload["to"], ["a@example.com"])
        self.assertEqual(payload["reply_to"], ["r@example.com"])
        self.assertEqual(payload["html"], "<b>hi</b>")
        self.assertEqual(payload["text"], "plain")
        self.assertEqual(payload["attachments"], [{"filename": "payslip.pdf", "content": "JVBERg==", "content_type": "application/pdf"}])

    @mock.patch("common.mail.requests.Session.post", return_value=_ok())
    def test_send_mail_html_message(self, post):
        self.assertEqual(send_mail("S", "body", "f@example.com", ["t@example.com"], html_message="<p>x</p>"), 1)
        self.assertEqual(post.call_args.kwargs["json"]["html"], "<p>x</p>")

    @mock.patch("common.mail.requests.Session.post", return_value=mock.Mock(status_code=403, text="domain not verified"))
    def test_rejection_raises_unless_silent(self, post):
        msg = EmailMultiAlternatives("S", "b", "f@example.com", ["t@example.com"])
        with self.assertRaises(RuntimeError):
            msg.send()
        self.assertEqual(get_connection(BACKEND, fail_silently=True).send_messages([msg]), 0)
