"""Bounded, conservative serializer for OPTIONAL input/output capture.

No repr() or arbitrary __dict__ introspection: those often leak secrets.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from itertools import islice

_REDACT_PARTS = (
    "password", "secret", "token", "authorization", "apikey",
    "credential", "privatekey", "accesskey", "passphrase",
)


def _safe(value, *, depth: int, seen: set[int]):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:500] + ("…" if len(value) > 500 else "")
    if depth == 0:
        return "<max-depth>"
    if isinstance(value, (Mapping, list, tuple)):
        marker = id(value)
        if marker in seen:
            return "<cycle>"
        seen.add(marker)
        try:
            if isinstance(value, Mapping):
                result = {}
                for key, child in islice(value.items(), 20):
                    if not isinstance(key, str):
                        continue
                    normalized_key = key.lower().replace("_", "").replace("-", "")
                    result[key] = (
                        "<redacted>"
                        if any(part in normalized_key for part in _REDACT_PARTS)
                        else _safe(child, depth=depth - 1, seen=seen)
                    )
                return result
            return [_safe(child, depth=depth - 1, seen=seen) for child in value[:20]]
        finally:
            seen.remove(marker)
    return f"<{type(value).__name__}>"


def serialize(value, *, max_chars: int = 4000) -> str:
    """Return a string attribute with bounded size and conservative redaction.

    Structured fields with sensitive values in unrecognized key names, and
    secrets embedded in free text, cannot be automatically sanitized.
    """
    result = json.dumps(_safe(value, depth=4, seen=set()), ensure_ascii=False, allow_nan=False)
    if len(result) <= max_chars:
        return result
    return json.dumps({"truncated": True, "preview": result[:max(0, max_chars - 70)]}, ensure_ascii=False)
