import json
from typing import Any, Dict, List, Optional


def _extract_raw_text_from_exception(exc: Exception) -> Optional[str]:
    """Try to extract a JSON payload or text from the SDK exception."""
    try:
        raw = (
            getattr(exc, "body", None)
            or getattr(exc, "response", None)
            or (exc.args[0] if exc.args else None)
        )
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode("utf-8", errors="ignore")
        if isinstance(raw, str):
            return raw
        # For other objects, attempt a JSON dump
        try:
            return json.dumps(raw)
        except Exception:
            return str(raw)
    except Exception:
        return str(exc)


def _coerce_industries_from_raw(raw_text: str) -> Optional[List[Dict[str, Any]]]:
    """Parse raw JSON and try to coerce an industries list into a stable shape.

    Expected to map common fields present in some Moov responses like
    {'title','naics','sic','mcc'} -> {'displayName','industry','category'}.
    Returns None if coercion isn't possible.
    """
    if not raw_text:
        return None
    try:
        parsed = json.loads(raw_text)
    except Exception:
        return None

    items = parsed.get("industries") or parsed.get("data") or parsed
    if not isinstance(items, list):
        return None

    coerced: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        mapped = {
            "industry": it.get("mcc")
            or it.get("naics")
            or it.get("sic")
            or it.get("title"),
            "displayName": it.get("title") or it.get("displayName") or None,
            "category": it.get("sic") or it.get("naics") or it.get("category") or None,
            "raw": it,
        }
        coerced.append(mapped)
    return coerced
