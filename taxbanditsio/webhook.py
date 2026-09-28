import json
import base64, hmac, hashlib
from django.http import HttpResponse
from ipaddress import ip_address, ip_network
from datetime import datetime, timezone
from django.conf import settings
from django.utils.timezone import now

# ---- IP allow-list ---------------------------------------------------------

def _parse_allowed_networks():
    nets = []
    for item in getattr(settings, "TAXBANDITS_ALLOWED_IPS", []):
        try:
            if "/" in item:      # CIDR range
                nets.append(ip_network(item, strict=False))
            else:                # single IP
                nets.append(ip_network(f"{item}/32"))
        except ValueError:
            # bad entry -> skip; you can log if you want
            pass
    return nets

_ALLOWED_NETS = _parse_allowed_networks()

def _client_ip(request) -> str:
    if getattr(settings, "TAXBANDITS_TRUST_XFF", False):
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            return xff.split(",")[0].strip()
    return (request.META.get("REMOTE_ADDR") or "").split(",")[0].strip()

def ip_is_allowed(request) -> bool:
    if not _ALLOWED_NETS:  # if empty, allow all (simple default)
        return True
    ip_str = _client_ip(request)
    try:
        ip_obj = ip_address(ip_str)
    except ValueError:
        return False
    return any(ip_obj in net for net in _ALLOWED_NETS)

# ---- Signature / timestamp --------------------------------------------------

SIG_HEADER = "Signature"
TS_HEADER  = "TimeStamp"

def _b64_hmac_sha256(key: bytes, msg: bytes) -> str:
    mac = hmac.new(key, msg, hashlib.sha256).digest()
    return base64.b64encode(mac).decode("ascii")

def expected_signature(timestamp: str) -> str:
    """
    Per TaxBandits docs:
    expected = base64( HMAC_SHA256( ClientSecret,  ClientId + "\n" + TimeStamp ) )
    """
    msg = f"{settings.TAXBANDITS_CLIENT_ID}\n{timestamp}".encode("utf-8")
    return _b64_hmac_sha256(settings.TAXBANDITS_CLIENT_SECRET.encode("utf-8"), msg)

def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a or "", b or "")

def timestamp_fresh(timestamp: str, max_skew_seconds: int = None) -> bool:
    max_skew_seconds = max_skew_seconds or getattr(settings, "TAXBANDITS_MAX_SKEW_SECONDS", 600)
    try:
        # most implementations send unix seconds; if your account differs, this will still pass (see except)
        t = int(timestamp)
        event_time = datetime.fromtimestamp(t, tz=timezone.utc)
        return abs((now() - event_time).total_seconds()) <= max_skew_seconds
    except Exception:
        # if format not int, skip freshness check rather than failing
        return True


# ---------- mixin for class-based views ----------
class TaxBanditsGuardMixin:
    def _validate_and_get_payload(self, request):
        if not ip_is_allowed(request): return HttpResponse(status=403)
        try:
            raw = request.body or b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return HttpResponse(status=400)
        signature = request.headers.get(SIG_HEADER) or request.META.get("HTTP_SIGNATURE")
        timestamp = request.headers.get(TS_HEADER)  or request.META.get("HTTP_TIMESTAMP")
        if not signature or not timestamp: return HttpResponse(status=401)
        if not constant_time_equals(signature, expected_signature(timestamp)): return HttpResponse(status=401)
        if not timestamp_fresh(timestamp): return HttpResponse(status=409)
        return payload