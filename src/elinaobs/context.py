"""Elina capture selection, NOT a replacement for OTel parent context."""
from contextvars import ContextVar

# Inherited by normal sync nesting and asyncio tasks.
# The OTel context still owns trace and parent/span IDs.
capture_active: ContextVar[bool] = ContextVar("elinaobs_capture_active", default=False)
