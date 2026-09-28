"""Moov webhook receiver — keeps local transfer status in sync with Moov.

A transfer is written PENDING when created; Moov then sends ``transfer.updated``
events as it settles (pending -> completed/failed/reversed). This endpoint
applies those to the matching ``MoovTransfers`` row.

Auth is by Moov's signature, not a session: every event carries an HMAC-SHA512
of ``X-Timestamp | X-Nonce | X-Webhook-ID`` keyed by the webhook's signing secret
(from the Moov dashboard). We reject anything that doesn't verify.
"""

import hashlib
import hmac
import logging

from django.conf import settings

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from moovmoneyio.choices import MoovTransferStatusChoices
from moovmoneyio.models import MoovTransfers

logger = logging.getLogger(__name__)

# Moov transfer status -> our MoovTransferStatusChoices.
_STATUS_MAP = {
    "created": MoovTransferStatusChoices.PENDING,
    "queued": MoovTransferStatusChoices.PENDING,
    "pending": MoovTransferStatusChoices.PENDING,
    "completed": MoovTransferStatusChoices.COMPLETED,
    "failed": MoovTransferStatusChoices.FAILED,
    "reversed": MoovTransferStatusChoices.CANCELED,
    "canceled": MoovTransferStatusChoices.CANCELED,
    "cancelled": MoovTransferStatusChoices.CANCELED,
}


def verify_moov_signature(request) -> bool:
    """True when the request's X-Signature matches an HMAC of its Moov headers."""
    secret = getattr(settings, "MOOV_WEBHOOK_SECRET", "")
    if not secret:
        # Fail closed: without the signing secret we cannot trust any event.
        logger.error("MOOV_WEBHOOK_SECRET is not configured; rejecting webhook.")
        return False

    timestamp = request.headers.get("X-Timestamp", "")
    nonce = request.headers.get("X-Nonce", "")
    webhook_id = request.headers.get("X-Webhook-ID", "")
    signature = request.headers.get("X-Signature", "")
    if not signature:
        return False

    payload = f"{timestamp}|{nonce}|{webhook_id}"
    expected = hmac.new(
        secret.encode(), payload.encode(), hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _extract_transfer(event):
    """Return (transfer_id, moov_status) from a transfer event, defensively."""
    data = event.get("data") or {}
    nested = data.get("transfer") or {}
    transfer_id = (
        data.get("transferID")
        or data.get("transfer_id")
        or nested.get("transferID")
        or nested.get("transfer_id")
    )
    moov_status = data.get("status") or nested.get("status")
    return transfer_id, moov_status


class MoovWebhookView(APIView):
    """POST /moov-money/webhook — receive Moov events (signature-verified)."""

    permission_classes = [AllowAny]
    authentication_classes = []  # Moov signs; no session/JWT.

    def post(self, request):
        if not verify_moov_signature(request):
            return Response(
                {"error": "invalid signature"}, status=status.HTTP_400_BAD_REQUEST
            )

        event = request.data or {}
        event_type = str(event.get("type", ""))

        if event_type.startswith("transfer"):
            transfer_id, moov_status = _extract_transfer(event)
            mapped = _STATUS_MAP.get(str(moov_status).lower()) if moov_status else None
            if transfer_id and mapped:
                updated = MoovTransfers.objects.filter(
                    moov_transfer_uid=transfer_id
                ).update(status=mapped)
                logger.info(
                    "Moov webhook %s: transfer %s -> %s (%d row(s))",
                    event_type, transfer_id, mapped, updated,
                )
            else:
                logger.info(
                    "Moov webhook %s: no actionable transfer id/status (id=%s status=%s)",
                    event_type, transfer_id, moov_status,
                )

        # Always 200 so Moov doesn't retry a well-formed, verified event.
        return Response({"received": True}, status=status.HTTP_200_OK)
