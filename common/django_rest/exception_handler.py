"""Project-wide DRF exception handler.

Delegates everything to DRF's default and adds one case: Django's
``ProtectedError``, raised when a delete would orphan rows behind an
``on_delete=PROTECT`` foreign key.

Without this the default handler does not recognise ``ProtectedError`` at all, so
it escapes as an unhandled exception and the client gets a 500 with no
explanation. That matters here because ``JournalEntryConnector.account`` became
``PROTECT`` to stop a deleted account taking its ledger history with it — the
guard is correct, but "500 Internal Server Error" is the wrong way to say
"this account has transactions".

409 Conflict is the accurate status: the request is well-formed and the caller is
authorised, but the resource's current state forbids it.
"""

import logging

from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


logger = logging.getLogger(__name__)

MESSAGE = (
    "This record cannot be deleted because other records depend on it. "
    "Deactivate it instead."
)


def _describe(error):
    """A short, safe hint at what is blocking the delete.

    Names the model and a count, never the protected rows themselves — the
    caller may not be entitled to see them, and on a ledger the count is the
    useful part anyway.
    """
    protected = getattr(error, "protected_objects", None)
    if not protected:
        return None
    try:
        rows = list(protected)
    except TypeError:  # pragma: no cover - defensive
        return None
    if not rows:
        return None
    label = rows[0]._meta.verbose_name_plural
    return f"{len(rows)} dependent {label}"


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is not None:
        return response

    if isinstance(exc, ProtectedError):
        view = context.get("view")
        logger.warning(
            "ProtectedError on %s: %s",
            view.__class__.__name__ if view else "unknown view",
            exc,
        )
        payload = {"error": True, "message": MESSAGE}
        detail = _describe(exc)
        if detail:
            payload["detail"] = detail
        return Response(payload, status=status.HTTP_409_CONFLICT)

    return None
