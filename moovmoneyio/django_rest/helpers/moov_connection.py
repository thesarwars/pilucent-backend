import base64
import json
import logging
from contextlib import contextmanager
from urllib.parse import urlparse

import httpx
from django.conf import settings
from django.utils import timezone

from moovio_sdk import Moov
from moovio_sdk.models import components, errors as moov_errors

logger = logging.getLogger(__name__)

MOOV_API_BASE = "https://api.moov.io"
MOOV_DEFAULT_VERSION = "v2026.07.00"
# MOOV_DEFAULT_VERSION = "v2024.01.00"

# A browser-like User-Agent is required for server-to-server calls.
# Cloudflare's WAF blocks python-httpx/requests from cloud/datacenter IPs
# but allows requests that look like they come from a browser.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Secrets / PII that must never reach the logs. The whole value is masked, so
# masking "tax_id" also hides the nested {"ein": {"number": ...}}.
_REDACT_KEYS = {
    "token",
    "moov_token",
    "tax_id",
    "taxid",
    "ssn",
    "itin",
    "government_id",
    "governmentid",
    "account_number",
    "accountnumber",
    "routing_number",
    "routingnumber",
    "card_number",
    "cardnumber",
}


def redact_moov_payload(value):
    """Return a copy of a Moov payload with secrets/PII masked — safe to log."""
    if isinstance(value, dict):
        return {
            key: (
                "***redacted***"
                if key.lower().replace("-", "_") in _REDACT_KEYS
                else redact_moov_payload(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_moov_payload(item) for item in value]
    return value


def describe_moov_error(exc: Exception) -> dict:
    """Flatten a moovio_sdk exception into loggable detail.

    Every Moov HTTP failure subclasses ``MoovError``, which carries the status
    code, the raw response body, and the response headers — where Moov puts the
    ``X-Request-ID`` that their support team needs to trace a request. Typed
    errors (e.g. ``CreateAccountError``) additionally expose ``.data`` with
    per-field detail, such as exactly what Moov rejected in ``termsOfService``
    or ``profile``. ``str(exc)`` throws all of that away, so pull it out here.
    """
    detail: dict = {"type": type(exc).__name__}

    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        detail["status_code"] = status_code

    headers = getattr(exc, "headers", None)
    if headers is not None:
        request_id = headers.get("x-request-id")
        if request_id:
            detail["request_id"] = request_id  # give this to Moov support

    body = getattr(exc, "body", None)
    if body:
        try:
            detail["body"] = json.loads(body)
        except (TypeError, ValueError):
            detail["body"] = str(body)[:2000]

    data = getattr(exc, "data", None)
    if data is not None:
        dump = getattr(data, "model_dump", None)
        detail["fields"] = (
            dump(exclude_none=True, by_alias=True) if callable(dump) else str(data)
        )

    if "body" not in detail and "fields" not in detail:
        detail["message"] = str(exc)

    return detail


@contextmanager
def moov_client(version: str = MOOV_DEFAULT_VERSION):
    """Moov SDK context manager using facilitator Basic Auth.

    Usage:
        from moovmoneyio.django_rest.helpers.moov_connection import moov_client

        with moov_client() as moov:
            moov.accounts.get(account_id="...")
    """
    with Moov(
        x_moov_version=version,
        security=components.Security(
            username=settings.MOOV_USERNAME,
            password=settings.MOOV_PASSWORD,
        ),
    ) as moov:
        yield moov


def moov_call(call):
    """Run a Moov SDK call, tolerating the SDK lagging behind Moov's API.

    moovio_sdk 0.13.24 strictly validates every response against its generated
    Pydantic models, but the live API is many major versions ahead (the SDK is
    now 26.x). When Moov returns an enum value the old models don't know — e.g.
    ``paymentMethodType: 'instant-bank-credit'`` once instant-bank capabilities
    are enabled — the SDK raises ``ResponseValidationError`` on an otherwise
    **successful** (2xx) response and the real data would be lost. Recover it from
    the raw response body instead of failing the request.

    ``call`` is a zero-arg callable returning an SDK response object. Returns
    ``_convert_moov_result(res.result)`` on the happy path, or the raw JSON body
    on the fallback path. Both key styles (bankAccountID / bank_account_id) reach
    callers, which already tolerate both. Non-2xx responses still raise.
    """
    from moovmoneyio.django_rest.helpers.convert_moov_response import (
        _convert_moov_result,
    )

    try:
        res = call()
    except moov_errors.ResponseValidationError as exc:
        raw_response = getattr(exc, "raw_response", None)
        if raw_response is not None and raw_response.is_success and getattr(
            exc, "body", None
        ):
            logger.warning(
                "Moov SDK could not parse a successful response (SDK 0.13.24 is "
                "behind the API); using the raw body. Detail: %s",
                str(exc).splitlines()[0][:200],
            )
            return json.loads(exc.body)
        raise

    try:
        return _convert_moov_result(res.result)
    except Exception:
        return res.result


def client_ip_from_request(request) -> str:
    """The END USER's IP, seen through whatever proxy/CDN fronts Django.

    Cloudflare sets CF-Connecting-IP; other proxies prepend the client to
    X-Forwarded-For. Falls back to REMOTE_ADDR (correct only with no proxy).
    """
    cf_ip = request.META.get("HTTP_CF_CONNECTING_IP")
    if cf_ip:
        return cf_ip.strip()

    forwarded = request.META.get("HTTP_X_FORWARDED_FOR") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()

    return (request.META.get("REMOTE_ADDR") or "").strip()


def moov_bearer_from_request(request):
    """The Moov OAuth token the frontend supplied with this request, if any.

    Read from the ``X-Moov-Token`` header (or a ``moov_token`` body field) —
    deliberately NOT ``Authorization``, which carries our own JWT. A ``Bearer ``
    prefix is tolerated. Returns None when the frontend sent nothing, in which
    case callers fall back to facilitator credentials.
    """
    raw = request.headers.get("X-Moov-Token") or request.headers.get(
        "X-Moov-Authorization"
    )
    if not raw:
        data = getattr(request, "data", None)
        if isinstance(data, dict):
            raw = data.get("moov_token")

    if not raw:
        return None

    raw = str(raw).strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    # Never log the token itself — it can carry /transfers.write (move money).
    logger.info("moov_bearer_from_request: forwarding client token (len=%d)", len(raw))
    return raw or None


def _request_domain(request) -> str:
    origin = request.META.get("HTTP_ORIGIN") or request.META.get("HTTP_REFERER") or ""
    if origin:
        return urlparse(origin).hostname or ""
    return ""


def build_terms_of_service_body(tos_raw, request):
    """Translate an incoming ``terms_of_service`` payload into Moov's shape.

    Returns ``(body, error_message)`` — exactly one is non-None.

    Two accepted shapes, checked in this order:

    * ``{"token": "..."}`` — a Moov.js Drop token. **This is the path we use.**
      Moov compares the IP that minted the token (the browser) against the IP
      submitting the request (this server) and rejects them when they match
      ("server address must not match client address"). That only collides in
      local/dockerised development, where the browser and the backend share one
      egress IP; in production the two genuinely differ and the token is accepted.

    * ``{"manual": {...}}`` — attested acceptance, kept only as a fallback. Moov
      currently rejects it for this platform ("manual terms of service has not
      been enabled for this account"), so it cannot succeed until Moov enables
      the flow. ``acceptedIP`` is always taken from THIS request, never from the
      client body: it attests where the real end user accepted.

    A token wins over manual when both are supplied.
    """
    if not isinstance(tos_raw, dict) or not tos_raw:
        return None, None

    if tos_raw.get("token"):
        return {"token": tos_raw["token"]}, None

    manual = tos_raw.get("manual")
    if isinstance(manual, dict):
        accepted = {
            "acceptedDate": manual.get("accepted_date")
            or timezone.now().isoformat().replace("+00:00", "Z"),
            "acceptedIP": client_ip_from_request(request),
            "acceptedUserAgent": manual.get("accepted_user_agent")
            or request.META.get("HTTP_USER_AGENT", ""),
            "acceptedDomain": manual.get("accepted_domain") or _request_domain(request),
        }
        missing = [key for key, value in accepted.items() if not value]
        if missing:
            return None, (
                "manual terms of service acceptance is missing required "
                f"field(s): {', '.join(missing)}"
            )
        return {"manual": accepted}, None

    return None, ("terms_of_service must contain either a 'token' or a 'manual' object")


def moov_basic_auth_header() -> str:
    """Return a Basic Auth Authorization header value for facilitator credentials."""
    creds = base64.b64encode(
        f"{settings.MOOV_USERNAME}:{settings.MOOV_PASSWORD}".encode()
    ).decode()
    return f"Basic {creds}"


def moov_get_oauth_token(scope: str = "/accounts.read /accounts.write") -> str:
    """
    Obtain a short-lived OAuth bearer token using client-credentials flow.

    Moov requires an OAuth token (not Basic Auth) for certain operations such as
    fetching a Terms-of-Service token.  Returns the raw access_token string.
    """
    url = f"{MOOV_API_BASE}/oauth2/token"
    origin = getattr(settings, "MOOV_ORIGIN", "https://accounting.balanzify.com")

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": "Balanzify-Backend/1.0",
        # "User-Agent": _BROWSER_UA,
        # "Origin": origin,
        # "Referer": origin + "/",
    }

    data = {
        "grant_type": "client_credentials",
        "client_id": settings.MOOV_USERNAME,
        "client_secret": settings.MOOV_PASSWORD,
        "scope": scope,
    }

    resp = httpx.post(url, data=data, headers=headers, timeout=15)

    if not resp.is_success:
        raise RuntimeError(
            f"Moov OAuth token request failed: {resp.status_code} {resp.text[:300]}"
        )

    # Log what Moov actually GRANTED (never the token itself). A 401 on the
    # subsequent call usually means the granted scope isn't what we asked for —
    # i.e. these facilitator keys aren't authorised for that scope.
    try:
        granted = resp.json()
        logger.info(
            "Moov OAuth token minted: requested_scope=%r granted_scope=%r "
            "token_type=%r expires_in=%s",
            scope,
            granted.get("scope"),
            granted.get("token_type"),
            granted.get("expires_in"),
        )
    except ValueError:
        logger.warning("Moov OAuth token response was not JSON")

    return resp.json()["access_token"]


def moov_get_tos_token(origin: str | None = None, referer: str | None = None) -> str:
    """
    Fetch a Moov Terms-of-Service token using an OAuth bearer token.

    Moov rejects ToS tokens that were created via Basic Auth — they must be
    obtained through an OAuth-authenticated request to /tos-token.

    Args:
        origin:  The Origin header value (e.g. the frontend URL). Defaults to MOOV_ORIGIN.
        referer: The Referer header value. Defaults to MOOV_ORIGIN + "/".

    Returns:
        The ToS token string to be sent as termsOfService.token in an account PATCH.
    """
    default_origin = getattr(
        settings, "MOOV_ORIGIN", "https://accounting.balanzify.com"
    )
    origin = origin or default_origin
    referer = referer or (default_origin + "/")

    access_token = moov_get_oauth_token()

    url = f"{MOOV_API_BASE}/tos-token"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": _BROWSER_UA,
        "Origin": origin,
        "Referer": referer,
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "x-moov-version": MOOV_DEFAULT_VERSION,
    }

    resp = httpx.get(url, headers=headers, timeout=15)

    if not resp.is_success:
        raise RuntimeError(
            f"Moov /tos-token request failed: {resp.status_code} {resp.text[:300]}"
        )

    token = resp.json().get("token")
    if not token:
        raise RuntimeError(
            f"Moov /tos-token response missing 'token': {resp.text[:300]}"
        )

    return token


