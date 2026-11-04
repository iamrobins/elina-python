"""Framework-agnostic decorator for ordinary sync and async Python functions."""
from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar, cast, overload

from opentelemetry import trace as otel_trace

from .context import capture_active
from .runtime import get_config
from .serialization import serialize
from .types import OBSERVATION_TYPES, ObservationType

F = TypeVar("F", bound=Callable[..., Any])


@overload
def trace(func: F, /) -> F: ...


@overload
def trace(*, name: str | None = None, as_type: ObservationType = "span") -> Callable[[F], F]: ...


def trace(
    func: F | None = None,
    /,
    *,
    name: str | None = None,
    as_type: ObservationType = "span",
) -> F | Callable[[F], F]:
    """Time a Python function and attach any OTel-instrumented children.

    This v0.1 deliberately rejects generator functions. Their lifetime is
    iteration, not function invocation, so naïve wrappers would lie.
    """
    if as_type not in OBSERVATION_TYPES:
        raise ValueError(f"Unknown observation type: {as_type!r}")
    if name is not None and not name.strip():
        raise ValueError("name must be nonempty")

    def decorate(fn: F) -> F:
        if inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn):
            raise TypeError("@trace does not support generator functions in v0.1")
        label = name or fn.__qualname__

        def attach_input(span, args, kwargs, settings):
            if not settings.capture_input or not span.is_recording():
                return
            try:
                bound = inspect.signature(fn).bind_partial(*args, **kwargs)
                value = dict(bound.arguments)
                value.pop("self", None)
                value.pop("cls", None)
                span.set_attribute("elinaobs.input", serialize(value, max_chars=settings.max_content_chars))
            except Exception:  # instrumentation must not break the application
                pass

        def attach_output(span, value, settings):
            if not settings.capture_output or not span.is_recording():
                return
            try:
                span.set_attribute("elinaobs.output", serialize(value, max_chars=settings.max_content_chars))
            except Exception:
                pass

        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                settings = get_config()
                token = capture_active.set(True)
                try:
                    tracer = otel_trace.get_tracer("elinaobs.sdk", "0.1.0")
                    with tracer.start_as_current_span(
                        label, attributes={"elinaobs.observation.type": as_type}
                    ) as span:
                        attach_input(span, args, kwargs, settings)
                        output = await fn(*args, **kwargs)
                        attach_output(span, output, settings)
                        return output
                finally:
                    capture_active.reset(token)
            return cast(F, async_wrapper)

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            settings = get_config()
            token = capture_active.set(True)
            try:
                tracer = otel_trace.get_tracer("elinaobs.sdk", "0.1.0")
                with tracer.start_as_current_span(
                    label, attributes={"elinaobs.observation.type": as_type}
                ) as span:
                    attach_input(span, args, kwargs, settings)
                    output = fn(*args, **kwargs)
                    attach_output(span, output, settings)
                    return output
            finally:
                capture_active.reset(token)
        return cast(F, sync_wrapper)

    if func is not None:
        return decorate(func)
    return decorate
