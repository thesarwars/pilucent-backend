"""Base class for all v2 dashboard cards.

Each card is its own endpoint, but they share:
- global filter parsing (company, date range, comparison period, ...)
- subscription feature gating -> ``restricted`` envelope instead of a 403
- per-card error isolation -> a failing card returns its ``error_state`` with
  HTTP 200 so the rest of the dashboard still renders (spec section 5).
"""

import hashlib
import logging

from django.conf import settings
from django.core.cache import cache

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from weapi.django_rest.helpers.dashboard.envelope import (
    error_card,
    restricted_card,
)
from weapi.django_rest.helpers.dashboard.filters import build_filters
from weapi.django_rest.helpers.dashboard.permissions import company_has_feature


logger = logging.getLogger(__name__)

# Falls back to a sane default if the setting is absent.
_DEFAULT_CACHE_TTL = getattr(settings, "DASHBOARD_CARD_CACHE_TTL", 30)


class DashboardCardView(APIView):
    permission_classes = [IsAuthenticated]

    # Identifier returned in the envelope and used in logs.
    card_key = None
    # Subscription flag (e.g. "is_payroll") required to view real values.
    required_feature = None
    # Frontend route the card drills down into.
    action_route = None
    # Per-card cache TTL in seconds. ``None`` -> use the project default; set to
    # ``0`` on a card to opt out of caching entirely.
    cache_ttl = None

    def get_card_data(self, request, filters):
        """Return the card envelope. Implemented by each card subclass."""
        raise NotImplementedError

    def _cache_ttl(self):
        return _DEFAULT_CACHE_TTL if self.cache_ttl is None else self.cache_ttl

    def _cache_key(self, request, filters):
        """Stable key scoped to company + card + all query params.

        Company-scoped data is identical for every user in the company, so the
        key intentionally omits the user to maximise hit rate. Query params
        (date range, currency, buckets, months, ...) are folded in so different
        views of the dashboard don't collide.
        """
        params = "&".join(
            f"{k}={v}" for k, v in sorted(request.query_params.items())
        )
        raw = f"{filters.company.id}:{self.card_key}:{params}"
        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
        return f"dashv2:{digest}"

    def get(self, request, *args, **kwargs):
        filters = build_filters(request)

        if filters.company is None:
            return Response(
                error_card(self.card_key, "No active company for this user."),
                status=200,
            )

        if not company_has_feature(request.user, self.required_feature):
            return Response(
                restricted_card(self.card_key, action_route=self.action_route),
                status=200,
            )

        ttl = self._cache_ttl()
        # ``?refresh=1`` lets the client force a recompute (e.g. a manual reload).
        bypass = request.query_params.get("refresh") in ("1", "true", "True")
        cache_key = self._cache_key(request, filters) if ttl and not bypass else None

        if cache_key is not None:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached, status=200)

        try:
            data = self.get_card_data(request, filters)
        except Exception as exc:  # noqa: BLE001 - card-level isolation by design
            logger.exception("Dashboard card '%s' failed", self.card_key)
            # Errors are deliberately not cached so a transient failure doesn't
            # stick for the whole TTL window.
            return Response(error_card(self.card_key, str(exc)), status=200)

        if cache_key is not None:
            cache.set(cache_key, data, ttl)

        return Response(data, status=200)
