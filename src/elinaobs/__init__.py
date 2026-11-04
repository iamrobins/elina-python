"""ElinaObs Python SDK: decorator first, framework agnostic, OTLP native."""
from .decorators import trace
from .runtime import flush, init, shutdown
from .types import ObservationType

__all__ = ["init", "trace", "flush", "shutdown", "ObservationType"]
__version__ = "0.1.0"
