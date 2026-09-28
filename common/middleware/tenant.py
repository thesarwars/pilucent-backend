"""Tenant-context middleware.

Reads the selected company from the request's JWT (the ``company_id`` claim set
by the workspace ``select-company`` exchange) and publishes it two ways for the
duration of the request:

  1. into the per-request :mod:`common.tenant` contextvar, which powers
     application-level scoping (``User.get_active_company()`` etc.), and
  2. into the Postgres session GUC ``app.company_id``, which the row-level
     security policies read via ``current_setting('app.company_id', true)``.

Why decode the token here instead of using ``request.user``? DRF's JWT
authentication runs *inside* the view, so ``request.user`` is still anonymous at
middleware time. We therefore validate the bearer token independently (cheap:
signature + expiry, no DB hit) and trust its signed ``company_id`` claim. The
claim is only ever minted after membership was verified, and
``get_active_company()`` re-checks membership against the id, so a stale claim
can never widen access.

Both values are always cleared in ``finally`` so nothing leaks across requests
that reuse the same worker thread or database connection.
"""

import logging

from django.db import connection

from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from accounts.django_rest.helpers.workspace import COMPANY_ID_CLAIM
from common.tenant import reset_current_company_id, set_current_company_id

logger = logging.getLogger(__name__)

PG_TENANT_GUC = "app.company_id"


def _company_id_from_request(request):
    """Return the company id from the request's bearer token, or None."""
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.startswith("Bearer "):
        return None
    raw_token = header[len("Bearer ") :].strip()
    if not raw_token:
        return None
    try:
        token = AccessToken(raw_token)
    except TokenError:
        # Invalid/expired token: leave the request unscoped. The view's own
        # authentication will reject it with the proper 401 if needed.
        return None
    return token.get(COMPANY_ID_CLAIM)


def _set_pg_company(company_id):
    """Set/clear the Postgres GUC used by RLS policies (no-op on non-Postgres)."""
    if connection.vendor != "postgresql":
        return
    value = "" if company_id is None else str(company_id)
    with connection.cursor() as cursor:
        # session-scoped (is_local=false); cleared in finally and the connection
        # is closed at request end, so it never bleeds into another request.
        cursor.execute("SELECT set_config(%s, %s, false)", [PG_TENANT_GUC, value])


class TenantContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        company_id = _company_id_from_request(request)
        token = set_current_company_id(company_id)
        try:
            if company_id is not None:
                try:
                    _set_pg_company(company_id)
                except Exception:  # pragma: no cover - DB set must never 500 a request
                    logger.exception("Failed to set tenant GUC for company %s", company_id)
            response = self.get_response(request)
        finally:
            reset_current_company_id(token)
            try:
                _set_pg_company(None)
            except Exception:  # pragma: no cover
                logger.exception("Failed to clear tenant GUC")
        return response