def _do_moov_patch(
    url: str,
    body: dict,
    auth_header: str,
    version: str,
) -> httpx.Response:
    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json",
        "Accept": "application/json, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "x-moov-version": version,
        "User-Agent": "Balanzify-Backend/1.0",
        # "User-Agent": _BROWSER_UA,
        # "Origin": "https://accounting.balanzify.com",
        # "Referer": "https://accounting.balanzify.com/",
        # "Sec-Fetch-Site": "same-site",
        # "Sec-Fetch-Mode": "cors",
        # "Sec-Fetch-Dest": "empty",
    }

    resp = httpx.patch(url, json=body, headers=headers, timeout=30)

    diag_headers = {
        k: v
        for k, v in resp.headers.items()
        if k.lower()
        in {
            "x-request-id",
            "x-moov-request-id",
            "server",
            "cf-ray",
            "cf-mitigated",
            "content-type",
            "content-length",
        }
    }
    logger.info(
        "moov_patch ← status=%s auth=%s diag_headers=%s body=%s",
        resp.status_code,
        auth_header.split(" ", 1)[0],
        diag_headers,
        resp.text[:500] if resp.text else "<empty>",
    )

    if not resp.is_success:
        logger.warning(
            "moov_patch failed: status=%s url=%s auth=%s diag_headers=%s body=%s",
            resp.status_code,
            url,
            auth_header.split(" ", 1)[0],
            diag_headers,
            resp.text[:500] if resp.text else "<empty>",
        )

    return resp


