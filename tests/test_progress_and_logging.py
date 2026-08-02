"""Long-running tools report progress, log through MCP, and stay off the event loop.

The gap this file pins: no tool took an MCP ``Context``. Two consequences, one
of them a live defect rather than a missing nicety:

* **Silence.** A render bounded by a 20-second subprocess budget produced no
  progress notification and no MCP log record. The JSONL audit trail on disk
  knew what happened; the operator driving the session did not.
* **Head-of-line blocking.** FastMCP calls a *sync* tool function inline on the
  event loop (``func_metadata.call_fn_with_arg_validation``: ``return fn(...)``
  when ``fn_is_async`` is false). Every tool here was sync, so one slow render
  froze the whole server — including the notifications that would have reported
  it.

The fix moves the blocking work to a worker thread and reports around it, so
these tests assert all three: the notifications, the log levels that mirror the
result, and the thread the work actually ran on.
"""
from __future__ import annotations

import threading

import anyio
import pytest

from frameforge_mcp import progress as progress_module
from frameforge_mcp.server import create_server


class RecordingContext:
    """A stand-in for ``mcp.server.fastmcp.Context`` that records what it was told."""

    def __init__(self):
        self.progress: list[tuple[float, float | None, str | None]] = []
        self.logs: list[tuple[str, str]] = []

    async def report_progress(self, progress, total=None, message=None):
        self.progress.append((progress, total, message))

    async def log(self, level, message, **_):
        self.logs.append((level, message))

    async def debug(self, message, **_):
        await self.log("debug", message)

    async def info(self, message, **_):
        await self.log("info", message)

    async def warning(self, message, **_):
        await self.log("warning", message)

    async def error(self, message, **_):
        await self.log("error", message)


# --------------------------------------------------------------------------- #
#  The helper: report around the work, never instead of it                     #
# --------------------------------------------------------------------------- #


def test_a_successful_call_brackets_the_work_with_progress():
    ctx = RecordingContext()

    result = anyio.run(
        progress_module.run_reported, ctx, "render_frameforge_yaml", lambda: {"ok": True}
    )

    assert result == {"ok": True}
    assert ctx.progress[0][0] == 0.0, "no progress emitted before the work started"
    assert ctx.progress[-1][0] == ctx.progress[-1][1], "final progress is not 100%"
    assert all(step[1] == 1.0 for step in ctx.progress), "progress reported without a total"


def test_a_successful_call_logs_start_and_completion_through_mcp():
    ctx = RecordingContext()

    anyio.run(progress_module.run_reported, ctx, "render_frameforge_yaml", lambda: {"ok": True})

    levels = [level for level, _ in ctx.logs]
    messages = " | ".join(message for _, message in ctx.logs)
    assert levels == ["info", "info"], ctx.logs
    assert "render_frameforge_yaml" in messages


def test_an_ok_false_envelope_is_logged_as_a_warning_not_a_success():
    """An expected failure is still a failure — the operator must see it as one."""
    ctx = RecordingContext()

    result = anyio.run(
        progress_module.run_reported,
        ctx,
        "propose_from_image",
        lambda: {"ok": False, "error": "no such file"},
    )

    assert result["ok"] is False
    assert ctx.logs[-1][0] == "warning", ctx.logs
    assert "no such file" in ctx.logs[-1][1]


def test_a_failed_render_is_logged_as_a_warning_through_its_content_wrapper():
    """Regression: the render family returns a CallToolResult, not a bare dict.

    ``_outcome`` read ``ok`` off the result directly, so every render tool —
    which wraps its envelope in a ``CallToolResult`` to carry the PNG as an
    image block — reported ``complete`` at ``info`` even when the render had
    failed. The operator watching the session saw a success.
    """
    from mcp.types import CallToolResult, TextContent

    ctx = RecordingContext()
    failed = CallToolResult(
        content=[TextContent(type="text", text="{}")],
        structuredContent={"ok": False, "error": "document does not validate"},
        isError=True,
    )

    anyio.run(progress_module.run_reported, ctx, "render_frameforge_yaml", lambda: failed)

    assert ctx.logs[-1][0] == "warning", ctx.logs
    assert "does not validate" in ctx.logs[-1][1]
    assert "failed" in ctx.progress[-1][2]


def test_a_successful_render_through_the_wrapper_still_reads_as_success():
    from mcp.types import CallToolResult, TextContent

    ctx = RecordingContext()
    good = CallToolResult(
        content=[TextContent(type="text", text="{}")],
        structuredContent={"ok": True},
        isError=False,
    )

    anyio.run(progress_module.run_reported, ctx, "render_frameforge_yaml", lambda: good)

    assert ctx.logs[-1][0] == "info"
    assert "complete" in ctx.logs[-1][1]


