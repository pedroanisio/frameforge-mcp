"""Run a blocking tool body off the event loop, reporting progress and logs to MCP.

Two problems are solved by the same wrapper, because they have the same cause.

**The server went silent under load.** FastMCP calls a synchronous tool function
inline on the event loop. Every tool in this server was synchronous, so a render
bounded by a 20-second subprocess budget held the loop for the whole run: no
other request could be served, and no notification could be flushed — including
the ones that would have said the render was still going. Moving the body to a
worker thread (:func:`anyio.to_thread.run_sync`) frees the loop.

**The operator could not see what the audit trail saw.** Every call is already
recorded to JSONL on disk (:mod:`frameforge_mcp.logging`), which is the right
answer for forensics and no answer at all for someone watching a session. The
same events are now mirrored to MCP's own logging + progress notifications, so
the client shows a live render rather than a stall.

PALS's Law applies to the reporting itself: this layer reports *what it can
observe* — that the call started, and how it ended. It does not synthesize
intermediate phase boundaries the server cannot see, because a progress bar
that invents its own milestones is a fabricated signal.
"""
from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from typing import Any, TypeVar

import anyio.to_thread

T = TypeVar("T")

try:  # pragma: no cover - `mcp` is a base dependency of this distribution
    from mcp.server.fastmcp import Context as _Context

    _CTX_ANNOTATION: Any = _Context | None
except ImportError:  # pragma: no cover - test doubles register plain callables
    _CTX_ANNOTATION = None

#: Progress is reported on a 0..1 scale: one notification before the work, one
#: after. The total is always sent — a progress notification without a total
#: renders as an indeterminate spinner in most clients.
_TOTAL = 1.0


async def _notify(call, *args, **kwargs) -> None:
    """Best-effort notification: a client that cannot receive one is not an error.

    A closed stream, an unsupported capability, or a client that simply never
    sent a progress token must never turn a successful render into a failure.
    The tool's real result is the contract; telemetry around it is advisory.
    """
    if call is None:
        return
    try:
        await call(*args, **kwargs)
    except Exception:
        return


async def _log(ctx: Any, level: str, message: str) -> None:
    if ctx is None:
        return
    await _notify(getattr(ctx, level, None), message)


async def _progress(ctx: Any, value: float, message: str) -> None:
    if ctx is None:
        return
    await _notify(getattr(ctx, "report_progress", None), value, _TOTAL, message)


def _outcome(result: Any) -> tuple[str, str]:
    """(log level, suffix) for a completed call, read off the shared envelope.

    An ``ok: false`` envelope is an *expected* failure — a missing lane, a bad
    path, a document that will not validate. It is still a failure, and logging
    it at ``info`` beside the successes is how an operator misses it.
    """
    if isinstance(result, dict) and result.get("ok") is False:
        detail = str(result.get("error") or "failed")
        return "warning", f"failed: {detail}"
    return "info", "complete"


async def run_reported(ctx: Any, tool: str, call: Callable[[], T]) -> T:
    """Run *call* in a worker thread, bracketing it with MCP progress + log records.

    ``ctx`` is the injected :class:`mcp.server.fastmcp.Context`, or ``None`` when
    the host did not supply one. The result — or the exception — of *call* is
    passed through untouched; this wrapper never converts one into the other,
    because the envelope layer above it (``server._enveloped``) is what decides
    which exceptions are expected.
    """
    await _log(ctx, "info", f"{tool}: started")
    await _progress(ctx, 0.0, f"{tool}: started")
    try:
        result = await anyio.to_thread.run_sync(call)
    except BaseException as exc:
        await _progress(ctx, _TOTAL, f"{tool}: failed")
        await _log(ctx, "error", f"{tool}: raised {type(exc).__name__}: {exc}")
        raise
    level, suffix = _outcome(result)
    await _progress(ctx, _TOTAL, f"{tool}: {suffix}")
    await _log(ctx, level, f"{tool}: {suffix}")
    return result


def offload(
    fn: Callable[..., Any], tool: str, *, result_model: Any | None = None
) -> Callable[..., Any]:
    """Wrap a synchronous tool body as an async, Context-receiving, reported tool.

    The tool functions stay ordinary synchronous code — that is what keeps them
    readable and directly callable from the tests and the ``live`` web UI. This
    adapter is what FastMCP actually registers.

    Two details make it work rather than merely look like it works:

    * **Annotations are resolved eagerly.** ``server.py`` uses
      ``from __future__ import annotations``, so its parameter annotations are
      strings that only resolve against *its* module globals. The wrapper is
      defined here, so a lazily-resolved hint would be evaluated in the wrong
      namespace — ``typing.get_type_hints`` would raise, FastMCP's context
      detection would silently give up, and progress reporting would vanish with
      no error anywhere. Resolving with ``include_extras=True`` also preserves
      the ``Annotated[..., Field(description=...)]`` metadata that gives every
      parameter its model-facing description.
    * **The signature is rebuilt, not copied.** ``functools.wraps`` would leave
      ``__wrapped__`` pointing at a function with no ``ctx`` parameter, so the
      injected argument would fail validation.

    ``result_model`` becomes the wrapper's return annotation, which is how
    FastMCP derives the tool's published ``outputSchema`` — and, because it also
    builds the matching output *model*, how it comes to validate every result's
    ``structuredContent`` before it leaves the server. Pass ``None`` for a tool
    that returns prose rather than an envelope.
    """
    signature = inspect.signature(fn)
    try:
        resolved = typing.get_type_hints(fn, include_extras=True)
    except Exception:
        resolved = {}

    parameters = [
        parameter.replace(annotation=resolved.get(name, parameter.annotation))
        for name, parameter in signature.parameters.items()
    ]
    annotations = {name: hint for name, hint in resolved.items()}

    if _CTX_ANNOTATION is not None:
        parameters.append(
            inspect.Parameter(
                "ctx",
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=_CTX_ANNOTATION,
            )
        )
        annotations["ctx"] = _CTX_ANNOTATION

    # The declared output contract. Absent (rather than `Any`) for a prose tool:
    # FastMCP publishes an outputSchema for anything it can model, and a schema
    # claiming structure over a plain string would misdescribe the result.
    return_annotation: Any = inspect.Signature.empty
    if result_model is not None:
        annotations["return"] = result_model
        return_annotation = result_model
    else:
        annotations.pop("return", None)

    async def wrapper(*args: Any, ctx: Any = None, **kwargs: Any) -> Any:
        return await run_reported(ctx, tool, lambda: fn(*args, **kwargs))

    wrapper.__name__ = fn.__name__
    wrapper.__qualname__ = fn.__qualname__
    wrapper.__module__ = fn.__module__
    wrapper.__doc__ = fn.__doc__
    wrapper.__signature__ = signature.replace(  # type: ignore[attr-defined]
        parameters=parameters, return_annotation=return_annotation
    )
    wrapper.__annotations__ = annotations
    # The undecorated body, so tests and in-process callers can reach it directly.
    wrapper.__frameforge_sync__ = fn  # type: ignore[attr-defined]
    return wrapper


__all__ = ["offload", "run_reported"]