def moov_patch(
    path: str,
    body: dict,
    version: str = MOOV_DEFAULT_VERSION,
    bearer_token: str | None = None,
) -> httpx.Response:

    url = f"{MOOV_API_BASE}{path}"

    if bearer_token:
        auth_header = f"Bearer {bearer_token}"
        logger.info(
            "moov_patch: using explicit bearer token for path=%s version=%s",
            path,
            version,
        )
        return _do_moov_patch(url, body, auth_header, version)

    # Default: try Basic Auth first.
    resp = _do_moov_patch(url, body, moov_basic_auth_header(), version)

    # Cloudflare WAF fingerprint: 403 with empty body and a cf-ray header
    # (and crucially, no x-request-id — that would indicate a real Moov response).
    is_cf_block = (
        resp.status_code == 403
        and not resp.text
        and "cf-ray" in {k.lower() for k in resp.headers.keys()}
        and "x-request-id" not in {k.lower() for k in resp.headers.keys()}
    )
    if is_cf_block:
        logger.warning(
            "moov_patch: Basic Auth got Cloudflare 403 (cf-ray=%s). "
            "Retrying with OAuth bearer token.",
            resp.headers.get("cf-ray"),
        )
        try:
            # Build account-scoped OAuth scopes for PATCH /accounts/{accountID}.
            # Generic /accounts.write is only for creating accounts; PATCHing an
            # existing one requires resource-scoped tokens.
            scope = _scopes_for_path(path, body)
            logger.info("moov_patch: OAuth fallback using scope=%r", scope)
            token = moov_get_oauth_token(scope=scope)
            resp = _do_moov_patch(url, body, f"Bearer {token}", version)
        except Exception as exc:
            logger.exception("moov_patch: OAuth fallback failed: %s", exc)

    return resp


def _scopes_for_path(path: str, body: dict) -> str:
    """
    Build the OAuth scope string required for a given Moov API path + body.

    For PATCH /accounts/{accountID}, Moov requires account-scoped permissions
    such as `/accounts/{accountID}/profile.write`. Add ToS scope when the body
    includes `termsOfService`.
    """
    parts = [p for p in path.split("/") if p]
    scopes: list[str] = []
    if len(parts) >= 2 and parts[0] == "accounts":
        account_id = parts[1]
        base = f"/accounts/{account_id}"
        # Always-safe read scope for the account itself.
        scopes.append(f"{base}/profile.read")
        # Writes based on what the PATCH body contains.
        if "profile" in body or "metadata" in body or "customerSupport" in body:
            scopes.append(f"{base}/profile.write")
        if "termsOfService" in body:
            # ToS acceptance is gated by the profile.write scope on the account.
            if f"{base}/profile.write" not in scopes:
                scopes.append(f"{base}/profile.write")
    if not scopes:
        # Fallback to generic scopes.
        scopes = ["/accounts.read", "/accounts.write"]
    return " ".join(scopes)