def test_a_raised_exception_is_logged_as_an_error_and_still_propagates():
    """Reporting must not swallow the exception the envelope layer expects to see."""
    ctx = RecordingContext()

    def boom():
        raise RuntimeError("engine exploded")

    with pytest.raises(RuntimeError, match="engine exploded"):
        anyio.run(progress_module.run_reported, ctx, "run_sdk_code", boom)

    assert ctx.logs[-1][0] == "error"
    assert "engine exploded" in ctx.logs[-1][1]


def test_progress_completes_even_when_the_work_fails():
    """A stuck progress bar is its own bug — the final notification is unconditional."""
    ctx = RecordingContext()

    def boom():
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        anyio.run(progress_module.run_reported, ctx, "run_sdk_code", boom)

    assert ctx.progress[-1][0] == ctx.progress[-1][1]


def test_the_work_runs_off_the_event_loop_thread():
    """The head-of-line-blocking fix: the blocking call must not run on the loop."""
    ctx = RecordingContext()
    loop_thread = {}
    work_thread = {}

    async def main():
        loop_thread["id"] = threading.get_ident()
        return await progress_module.run_reported(
            ctx, "run_sdk_code", lambda: work_thread.setdefault("id", threading.get_ident())
        )

    anyio.run(main)

    assert work_thread["id"] != loop_thread["id"], (
        "the tool body ran on the event loop — one slow render still blocks the server"
    )


def test_reporting_is_a_no_op_without_a_context():
    """Not every client sends a progress token; the tool must still work."""
    assert anyio.run(progress_module.run_reported, None, "list_fonts", lambda: {"ok": True}) == {
        "ok": True
    }


def test_a_context_that_cannot_notify_never_breaks_the_tool():
    """A client that rejects a notification must not turn a good render into a failure."""

    class BrokenContext(RecordingContext):
        async def report_progress(self, *args, **kwargs):
            raise RuntimeError("client closed the stream")

        async def log(self, *args, **kwargs):
            raise RuntimeError("client closed the stream")

    result = anyio.run(
        progress_module.run_reported, BrokenContext(), "render_frameforge_yaml", lambda: {"ok": True}
    )
    assert result == {"ok": True}


# --------------------------------------------------------------------------- #
#  The registered surface actually wires it up                                 #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def registered(tmp_path_factory):
    root = tmp_path_factory.mktemp("progress-sessions")
    server = create_server(session_root=root, structured_log_path=root / "log.jsonl")
    return {tool.name: tool for tool in server._tool_manager.list_tools()}


def test_every_tool_receives_the_mcp_context(registered):
    """FastMCP injects Context only when it can *find* the parameter.

    Detection goes through ``typing.get_type_hints``, which silently returns
    nothing if an annotation fails to resolve — so a wiring mistake here would
    disable progress reporting without any error at all.
    """
    blind = sorted(name for name, tool in registered.items() if tool.context_kwarg is None)
    assert not blind, f"tools that cannot receive a Context: {blind}"


def test_every_tool_is_async_so_the_loop_stays_free(registered):
    sync = sorted(name for name, tool in registered.items() if not tool.is_async)
    assert not sync, f"tools still executed inline on the event loop: {sync}"


def test_the_context_parameter_is_hidden_from_the_model(registered):
    """`ctx` is injected by the host — an agent must never be asked to supply it."""
    for name, tool in registered.items():
        assert "ctx" not in tool.parameters.get("properties", {}), (
            f"{name} advertises the injected context as a model-facing argument"
        )


def test_wiring_the_context_did_not_disturb_the_declared_arguments(registered):
    """Regression: the async wrapper must preserve each tool's real input schema."""
    render = registered["render_frameforge_yaml"].parameters["properties"]
    assert "yaml_text" in render
    assert "session_id" in render
    assert "max_pages" in render

    write = registered["write_sdk_client"].parameters["properties"]
    assert {"path", "code", "create", "append", "old_string", "new_string"} <= set(write)

    assert registered["render_frameforge_yaml"].parameters["required"] == ["yaml_text"]


def test_tool_descriptions_survive_the_wrapper(registered):
    """The docstring is the model's only account of what a tool does."""
    assert "deprecated" in (registered["list_deprecated_forms"].description or "").lower()
    assert "fontconfig" in (registered["list_fonts"].description or "").lower()
