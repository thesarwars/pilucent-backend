from datetime import datetime
from enum import Enum


def _convert_moov_result(obj):
    """Robust converter for Moov SDK responses.

    Handles:
    - list-of-pairs -> dict
    - nested lists -> lists
    - dicts -> dicts
    - objects with __dict__ / .to_dict() / .dict()
    - datetime -> ISO string
    - Enum -> .value
    - fallback -> str(obj)
    """
    # simple scalars
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, datetime):
        return obj.isoformat()

    if isinstance(obj, Enum):
        return obj.value

    # lists: detect list-of-pairs (key, value)
    if isinstance(obj, list):

        def is_pair(x):
            try:
                return (
                    isinstance(x, (list, tuple))
                    and len(x) == 2
                    and isinstance(x[0], str)
                )
            except Exception:
                return False

        if all(is_pair(el) for el in obj):
            out = {}
            for key, value in obj:
                out[str(key)] = _convert_moov_result(value)
            return out
        # otherwise it's a normal list
        return [_convert_moov_result(el) for el in obj]

    if isinstance(obj, dict):
        return {k: _convert_moov_result(v) for k, v in obj.items()}

    # objects: try dataclass-like or SDK model objects
    try:
        # prefer explicit conversion methods if present
        if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
            return _convert_moov_result(obj.to_dict())
        if hasattr(obj, "dict") and callable(getattr(obj, "dict")):
            return _convert_moov_result(obj.dict())

        if hasattr(obj, "__dict__"):
            result = {}
            for k, v in vars(obj).items():
                if k.startswith("_"):
                    continue
                result[k] = _convert_moov_result(v)
            return result
    except Exception:
        pass

    # fallback
    try:
        return str(obj)
    except Exception:
        return None
