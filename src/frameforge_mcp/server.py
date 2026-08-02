"""FrameForge MCP server — composition root and backward-compatible facade.

The server's behaviour is split across focused modules (``config``, ``sessions``,
``execution``, ``pipeline``, ``sources``, ``usecases``, ``transport``, ``logging``,
``results``, ``security``, ``discovery``, ``clients``). This module wires them into a
FastMCP server via :func:`create_server` and re-exports the public + historically
module-level names so ``from frameforge_mcp.server import ...`` keeps working for the
live server, the package ``__init__``, and the test suite.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

# -- names create_server uses directly ------------------------------------------
from frameforge_mcp.config import DEFAULT_TIMEOUT_SECONDS, max_result_chars
from frameforge_mcp.descriptions import (
    _DESC_CLIENT_PATH,
    _DESC_COACH_MODES,
    _DESC_COACH_PAINT,
    _DESC_COACH_STYLE,
    _DESC_DETECTORS,
    _DESC_FONT_CLOSURE,
    _DESC_FONT_GENERICS,
    _DESC_MAX_PAGES,
    _DESC_MIGRATE_APPLY,
    _DESC_MIGRATE_YAML,
    _DESC_PAGES,
    _DESC_RASTER,
    _DESC_REAL_METRICS,
    _DESC_REGION_METHOD,
    _DESC_REGION_TUNABLES,
    _DESC_SCALE,
    _DESC_SESSION_ID,
    _DESC_SIGN,
    _DESC_SIGNED_AT,
    _DESC_SILHOUETTE,
    _DESC_TIMEOUT,
    _DESC_VLM_IMAGE,
    _DESC_VLM_QUESTION,
    _DESC_VLM_STAGE,
    _DESC_TO,
    _DESC_TOPIC,
)
from frameforge_mcp.guide import FRAMEFORGE_GUIDE
from frameforge_mcp.live_discovery import (
    live_describe_capabilities as _live_describe_capabilities,
    live_guide as _live_guide,
)
from frameforge_mcp.paths import _repo_root, _session_root
from frameforge_mcp.sessions import (
    read_session_resource,
    session_resource_endpoint_bytes,
    session_resource_endpoint_text,
)
from frameforge_mcp.logging import _logged_call, _structured_log_path
from frameforge_mcp.envelope import ToolEnvelope
from frameforge_mcp.progress import offload
from frameforge_mcp.security import INPUT_ROOTS_HINT
from frameforge_mcp.tool_facts import tool_kwargs
from frameforge_mcp.transport import _maybe_call_tool_result
from frameforge_mcp.util import _positive_int

# The tool wrappers call the use cases under aliases so the inner FastMCP-decorated
# functions can keep the public tool names without shadowing the use case (this is
# what the old ``globals()[...]`` indirection worked around — now made explicit).
from frameforge_mcp.clients import (
    list_sdk_clients as _uc_list_sdk_clients,
    read_sdk_client as _uc_read_sdk_client,
)
from frameforge_mcp.sessions import (
    cleanup_sessions as _uc_cleanup_sessions,
    list_sessions as _uc_list_sessions,
)
from frameforge_mcp.discovery import list_fonts as _uc_list_fonts
from frameforge_mcp.usecases import (
    fit_text as _uc_fit_text,
    write_or_edit_client as _uc_write_or_edit,
    compare_images as _uc_compare_images,
    construct_vectors as _uc_construct_vectors,
    detect_regions as _uc_detect_regions,
    diff_renders as _uc_diff_renders,
    fit_primitives as _uc_fit_primitives,
    match_font as _uc_match_font,
    map_coordinates as _uc_map_coordinates,
    mark_points as _uc_mark_points,
    measure_image as _uc_measure_image,
    overlay_images as _uc_overlay_images,
    refine_reconstruction as _uc_refine_reconstruction,
    score_reconstruction as _uc_score_reconstruction,
    vectorize_image as _uc_vectorize_image,
    workspace as _uc_workspace,
    coach_vectorize as _uc_coach_vectorize,
    describe_render as _uc_describe_render,
    propose_from_document as _uc_propose_from_document,
    propose_from_image as _uc_propose_from_image,
    propose_from_svg as _uc_propose_from_svg,
    render_frameforge_yaml as _uc_render_frameforge_yaml,
    design_audit as _uc_design_audit,
    list_deprecated_forms as _uc_list_deprecated_forms,
    migrate_deprecated_forms as _uc_migrate_deprecated_forms,
    run_sdk_client as _uc_run_sdk_client,
    run_sdk_code as _uc_run_sdk_code,
)

# -- backward-compatible re-exports ---------------------------------------------
# Re-exported (redundant-alias form marks the intent) so ``from
# frameforge_mcp.server import X`` and ``server.X`` keep resolving for the live
# server, the package __init__, and the test suite. Not used inside this module.
from frameforge_mcp.config import (
    STRUCTURED_LOG_MAX_FIELD_CHARS as STRUCTURED_LOG_MAX_FIELD_CHARS,
    TRANSPORT_STREAM_MAX_CHARS as TRANSPORT_STREAM_MAX_CHARS,
)
from frameforge_mcp.paths import (
    get_default_repo_root as get_default_repo_root,
    get_default_session_root as get_default_session_root,
)
from frameforge_mcp.clients import (
    list_sdk_clients as list_sdk_clients,
    read_sdk_client as read_sdk_client,
    write_sdk_client as write_sdk_client,
)
from frameforge_mcp.sessions import (
    cleanup_sessions as cleanup_sessions,
    list_sessions as list_sessions,
)
from frameforge_mcp.usecases import (
    fit_text as fit_text,
    list_deprecated_forms as list_deprecated_forms,
    migrate_deprecated_forms as migrate_deprecated_forms,
    compare_images as compare_images,
    construct_vectors as construct_vectors,
    detect_regions as detect_regions,
    diff_renders as diff_renders,
    fit_primitives as fit_primitives,
    match_font as match_font,
    map_coordinates as map_coordinates,
    mark_points as mark_points,
    measure_image as measure_image,
    overlay_images as overlay_images,
    score_reconstruction as score_reconstruction,
    vectorize_image as vectorize_image,
    workspace as workspace,
    coach_vectorize as coach_vectorize,
    describe_render as describe_render,
    propose_from_document as propose_from_document,
    propose_from_image as propose_from_image,
    propose_from_svg as propose_from_svg,
    render_frameforge_yaml as render_frameforge_yaml,
    design_audit as design_audit,
    run_sdk_client as run_sdk_client,
    run_sdk_code as run_sdk_code,
)
from frameforge_mcp.transport import (
    mcp_content_blocks as mcp_content_blocks,
    _clamp_stream as _clamp_stream,
    _max_inline_images as _max_inline_images,
)
from frameforge_mcp.logging import _append_structured_log as _append_structured_log
from frameforge_mcp.execution import _subprocess_env as _subprocess_env
from frameforge_mcp.discovery import (
    describe_capabilities as describe_capabilities,
    list_fonts as list_fonts,
    _frameforge_yaml_snapshot as _frameforge_yaml_snapshot,
    _new_generated_yaml as _new_generated_yaml,
)


# --------------------------------------------------------------------------- #
#  Tool error envelope + result shaping                                       #
# --------------------------------------------------------------------------- #


def _tool_failure_hint(tool: str, exc: BaseException) -> str | None:
    """An actionable next step for the common expected tool failures."""
    message = str(exc)
    if isinstance(exc, SyntaxError):
        return "the client code must be valid Python — fix the syntax error and retry"
    if isinstance(exc, FileNotFoundError):
        if tool in ("read_sdk_client", "write_sdk_client", "run_sdk_client"):
            return (
                "call list_sdk_clients to see the editable client files "
                "(its allowed_roots field names the writable directories)"
            )
        if tool == "get_session_resource":
            return (
                "call list_sessions to see which sessions exist; every render tool resets "
                "page-*.svg/p*.png in its session, so only the LAST call's artifacts remain"
            )
        return (
            "check the path — image arguments accept a filesystem path or a "
            "frameforge://session/<id>/page/<n>.png URI"
        )
    if "allowed SDK client roots" in message:
        return (
            "call list_sdk_clients — its allowed_roots field lists the writable directories "
            "(configure with FRAMEFORGE_MCP_EDIT_ROOTS)"
        )
    if "session_id" in message:
        return (
            "session ids must match [A-Za-z0-9][A-Za-z0-9_.-]{0,79}; omit session_id for the "
            "default 'session'"
        )
    if "FRAMEFORGE_MCP_INPUT_ROOTS" in message or "allowed input roots" in message:
        return INPUT_ROOTS_HINT
    if "resource URI" in message or "frameforge://" in message:
        return (
            "session resource URIs look like frameforge://session/<id>/ + document.yaml | "
            "document.pdf | page/<n>.svg | page/<n>.png | diagnostics.json | workspace.json"
        )
    return None


def _error_envelope(tool: str, exc: BaseException) -> dict[str, Any]:
    """The shared structured-failure shape every tool returns instead of raising."""
    envelope: dict[str, Any] = {
        "ok": False,
        "error": str(exc) or type(exc).__name__,
        "error_type": type(exc).__name__,
        "renders": [],
        "resources": [],
    }
    hint = _tool_failure_hint(tool, exc)
    if hint:
        envelope["hint"] = hint
    return envelope


def _budget_result(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    """Refuse to transport a result larger than the per-result budget.

    Clients enforce token caps by REJECTING an oversized tool result wholesale
    (the transfer is paid, the payload is lost). The server pre-empts that:
    an over-budget result is replaced by a small structured summary — sizes of
    the offending keys, every small scalar salvaged, and the remediation —
    so the failure stays actionable in one round-trip.
    """
    budget = max_result_chars()
    serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if len(serialized) <= budget:
        return result

    sizes = sorted(
        (
            (key, len(json.dumps(value, ensure_ascii=False, default=str)))
            for key, value in result.items()
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    kept: dict[str, Any] = {}
    for key, value in result.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            if not isinstance(value, str) or len(value) <= 400:
                kept[key] = value
        if len(kept) >= 12:
            break
    return {
        "ok": False,
        "error": (
            f"{tool} result is {len(serialized)} chars — over the {budget}-char "
            "transport budget (FRAMEFORGE_MCP_MAX_RESULT_CHARS); refusing to ship a "
            "payload the client would reject"
        ),
        "error_type": "ResultBudgetExceeded",
        "chars": len(serialized),
        "budget": budget,
        "oversized_keys": [
            {"key": key, "chars": chars} for key, chars in sizes[:5]
        ],
        "kept": kept,
        "hint": (
            "narrow the request — get_session_resource supports offset/max_chars "
            "pagination and query='/json/pointer'; render tools accept pages=...; "
            "artifacts are always readable on disk at their reported path — or raise "
            "FRAMEFORGE_MCP_MAX_RESULT_CHARS for this deployment"
        ),
        "renders": [],
        "resources": [],
    }


def _enveloped(tool: str, call):
    """Run a use case, lowering expected input/filesystem failures into the envelope.

    Unexpected exceptions still raise (and are logged) — masking a genuine bug as
    an input error would hide it from the operator (fix root causes, PALS's Law).
    Successful dict results pass through the transport budget (`_budget_result`).
    """
    try:
        result = call()
    except (ValueError, OSError, SyntaxError) as exc:
        return _error_envelope(tool, exc)
    if isinstance(result, dict):
        return _budget_result(tool, result)
    return result


def _logged_enveloped_call(log_path: Path, tool: str, instruction: dict[str, Any], call):
    """`_logged_call` with the expected-failure envelope applied to the call.

    The log then records the envelope the client actually received, not a raise.
    """
    return _logged_call(log_path, tool, instruction, lambda: _enveloped(tool, call))


def _plain_tool_result(result: Any):
    """CallToolResult for dict-returning tools: full JSON text + a real isError flag.

    The render tools go through :func:`_maybe_call_tool_result` (image blocks +
    summary); the plain dict tools previously returned raw dicts, so ``isError``
    was never meaningful for them. The full JSON stays the text block (nothing
    like ``code`` may be summarized away). Without the ``mcp`` package the dict
    passes through unchanged, exactly like ``_maybe_call_tool_result``.
    """
    if not isinstance(result, dict):
        return result
    try:
        from mcp.types import CallToolResult, TextContent
    except ImportError:
        return result
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
            )
        ],
        structuredContent=result,
        isError=result.get("ok", True) is False,
    )


def _registered_tool_names(server: Any) -> list[str]:
    """The live tool names, from FastMCP's manager or a test double's registry."""
    manager = getattr(server, "_tool_manager", None)
    if manager is not None:
        try:
            return sorted(tool.name for tool in manager.list_tools())
        except (AttributeError, TypeError):
            pass
    tools = getattr(server, "tools", None)
    if isinstance(tools, dict):
        return sorted(tools)
    return []


def create_server(
    *,
    session_root: str | Path | None = None,
    repo_root: str | Path | None = None,
    edit_roots: str | list[str] | tuple[str, ...] | None = None,
    structured_log_path: str | Path | None = None,
    fastmcp_cls: Any | None = None,
):
    """Create the FastMCP server exposing the FrameForge feedback tools."""
    if fastmcp_cls is None:
        try:
            from mcp.server.fastmcp import FastMCP as fastmcp_cls
        except ImportError as exc:
            raise RuntimeError(
                "The FrameForge MCP server requires the `mcp` SDK, which is a BASE "
                "dependency of this distribution — if it is missing, the install is "
                "incomplete rather than missing an optional lane. Repair it with "
                "`uv sync` (checkout) or `pip install frameforge-mcp`."
            ) from exc

    root = _session_root(session_root)
    repo = _repo_root(repo_root)
    log_path = _structured_log_path(root, structured_log_path)
    server = fastmcp_cls(
        "FrameForge",
        instructions=(
            # A CONNECTION PREAMBLE, not a manual. It is sent to every client on
            # every connection, before the agent has asked for anything, so it
            # buys only what an agent cannot recover on its own: the loop, the
            # rules whose violation is silent, and where the real reference is.
            # The SDK tour that used to live here is served on demand by
            # `get_guide` / the `frameforge_guide` prompt. Keeping it short is
            # also a security posture: instructions and tool descriptions are
            # injected verbatim into the model's context.
            "FrameForge is an agent-native visual-authoring substrate: author documents "
            "with the Python SDK, this server validates + renders them, and you verify "
            "against the rendered pixels.\n\n"
            "START HERE\n"
            "• describe_capabilities() — the capability index. Topics: `sdk`, `tools` "
            "(what each tool does to your environment), `envelope` (the result shape), "
            "`security` (which paths are readable), `backends` (which optional lanes "
            "this server has), plus any type name (`rect`, `paragraph`) for its schema. "
            "Look fields up here instead of iterating on validation errors.\n"
            "• get_guide() — the full SDK + workflow reference (also the "
            "`frameforge_guide` prompt, for clients that surface prompts).\n\n"
            "RULES WHOSE VIOLATION IS SILENT\n"
            "• Fonts: call list_fonts BEFORE choosing a font_family. An unresolvable "
            "family is SUBSTITUTED without an error and collapses the rendered type.\n"
            "• Deprecated forms: if a document is rejected for a `stroke` or `size` key, "
            "run list_deprecated_forms / migrate_deprecated_forms FIRST. Both spellings "
            "were removed by the contract, so such a document can never reach a render, "
            "and the rewrite is mechanical.\n"
            "• Typed diagnostics ride on every render result — `diagnostics.overflow` "
            "(clipped/spilling layout), `diagnostics.legibility` (WCAG contrast, type "
            "below the legible floor), `diagnostics.paint` (ink the document declared "
            "that the render did not produce). An invisible shape and an unreadable "
            "page are the defects a screenshot cannot show you: read the signals.\n"
            "• A tool whose optional lane is absent returns ok:false with the install "
            "command in `hint` — it is UNINSTALLED, not broken. Install it rather than "
            "working around it.\n\n"
            "CONTRACTS\n"
            "• Every tool result carries `ok`; branch on it first. Expected failures are "
            "ok:false envelopes with `error` and an actionable `hint`, never exceptions. "
            "Schema: describe_capabilities(topic='envelope').\n"
            "• Every tool declares whether it is read-only, destructive, idempotent, and "
            "open-world, as MCP annotations and via describe_capabilities(topic='tools'). "
            "Renders RESET their session's previous pages.\n"
            "• File inputs are confined to the session root, working directory, and "
            "repository unless FRAMEFORGE_MCP_INPUT_ROOTS says otherwise.\n"
            "• Artifacts live at frameforge://session/<id>/... (document.yaml, "
            "page/<n>.svg, page/<n>.png, diagnostics.json, workspace.json).\n\n"
            "PALS's LAW: all CV/VLM output is unverified by default — verify every "
            "result against the rendered PNG, never the YAML alone."
        ),
    )

    def _reporting_tool(name: str, *, structured: bool = True):
        """Register a synchronous tool body as an async, reported, annotated MCP tool.

        One registrar instead of 35 hand-written decorator argument lists. It
        carries the three declarations a bare ``@server.tool()`` left unstated:

        * the environmental contract from :mod:`frameforge_mcp.tool_facts`, so a
          host can gate approval on read-only vs destructive;
        * the offload to a worker thread with progress + MCP log notifications,
          so a slow render neither blocks the event loop nor goes silent;
        * the result contract from :mod:`frameforge_mcp.envelope`, published as
          ``outputSchema`` and enforced by FastMCP on every call.

        ``structured=False`` is for a tool that returns prose instead of an
        envelope — currently only ``get_guide``.
        """
        def decorator(fn):
            wrapped = offload(fn, name, result_model=ToolEnvelope if structured else None)
            return server.tool(**tool_kwargs(name))(wrapped)

        return decorator

    @_reporting_tool("list_deprecated_forms")
    def list_deprecated_forms():
        """List every DEPRECATED FrameForge form and the current spelling that replaces it.

        Read this before hand-fixing a document that will not validate. Branch on
        `valid_at_head`: a `legacy-key` still parses, a `removed-form` does not.
        `fix: automatic` means `migrate_deprecated_forms` handles it for you.
        """
        return _plain_tool_result(_logged_call(
            log_path,
            "list_deprecated_forms",
            {},
            lambda: _enveloped("list_deprecated_forms", _uc_list_deprecated_forms),
        ))

    @_reporting_tool("migrate_deprecated_forms")
    def migrate_deprecated_forms(
        yaml_text: Annotated[str, Field(description=_DESC_MIGRATE_YAML)],
        apply: Annotated[bool, Field(description=_DESC_MIGRATE_APPLY)] = False,
    ):
        """Report — and optionally rewrite — deprecated forms in a FrameForge document.

        Run this FIRST when a document is rejected for a `stroke` or `size` key:
        both were removed by the contract, so such a document can never reach
        `render_frameforge_yaml`, and the rewrite is mechanical. Reports only by
        default; pass `apply: true` for `migrated_yaml`. Never renders, never
        writes to a session.
        """
        return _plain_tool_result(_logged_call(
            log_path,
            "migrate_deprecated_forms",
            {"apply": apply},
            lambda: _enveloped(
                "migrate_deprecated_forms",
                lambda: _uc_migrate_deprecated_forms(yaml_text, apply=apply),
            ),
        ))

    @_reporting_tool("list_sdk_clients")
    def list_sdk_clients():
        """List editable Python SDK clients under the configured safe roots."""
        return _plain_tool_result(_logged_call(
            log_path,
            "list_sdk_clients",
            {},
            lambda: _enveloped(
                "list_sdk_clients",
                lambda: _uc_list_sdk_clients(repo_root=repo, edit_roots=edit_roots),
            ),
        ))

    @_reporting_tool("read_sdk_client")
    def read_sdk_client(
        path: Annotated[str, Field(description=_DESC_CLIENT_PATH)],
    ):
        """Read an editable Python SDK client file."""
        return _plain_tool_result(_logged_call(
            log_path,
            "read_sdk_client",
            {"path": path},
            lambda: _enveloped(
                "read_sdk_client",
                lambda: _uc_read_sdk_client(path, repo_root=repo, edit_roots=edit_roots),
            ),
        ))

    @_reporting_tool("write_sdk_client")
    def write_sdk_client(
        path: Annotated[str, Field(description=_DESC_CLIENT_PATH)],
        code: Annotated[
            str | None,
            Field(description="Full new contents of the SDK client file (replaces the file). Omit "
                              "when using old_string/new_string. Capped at 2,000,000 bytes; for a "
                              "file near/over your client's per-argument transport limit, use an "
                              "anchored edit or append=true chunking instead of one giant `code`."),
        ] = None,
        create: Annotated[
            bool, Field(description="Allow creating the file when it does not yet exist; false requires an existing file.")
        ] = False,
        append: Annotated[
            bool, Field(description="Append `code` to the existing file (created if absent) — write a large client in chunks under the per-argument transport limit."),
        ] = False,
        allow_partial: Annotated[
            bool, Field(description="Skip the compile check for a not-yet-complete chunk; set it on every append chunk except the last."),
        ] = False,
        old_string: Annotated[
            str | None,
            Field(description="Anchored edit: the exact text to replace. Must match the current file exactly once (extend with surrounding lines until unique). Use with new_string instead of `code`."),
        ] = None,
        new_string: Annotated[
            str | None,
            Field(description="Anchored edit: the replacement text for old_string."),
        ] = None,
    ):
        """Replace, create, anchored-edit, or chunk-append an editable Python SDK client file.

        Modes: full replace (``code``); anchored edit (``old_string`` +
        ``new_string`` — exact-match single-occurrence, so iterating on a large
        client does not re-transmit it); or chunked append (``append=True`` with
        ``allow_partial=True`` on every chunk except the last) for files larger
        than the client's per-argument transport limit.
        """
        def _meta(s):
            return None if s is None else f"<{len(s)} chars>"

        return _plain_tool_result(_logged_call(
            log_path,
            "write_sdk_client",
            {"path": path, "code": _meta(code), "create": create, "append": append,
             "allow_partial": allow_partial, "old_string": _meta(old_string),
             "new_string": _meta(new_string)},
            lambda: _enveloped("write_sdk_client", lambda: _uc_write_or_edit(
                path, code=code, create=create, append=append, allow_partial=allow_partial,
                old_string=old_string, new_string=new_string, repo_root=repo, edit_roots=edit_roots)),
        ))

    @_reporting_tool("run_sdk_client")
    def run_sdk_client(
        path: Annotated[str, Field(description=_DESC_CLIENT_PATH)],
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
        timeout_seconds: Annotated[int, Field(description=_DESC_TIMEOUT)] = DEFAULT_TIMEOUT_SECONDS,
        max_pages: Annotated[int, Field(description=_DESC_MAX_PAGES)] = 3,
        raster_png: Annotated[bool, Field(description=_DESC_RASTER)] = True,
        invoke_main: Annotated[
            bool,
            Field(description="Execute the client as __main__ (runs its `if __name__ == '__main__'` block) instead of importing it."),
        ] = False,
        pages: Annotated[str | None, Field(description=_DESC_PAGES)] = None,
        sign: Annotated[bool, Field(description=_DESC_SIGN)] = False,
        signed_at: Annotated[str | None, Field(description=_DESC_SIGNED_AT)] = None,
        silhouette: Annotated[bool, Field(description=_DESC_SILHOUETTE)] = False,
        to: Annotated[str, Field(description=_DESC_TO)] = "png",
        scale: Annotated[float, Field(description=_DESC_SCALE)] = 1.0,
        real_metrics: Annotated[bool | str, Field(description=_DESC_REAL_METRICS)] = "auto",
        font_closure: Annotated[str | None, Field(description=_DESC_FONT_CLOSURE)] = None,
        font_generics: Annotated[
            dict[str, str] | None, Field(description=_DESC_FONT_GENERICS)
        ] = None,
        reference: Annotated[
            str | None,
            Field(description="Optional reference image (path, frameforge:// URI, or data:image URI) to diff the rendered page 1 against: the result gains reference_diff with per-object ghost vectors — each authored object's displacement toward its best match in the reference — so corrections are typed from numbers instead of eyeballed off an overlay."),
        ] = None,

        publish: Annotated[
            bool,
            Field(description="Copy this render's DELIVERABLES (document.fg.yaml, page SVGs, PNGs, PDF, diagnostics.json + a sha256 manifest) to FRAMEFORGE_MCP_PUBLISH_ROOT/<session_id>/ — the durable counterpart of the ephemeral session scratchpad. Fails fast with a structured error when the root is unset; re-publishing a session replaces its directory."),
        ] = False,
    ):
        """Run an editable Python SDK client, validate its YAML, and return render feedback.

        ``pages`` selects specific 1-based pages to render (e.g. ``"6-10,15"``), overriding
        ``max_pages``; omit it to render the first ``max_pages`` pages (``<=0`` = all).
        """
        result = _logged_call(
            log_path,
            "run_sdk_client",
            {
                "path": path,
                "session_id": session_id,
                "timeout_seconds": timeout_seconds,
                "max_pages": max_pages,
                "raster_png": raster_png,
                "invoke_main": invoke_main,
                "pages": pages,
                "sign": sign,
                "signed_at": signed_at,
                "silhouette": silhouette,
                "to": to,
                "scale": scale,
                "real_metrics": real_metrics,
                "font_closure": font_closure,
                "font_generics": font_generics,
                "reference": reference,
            },
            lambda: _enveloped("run_sdk_client", lambda: _uc_run_sdk_client(
                path,
                session_id=session_id,
                session_root=root,
                timeout_seconds=timeout_seconds,
                max_pages=max_pages,
                raster_png=raster_png,
                invoke_main=invoke_main,
                pages=pages,
                sign=sign,
                signed_at=signed_at,
                silhouette=silhouette,
                to=to,
                scale=scale,
                real_metrics=real_metrics,
                font_closure=font_closure,
                font_generics=font_generics,
                reference=reference,
                publish=publish,
                repo_root=repo,
                edit_roots=edit_roots,
            )),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("run_sdk_code")
    def run_sdk_code(
        code: Annotated[
            str,
            Field(description="Python source that uses frameforge_sdk and emits a document: write OUTPUT_YAML_PATH, or expose a doc/document/builder global or a build() function."),
        ],
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
        timeout_seconds: Annotated[int, Field(description=_DESC_TIMEOUT)] = DEFAULT_TIMEOUT_SECONDS,
        max_pages: Annotated[int, Field(description=_DESC_MAX_PAGES)] = 3,
        raster_png: Annotated[bool, Field(description=_DESC_RASTER)] = True,
        pages: Annotated[str | None, Field(description=_DESC_PAGES)] = None,
        sign: Annotated[bool, Field(description=_DESC_SIGN)] = False,
        signed_at: Annotated[str | None, Field(description=_DESC_SIGNED_AT)] = None,
        silhouette: Annotated[bool, Field(description=_DESC_SILHOUETTE)] = False,
        to: Annotated[str, Field(description=_DESC_TO)] = "png",
        scale: Annotated[float, Field(description=_DESC_SCALE)] = 1.0,
        real_metrics: Annotated[bool | str, Field(description=_DESC_REAL_METRICS)] = "auto",
        font_closure: Annotated[str | None, Field(description=_DESC_FONT_CLOSURE)] = None,
        font_generics: Annotated[
            dict[str, str] | None, Field(description=_DESC_FONT_GENERICS)
        ] = None,
        reference: Annotated[
            str | None,
            Field(description="Optional reference image (path, frameforge:// URI, or data:image URI) to diff the rendered page 1 against: the result gains reference_diff with per-object ghost vectors — each authored object's displacement toward its best match in the reference — so corrections are typed from numbers instead of eyeballed off an overlay."),
        ] = None,

        publish: Annotated[
            bool,
            Field(description="Copy this render's DELIVERABLES (document.fg.yaml, page SVGs, PNGs, PDF, diagnostics.json + a sha256 manifest) to FRAMEFORGE_MCP_PUBLISH_ROOT/<session_id>/ — the durable counterpart of the ephemeral session scratchpad. Fails fast with a structured error when the root is unset; re-publishing a session replaces its directory."),
        ] = False,
    ):
        """Run Python SDK code, validate its YAML, and return render feedback.

        ``pages`` selects specific 1-based pages to render (e.g. ``"6-10,15"``), overriding
        ``max_pages``; omit it to render the first ``max_pages`` pages (``<=0`` = all).
        """
        result = _logged_call(
            log_path,
            "run_sdk_code",
            {
                "code": code,
                "session_id": session_id,
                "timeout_seconds": timeout_seconds,
                "max_pages": max_pages,
                "raster_png": raster_png,
                "pages": pages,
                "sign": sign,
                "signed_at": signed_at,
                "silhouette": silhouette,
                "to": to,
                "scale": scale,
                "real_metrics": real_metrics,
                "font_closure": font_closure,
                "font_generics": font_generics,
                "reference": reference,
            },
            lambda: _enveloped("run_sdk_code", lambda: _uc_run_sdk_code(
                code,
                session_id=session_id,
                session_root=root,
                timeout_seconds=timeout_seconds,
                max_pages=max_pages,
                raster_png=raster_png,
                pages=pages,
                sign=sign,
                signed_at=signed_at,
                silhouette=silhouette,
                to=to,
                scale=scale,
                real_metrics=real_metrics,
                font_closure=font_closure,
                font_generics=font_generics,
                reference=reference,
                publish=publish,
            )),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("render_frameforge_yaml")
    def render_frameforge_yaml(
        yaml_text: Annotated[
            str,
            Field(description="FrameForge document as YAML text to validate and render directly, without executing any Python."),
        ],
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
        max_pages: Annotated[int, Field(description=_DESC_MAX_PAGES)] = 3,
        raster_png: Annotated[bool, Field(description=_DESC_RASTER)] = True,
        pages: Annotated[str | None, Field(description=_DESC_PAGES)] = None,
        sign: Annotated[bool, Field(description=_DESC_SIGN)] = False,
        signed_at: Annotated[str | None, Field(description=_DESC_SIGNED_AT)] = None,
        silhouette: Annotated[bool, Field(description=_DESC_SILHOUETTE)] = False,
        to: Annotated[str, Field(description=_DESC_TO)] = "png",
        scale: Annotated[float, Field(description=_DESC_SCALE)] = 1.0,
        real_metrics: Annotated[bool | str, Field(description=_DESC_REAL_METRICS)] = "auto",
        font_closure: Annotated[str | None, Field(description=_DESC_FONT_CLOSURE)] = None,
        font_generics: Annotated[
            dict[str, str] | None, Field(description=_DESC_FONT_GENERICS)
        ] = None,
        reference: Annotated[
            str | None,
            Field(description="Optional reference image (path, frameforge:// URI, or data:image URI) to diff the rendered page 1 against: the result gains reference_diff with per-object ghost vectors — each authored object's displacement toward its best match in the reference — so corrections are typed from numbers instead of eyeballed off an overlay."),
        ] = None,

        publish: Annotated[
            bool,
            Field(description="Copy this render's DELIVERABLES (document.fg.yaml, page SVGs, PNGs, PDF, diagnostics.json + a sha256 manifest) to FRAMEFORGE_MCP_PUBLISH_ROOT/<session_id>/ — the durable counterpart of the ephemeral session scratchpad. Fails fast with a structured error when the root is unset; re-publishing a session replaces its directory."),
        ] = False,
    ):
        """Validate and render FrameForge YAML without executing Python code.

        ``pages`` selects specific 1-based pages to render (e.g. ``"6-10,15"``), overriding
        ``max_pages``; omit it to render the first ``max_pages`` pages (``<=0`` = all).
        """
        result = _logged_call(
            log_path,
            "render_frameforge_yaml",
            {
                "yaml_text": yaml_text,
                "session_id": session_id,
                "max_pages": max_pages,
                "raster_png": raster_png,
                "pages": pages,
                "sign": sign,
                "signed_at": signed_at,
                "silhouette": silhouette,
                "to": to,
                "scale": scale,
                "real_metrics": real_metrics,
                "font_closure": font_closure,
                "font_generics": font_generics,
                "reference": reference,
            },
            lambda: _enveloped("render_frameforge_yaml", lambda: _uc_render_frameforge_yaml(
                yaml_text,
                session_id=session_id,
                session_root=root,
                max_pages=max_pages,
                raster_png=raster_png,
                pages=pages,
                sign=sign,
                signed_at=signed_at,
                silhouette=silhouette,
                to=to,
                scale=scale,
                real_metrics=real_metrics,
                font_closure=font_closure,
                font_generics=font_generics,
                reference=reference,
                publish=publish,
            )),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("design_audit")
    def design_audit(
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
    ):
        """Full design-token + feature-usage audit of a session's most recent render.

        Reads the session's rendered SVG pages + document and returns the census —
        fonts, sizes, weights, colours, and features (drift-proof: read off the
        emitted SVG plus a generic model walk) — with design-system health flags
        (type-scale-sprawl, palette-sprawl, mixed-weight-encoding, near-duplicate
        sizes). Run a render tool first; the compact census also rides on every
        render result's ``design`` key. Persists ``audit.json``/``audit.md`` as
        session resources.

        Two ERROR-severity classes ride here too, because a document can render
        perfectly and still be unusable:

        * ``low-contrast`` / ``type-too-small`` / ``measure-*`` — the reader
          cannot read it (WCAG 2.1 SC 1.4.3 and the legible-size floor); the
          count is ``design.unreadable``, the detail in ``audit.legibility``.
        * ``text-collision`` — unintended same-layer text painted over text; the
          count is ``design.collisions``, the records in ``audit.collisions``,
          each naming the page, the overlap extent, both ink rectangles and a
          text excerpt of each party (ids are optional, so excerpts are what make
          an id-less pair locatable). Declare ``overlap: "allowed"`` on both
          objects when the overlap is the design.

        This is the same report as the CLI's ``--to audit`` and the SDK's
        ``collision_report()`` — verify through any door and get the same answer.
        """
        result = _logged_call(
            log_path,
            "design_audit",
            {"session_id": session_id},
            lambda: _enveloped("design_audit", lambda: _uc_design_audit(
                session_id=session_id,
                session_root=root,
            )),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("propose_from_image")
    def propose_from_image(
        image_path: Annotated[
            str | None, Field(description="Filesystem path to the source image. Provide this or image_base64.")
        ] = None,
        image_base64: Annotated[
            str | None, Field(description="Base64-encoded image bytes. Provide this or image_path.")
        ] = None,
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
        max_pages: Annotated[int, Field(description=_DESC_MAX_PAGES)] = 3,
        raster_png: Annotated[bool, Field(description=_DESC_RASTER)] = True,
        pages: Annotated[str | None, Field(description=_DESC_PAGES)] = None,
        title: Annotated[str, Field(description="Title for the proposed draft document.")] = "Proposed from image",
        detector_names: Annotated[list[str] | None, Field(description=_DESC_DETECTORS)] = None,
    ):
        """Propose a DRAFT FrameForge document from an image (OpenCV/numpy + optional VLM), then validate and render it."""
        result = _logged_enveloped_call(
            log_path,
            "propose_from_image",
            {
                "image_path": image_path,
                "image_base64_bytes": len(image_base64) if image_base64 else 0,
                "session_id": session_id,
                "max_pages": max_pages,
                "raster_png": raster_png,
                "pages": pages,
                "title": title,
                "detector_names": detector_names,
            },
            lambda: _uc_propose_from_image(
                image_path,
                image_base64=image_base64,
                session_id=session_id,
                session_root=root,
                max_pages=max_pages,
                raster_png=raster_png,
                pages=pages,
                title=title,
                detector_names=detector_names,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("describe_render")
    def describe_render(
        image: Annotated[str, Field(description=_DESC_VLM_IMAGE)],
        question: Annotated[str | None, Field(description=_DESC_VLM_QUESTION)] = None,
        stage: Annotated[str | None, Field(description=_DESC_VLM_STAGE)] = None,
        model: Annotated[str | None, Field(description="Override the VLM model id (default SmolVLM-256M).")] = None,
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
    ):
        """Have a local (CPU) vision model describe/assess a rendered page in words — ADVISORY (PALS's Law), a steer not a measurement; verify with compare_images / score_reconstruction / the validator."""
        result = _logged_call(
            log_path,
            "describe_render",
            {"image": image, "question": question, "stage": stage, "model": model, "session_id": session_id},
            lambda: _uc_describe_render(
                image,
                question=question,
                stage=stage,
                model=model,
                session_id=session_id,
                session_root=root,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("coach_vectorize")
    def coach_vectorize(
        image_path: Annotated[str, Field(description="Filesystem path to the source image (line-art or illustration).")],
        style: Annotated[str, Field(description=_DESC_COACH_STYLE)] = "children_book",
        modes: Annotated[str, Field(description=_DESC_COACH_MODES)] = "region,outline",
        paint: Annotated[bool, Field(description=_DESC_COACH_PAINT)] = True,
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
        max_pages: Annotated[int, Field(description=_DESC_MAX_PAGES)] = 3,
        raster_png: Annotated[bool, Field(description=_DESC_RASTER)] = True,
        pages: Annotated[str | None, Field(description=_DESC_PAGES)] = None,
        silhouette: Annotated[bool, Field(description=_DESC_SILHOUETTE)] = True,
    ):
        """Run the Vector Construction Coach pipeline on an image (ingest → clean → redraw → recolor → paint), styled by the named grammar, then validate, render, and gate it."""
        result = _logged_call(
            log_path,
            "coach_vectorize",
            {
                "image_path": image_path,
                "style": style,
                "modes": modes,
                "paint": paint,
                "session_id": session_id,
                "max_pages": max_pages,
                "raster_png": raster_png,
                "pages": pages,
                "silhouette": silhouette,
            },
            lambda: _uc_coach_vectorize(
                image_path,
                style=style,
                modes=modes,
                paint=paint,
                session_id=session_id,
                session_root=root,
                max_pages=max_pages,
                raster_png=raster_png,
                pages=pages,
                silhouette=silhouette,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("propose_from_document")
    def propose_from_document(
        path: Annotated[str, Field(description="Filesystem path to the source PDF.")],
        page: Annotated[int, Field(description="1-based PDF page number to rasterize and analyze.")] = 1,
        dpi: Annotated[
            int, Field(description="Resolution (DPI) to rasterize the PDF page at before detection.")
        ] = 144,
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
        max_pages: Annotated[int, Field(description=_DESC_MAX_PAGES)] = 3,
        raster_png: Annotated[bool, Field(description=_DESC_RASTER)] = True,
        pages: Annotated[str | None, Field(description=_DESC_PAGES)] = None,
        title: Annotated[
            str | None, Field(description="Title for the proposed draft document; defaults to the source name.")
        ] = None,
        detector_names: Annotated[list[str] | None, Field(description=_DESC_DETECTORS)] = None,
    ):
        """Propose a DRAFT FrameForge document from a rasterised PDF page, then validate and render it."""
        result = _logged_enveloped_call(
            log_path,
            "propose_from_document",
            {
                "path": path,
                "page": page,
                "dpi": dpi,
                "session_id": session_id,
                "max_pages": max_pages,
                "raster_png": raster_png,
                "pages": pages,
                "title": title,
                "detector_names": detector_names,
            },
            lambda: _uc_propose_from_document(
                path,
                page=page,
                dpi=dpi,
                session_id=session_id,
                session_root=root,
                max_pages=max_pages,
                raster_png=raster_png,
                pages=pages,
                title=title,
                detector_names=detector_names,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("propose_from_svg")
    def propose_from_svg(
        svg_path: Annotated[
            str | None, Field(description="Filesystem path to a .svg file. Provide this or svg_text.")
        ] = None,
        svg_text: Annotated[
            str | None, Field(description="SVG document as text. Provide this or svg_path.")
        ] = None,
        regions: Annotated[
            list[dict] | None,
            Field(description="Optional region-level grade: a list of "
                  '{"box": [x, y, w, h], "ramp": "#hex" | [[pos, "#hex"], ...]}. Each object is '
                  "recoloured by the region its centroid falls in (most-specific window first)."),
        ] = None,
        default_ramp: Annotated[
            Any,
            Field(description="Paint for objects in no region: a '#hex' string or a "
                  "[[pos, '#hex'], ...] ramp. Omit to leave unmatched objects unchanged."),
        ] = None,
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
        max_pages: Annotated[int, Field(description=_DESC_MAX_PAGES)] = 3,
        raster_png: Annotated[bool, Field(description=_DESC_RASTER)] = True,
        pages: Annotated[str | None, Field(description=_DESC_PAGES)] = None,
        title: Annotated[str, Field(description="Title for the ingested document.")] = "Proposed from SVG",
    ):
        """Ingest an SVG into a FrameForge document (1:1 vector lowering), optionally recolour it by region, then validate and render.

        Unlike ``propose_from_image`` (which re-detects from pixels), this lowers the
        SVG's own elements to FrameForge primitives. ``regions`` applies a region-level
        colour grade; region clip/transform stay in the SDK (``place_region``) via
        ``run_sdk_code``.
        """
        result = _logged_enveloped_call(
            log_path,
            "propose_from_svg",
            {
                "svg_path": svg_path,
                "svg_text_bytes": len(svg_text) if svg_text else 0,
                "regions": regions,
                "default_ramp": default_ramp,
                "session_id": session_id,
                "max_pages": max_pages,
                "raster_png": raster_png,
                "pages": pages,
                "title": title,
            },
            lambda: _uc_propose_from_svg(
                svg_path,
                svg_text=svg_text,
                regions=regions,
                default_ramp=default_ramp,
                session_id=session_id,
                session_root=root,
                max_pages=max_pages,
                raster_png=raster_png,
                pages=pages,
                title=title,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("compare_images")
    def compare_images(
        reference: Annotated[
            str,
            Field(description="Reference/source image: a filesystem path, a frameforge://session/<id>/page/<n>.png URI, or a data:image/<type>;base64,<payload> URI."),
        ],
        candidate: Annotated[
            str,
            Field(description="Candidate/recreation image to compare against the reference: a filesystem path, a frameforge://session/<id>/page/<n>.png URI, or a data:image/<type>;base64,<payload> URI (e.g. a page just rendered by run_sdk_client)."),
        ],
        regions: Annotated[
            list[dict] | None,
            Field(description='Named crops to zoom into, as [{"name": str, "box": [x, y, w, h]}] with all values normalized 0..1 (fractions of width/height). Omit to auto-split.'),
        ] = None,
        grid: Annotated[
            list[int] | None,
            Field(description="Auto-split both images into a [cols, rows] grid of regions when `regions` is omitted (defaults to [2, 3])."),
        ] = None,
        diff: Annotated[
            bool, Field(description="Include a per-region difference cell (bright red = mismatch).")
        ] = True,
        align: Annotated[
            bool, Field(description="Phase-align the candidate onto the reference before scoring, so a pure offset doesn't read as error (adds `metrics.shift_px`).")
        ] = False,
        label_reference: Annotated[str, Field(description="Caption for the reference column.")] = "reference",
        label_candidate: Annotated[str, Field(description="Caption for the candidate column.")] = "recreation",
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
    ):
        """Compose zoomed side-by-side comparison panels of two images for visual QA.

        Emits an overview plus one ``reference | candidate | difference`` panel per
        region — each crop scaled up and stamped with a naive pixel-match score — so a
        vision model can *see* where a recreation is off instead of eyeballing two
        downscaled thumbnails. The pixel-match score is a hint (luminance difference),
        not a verdict; the panels are the signal.
        """
        result = _logged_enveloped_call(
            log_path,
            "compare_images",
            {
                "reference": reference,
                "candidate": candidate,
                "regions": regions,
                "grid": grid,
                "diff": diff,
                "align": align,
                "label_reference": label_reference,
                "label_candidate": label_candidate,
                "session_id": session_id,
            },
            lambda: _uc_compare_images(
                reference,
                candidate,
                regions=regions,
                grid=grid,
                diff=diff,
                align=align,
                label_reference=label_reference,
                label_candidate=label_candidate,
                session_id=session_id,
                session_root=root,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("measure_image")
    def measure_image(
        image: Annotated[
            str,
            Field(description="Image to measure: a filesystem path, a frameforge://session/<id>/page/<n>.png URI, or a data:image/<type>;base64,<payload> URI."),
        ],
        regions: Annotated[
            list[dict] | None,
            Field(description='Named regions to box + ID + measure, as [{"name": str, "box": [x, y, w, h]}] with values normalized 0..1. Each gets a stable id (R1, R2, ...) plus exact bbox/centroid/area/offset in the spatial payload.'),
        ] = None,
        region_grid: Annotated[
            list[int] | None,
            Field(description="Segment the image into a [cols, rows] grid of measured regions when `regions` is omitted."),
        ] = None,
        zooms: Annotated[
            list[dict] | None,
            Field(description='Zoomed crops to also emit, as [{"name": str, "box": [x, y, w, h]}] normalized 0..1. Each crop is enlarged but its rulers stay labelled in SOURCE coordinates; its origin+scale transform back to source pixels is in spatial.crops.'),
        ] = None,
        origin: Annotated[
            str,
            Field(description="Coordinate-system origin: 'top-left' (image/page space, +y down; default), 'bottom-left' (+y up), or 'center' (+y up)."),
        ] = "top-left",
        grid: Annotated[bool, Field(description="Draw the measurement grid.")] = True,
        grid_step: Annotated[
            int | None,
            Field(description="Grid/ruler tick spacing in source pixels (0/omit = a round auto step from the image size)."),
        ] = None,
        rulers: Annotated[bool, Field(description="Draw edge rulers (top + left) labelled in coordinate-system units.")] = True,
        label_every: Annotated[int, Field(description="Label (and emphasise) every Nth grid tick.")] = 2,
        landmarks: Annotated[bool, Field(description="Draw + report landmark anchors (the exact structural anchors A1..A9 always; detected L* when enabled).")] = True,
        detect_landmarks: Annotated[bool, Field(description="Also run the CV detectors for extra (UNVERIFIED) landmark anchors. Needs the vision group.")] = True,
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
    ):
        """Overlay an auto grid + rulers + coordinate system on an image and extract exact spatial metadata.

        Turns a rasterized image into a reliable coordinate reference for vector
        reconstruction: the overlay PNG keeps the source's pixel size (so coordinates
        read 1:1) and carries a grid, edge rulers, region boxes with stable IDs, and
        landmark crosshairs; the ``spatial`` payload carries the exact numbers
        (coordinate system, per-region bbox/centroid/area/offset, structural + detected
        landmarks, and each zoom crop's origin+scale transform back to source pixels).

        ⚠ PALS's LAW: the coordinate system, grid, rulers, explicit regions, and
        structural landmarks (A1..A9) are exact geometry; detected landmarks (L*) are
        UNVERIFIED CV guesses — anchor to the structural anchors, treat the rest as hints.
        """
        result = _logged_enveloped_call(
            log_path,
            "measure_image",
            {
                "image": image,
                "regions": regions,
                "region_grid": region_grid,
                "zooms": zooms,
                "origin": origin,
                "grid": grid,
                "grid_step": grid_step,
                "rulers": rulers,
                "label_every": label_every,
                "landmarks": landmarks,
                "detect_landmarks": detect_landmarks,
                "session_id": session_id,
            },
            lambda: _uc_measure_image(
                image,
                regions=regions,
                region_grid=region_grid,
                zooms=zooms,
                origin=origin,
                grid=grid,
                grid_step=grid_step,
                rulers=rulers,
                label_every=label_every,
                landmarks=landmarks,
                detect_landmarks=detect_landmarks,
                session_id=session_id,
                session_root=root,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("mark_points")
    def mark_points(
        image: Annotated[
            str,
            Field(description="Image to mark on: a filesystem path, a frameforge://session/<id>/page/<n>.png URI, or a data:image/<type>;base64,<payload> URI."),
        ],
        points: Annotated[
            list[dict],
            Field(description=(
                'Ordered points to mark. Each is ONE of: {"norm": [nx, ny]} (0..1 of the full image), '
                '{"px": [x, y]} (source pixels), {"cs": [cx, cy]} (coordinate-system units), '
                '{"landmark": "A9", "dx": 0, "dy": 0} (offset from a landmark), or '
                '{"viewport_px": [vx, vy]} (pixels in the `viewport` crop). Optional "label" per point.'
            )),
        ],
        viewport: Annotated[
            dict | None,
            Field(description='Optional current view as {"name": str, "box": [x, y, w, h]} normalized 0..1. Points are anchored to the IMAGE, so the crosshairs stay fixed as the viewport moves; the marked view is emitted zoomed with rulers in source coordinates.'),
        ] = None,
        connect: Annotated[
            bool, Field(description="Draw a polyline through the points in order (a preview of the path they would trace).")
        ] = False,
        origin: Annotated[str, Field(description="Coordinate-system origin: 'top-left' (default), 'bottom-left', or 'center'.")] = "top-left",
        grid: Annotated[bool, Field(description="Draw the measurement grid behind the marks.")] = True,
        rulers: Annotated[bool, Field(description="Draw edge rulers.")] = True,
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
    ):
        """Mark coordinate points on an image and resolve each in every frame (image / coordinate-system / viewport).

        The AI's "aim + click": give points in any frame and get back an annotated
        image with numbered crosshairs plus, per point, its coordinates in the full
        image (px + coordinate system + normalized) and in the current viewport crop.
        Because points are anchored to the image, the crosshair stays fixed while the
        viewport moves. ``connect`` previews the path the points would trace — the
        bridge to the (later) vector-construction commands.
        """
        result = _logged_enveloped_call(
            log_path,
            "mark_points",
            {
                "image": image,
                "points": points,
                "viewport": viewport,
                "connect": connect,
                "origin": origin,
                "grid": grid,
                "rulers": rulers,
                "session_id": session_id,
            },
            lambda: _uc_mark_points(
                image,
                points=points,
                viewport=viewport,
                connect=connect,
                origin=origin,
                grid=grid,
                rulers=rulers,
                session_id=session_id,
                session_root=root,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("overlay_images")
    def overlay_images(
        base: Annotated[
            str,
            Field(description="Base/source image: a filesystem path, a frameforge://session/<id>/page/<n>.png URI, or a data:image/<type>;base64,<payload> URI."),
        ],
        overlay: Annotated[
            str,
            Field(description="Overlay image to align onto the base: a filesystem path, a frameforge://session/<id>/page/<n>.png URI, or a data:image/<type>;base64,<payload> URI."),
        ],
        landmarks: Annotated[
            list[dict],
            Field(description=(
                'Matched landmark pairs, as [{"base": [x, y], "overlay": [x, y]}]. Coordinates are '
                'source pixels by default; set "norm": true on a pair to give both as 0..1 fractions. '
                'One pair → translation only; two or more → best-fit scale + translation.'
            )),
        ],
        opacity: Annotated[
            float, Field(description="Overlay opacity in the aligned composite, 0..1.")
        ] = 0.5,
        rotation: Annotated[
            bool,
            Field(description="Opt into the full-similarity model (scale + rotation + translation, 2D Procrustes; needs >= 2 pairs). Default false keeps the rotation-free contract, where a tilted overlay shows up honestly as residuals."),
        ] = False,
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
    ):
        """Align an overlay image onto a base by matched landmarks and extract the coordinate offsets.

        Computes the offset between each landmark pair, fits a scale+translation that
        best maps overlay→base (rotation modelled only when `rotation=true`), reports per-pair residuals,
        and emits an aligned composite so the fit is visible. Use it to compare, align,
        and reconstruct visual structures across a source and a reference.
        """
        result = _logged_enveloped_call(
            log_path,
            "overlay_images",
            {
                "base": base,
                "overlay": overlay,
                "landmarks": landmarks,
                "opacity": opacity,
                "rotation": rotation,
                "session_id": session_id,
            },
            lambda: _uc_overlay_images(
                base,
                overlay,
                landmarks=landmarks,
                opacity=opacity,
                rotation=rotation,
                session_id=session_id,
                session_root=root,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("workspace")
    def workspace(
        action: Annotated[
            str,
            Field(description=(
                "Workspace action: 'open' (bind an image — required first), 'pin' (add points), "
                "'nudge' (move selected pins by a delta — the AI mouse), 'move' (absolute), "
                "'snap' (snap selected pins to the nearest bright/dark/edge/centroid pixel, or "
                "sub-pixel edge with snap_to='edge_subpixel'), 'fit_edge' (re-project selected pins "
                "onto one sub-pixel edge line — collinear + edge-accurate), 'collinear' (project "
                "selected pins onto their best-fit line), 'symmetrize' (enforce bilateral symmetry "
                "over pin pairs, geometry={'pairs':[[l,r],...]}), 'intersect' (set a corner pin at "
                "the meeting of two edges, geometry={'edge1':[ids],'edge2':[ids],'target':id}), "
                "'transform' (translate+scale+rotate selected pins as a group), 'unpin', 'clear', "
                "'viewport' (set/clear a crop), 'pan', 'zoom', 'checkpoint' (save state), "
                "'revert' (restore a checkpoint), or 'render'/'status' (aliases: re-render the "
                "current state without changing it)."
            )),
        ] = "render",
        image: Annotated[
            str | None,
            Field(description="For 'open': the image path or frameforge://session/<id>/page/<n>.png URI to bind."),
        ] = None,
        points: Annotated[
            list[dict] | None,
            Field(description='For "pin": points to add, each in any frame — {"norm"|"px"|"cs"|"viewport_px": [a,b]} or {"landmark": id, "dx"?, "dy"?}; optional "id"/"group"/"label". A spec may reference an existing pin id.'),
        ] = None,
        select: Annotated[
            dict | None,
            Field(description='Which pins an action targets: omit for all, or {"ids": [...]} or {"group": name}. Enables multi-adjust.'),
        ] = None,
        to: Annotated[dict | None, Field(description="For 'move': the absolute target point (any frame).")] = None,
        dx: Annotated[float, Field(description="For 'nudge'/'pan': x delta (see 'unit'; e.g. -0.01 norm = left).")] = 0.0,
        dy: Annotated[float, Field(description="For 'nudge'/'pan': y delta.")] = 0.0,
        unit: Annotated[str, Field(description="Nudge unit: 'norm' (fraction of image; default), 'px', or 'viewport'.")] = "norm",
        viewport: Annotated[
            dict | None,
            Field(description='For "viewport": {"name"?, "box": [x, y, w, h]} normalized 0..1 to set, or omit box to clear.'),
        ] = None,
        factor: Annotated[float | None, Field(description="For 'zoom': zoom factor (>1 zooms in).")] = None,
        aim: Annotated[dict | None, Field(description="For 'zoom' (kept centred) / 'transform' (pivot): a point in any frame; default viewport centre / selection centroid.")] = None,
        snap_to: Annotated[str, Field(description="For 'snap': target — 'bright', 'dark', 'edge', 'centroid', or 'edge_subpixel' (sub-pixel edge via the gradient normal).")] = "bright",
        radius: Annotated[int, Field(description="For 'snap': search window radius in pixels.")] = 4,
        scale: Annotated[float, Field(description="For 'transform': uniform scale about the pivot.")] = 1.0,
        rotate: Annotated[float, Field(description="For 'transform': rotation in degrees about the pivot.")] = 0.0,
        tag: Annotated[str | None, Field(description="For 'checkpoint': an optional label.")] = None,
        index: Annotated[int, Field(description="For 'revert': checkpoint index (default -1 = latest).")] = -1,
        geometry: Annotated[
            dict | None,
            Field(description=(
                "Args for the constraint actions: 'symmetrize' → {'pairs':[[leftId,rightId],...], "
                "'axis'?}; 'intersect' → {'edge1':[ids],'edge2':[ids],'target':id}; sub-pixel edge "
                "tuning for fit_edge/intersect/snap → {'band'?,'step'?,'min_strength'?,'search_dir'?}."
            )),
        ] = None,
        origin: Annotated[str, Field(description="For 'open': coordinate origin ('top-left'/'bottom-left'/'center').")] = "top-left",
        grid: Annotated[bool, Field(description="Draw the measurement grid.")] = True,
        rulers: Annotated[bool, Field(description="Draw edge rulers.")] = True,
        connect: Annotated[bool, Field(description="Draw a polyline through the pins in order.")] = False,
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
    ):
        """Stateful coordinate workspace — the AI's precise pointer for multi-pass reconstruction.

        One workspace persists per ``session_id``: pins (anchor points) and a viewport
        survive across calls, so the AI can pin, look, nudge (e.g. 0.01 left), pin more,
        and refine over passes until pixel-accurate. Pins are image-anchored, so their
        coordinates hold as the viewport pans/zooms (fixed aim). Every call re-renders the
        overlay (+ viewport crop) and returns each pin resolved in every frame.
        """
        result = _logged_enveloped_call(
            log_path,
            "workspace",
            {
                "action": action, "image": image, "points": points, "select": select,
                "to": to, "dx": dx, "dy": dy, "unit": unit, "viewport": viewport,
                "factor": factor, "aim": aim, "snap_to": snap_to, "radius": radius,
                "scale": scale, "rotate": rotate, "tag": tag, "index": index,
                "geometry": geometry,
                "origin": origin, "grid": grid, "rulers": rulers, "connect": connect,
                "session_id": session_id,
            },
            lambda: _uc_workspace(
                action, image=image, points=points, select=select, to=to,
                dx=dx, dy=dy, unit=unit, viewport=viewport, factor=factor, aim=aim,
                snap_to=snap_to, radius=radius, scale=scale, rotate=rotate, tag=tag,
                index=index, geometry=geometry, origin=origin, grid=grid, rulers=rulers,
                connect=connect, session_id=session_id, session_root=root,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("construct_vectors")
    def construct_vectors(
        shapes: Annotated[
            list[dict],
            Field(description=(
                'Shapes to draw, each {"kind": one of line/path/trace/polyline/curve/spline/arc/'
                'triangle/polygon/closed/rect/ellipse/circle/star/text, "points": [[x,y],...] (image px) '
                'OR "pins": [ids from the workspace / landmarks A1..A9], optional "style": '
                '{stroke, stroke_width, fill}, for circle/star optional "r"/"points_count"/"inner_ratio". '
                'arc: 3 points (start/on-arc/end through their circumcircle) or 1 centre point + '
                '"r" + "start_deg"/"end_deg". text: requires "text" and "size" (font px); 1 anchor '
                'point (box top-left) or 2+ points (the bbox).'
            )),
        ],
        image: Annotated[
            str | None,
            Field(description="Optional source image (path or session URI) — used for canvas size and as the diff reference."),
        ] = None,
        from_workspace: Annotated[
            str | None,
            Field(description="Session id of a workspace whose pins the shapes reference (defaults to session_id)."),
        ] = None,
        width: Annotated[int | None, Field(description="Canvas width px (overrides workspace/image dims).")] = None,
        height: Annotated[int | None, Field(description="Canvas height px.")] = None,
        background: Annotated[str | None, Field(description="Optional page background colour (e.g. '#ffffff').")] = None,
        title: Annotated[str, Field(description="Title for the reconstruction document.")] = "Vector reconstruction",
        raster_png: Annotated[bool, Field(description=_DESC_RASTER)] = True,
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
    ):
        """Draw FrameForge vector geometry from anchor points, then validate + render it.

        Turns marked coordinates (workspace pins or explicit image pixels) into real SDK
        primitives (line, path, curve/spline, polygon, triangle, rect, circle, ellipse,
        star, closed region), authors a FrameForge document sized to the source so it
        overlays the raster 1:1, and runs it through validate + render. Diff the render
        against the source with ``compare_images`` and refine the pins to converge.
        """
        result = _logged_enveloped_call(
            log_path,
            "construct_vectors",
            {
                "shapes": shapes, "image": image, "from_workspace": from_workspace,
                "width": width, "height": height, "background": background,
                "title": title, "raster_png": raster_png, "session_id": session_id,
            },
            lambda: _uc_construct_vectors(
                shapes, image=image, from_workspace=from_workspace, width=width,
                height=height, background=background, title=title,
                raster_png=raster_png, session_id=session_id, session_root=root,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("score_reconstruction")
    def score_reconstruction(
        image: Annotated[
            str,
            Field(description="Source image (filesystem path or frameforge://session/<id>/page/<n>.png URI) whose edges the shapes are scored against."),
        ],
        shapes: Annotated[
            list[dict],
            Field(description=(
                'Shapes to score — same schema as construct_vectors: each {"kind": one of '
                'line/path/trace/polyline/curve/spline/arc/triangle/polygon/closed/rect/ellipse/'
                'circle/star/text, "points": [[x,y],...] (image px) OR "pins": [workspace ids / '
                'landmarks A1..A9], and for circle/star optional "r"/"points_count"/"inner_ratio"}. '
                "'text' contributes no edge samples (glyph outlines are font geometry)."
            )),
        ],
        from_workspace: Annotated[
            str | None,
            Field(description="Session id of a workspace whose pins the shapes reference (defaults to session_id)."),
        ] = None,
        roi: Annotated[
            list[float] | None,
            Field(description="Optional [x0, y0, x1, y1] pixel window to score within (defaults to the whole image)."),
        ] = None,
        tol: Annotated[
            float, Field(description="A shape sample within this many pixels of a detected edge counts as on-edge.")
        ] = 2.0,
        symmetry_pairs: Annotated[
            list | None,
            Field(description='Optional bilateral pairs [[left, right], ...] to check for symmetry — adds a geometry-consistency report (catches a single-corner offset the luminance % is blind to). Each point is [x, y] image px OR a workspace pin/landmark id string ("P3", "A9"), resolved against from_workspace like shape pins.'),
        ] = None,
        collinear_groups: Annotated[
            list | None,
            Field(description='Optional point groups [[p1, p2, ...], ...] that should each lie on one straight edge — adds each group\'s collinearity residual. Points are [x, y] image px or workspace pin/landmark id strings, like symmetry_pairs.'),
        ] = None,
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
    ):
        """Score how well constructed vector shapes sit on the source image's edges.

        The NUMERIC convergence signal for the raster→vector loop — complements
        ``compare_images`` (which shows *where* a recreation is off) by reporting *how
        far*: ``on_edge_frac`` (fraction of shape samples within ``tol`` px of a detected
        edge) plus mean/median/p90 distances, over a match overlay (source dimmed, edges
        cyan, samples green on-edge / red off). Drive ``on_edge_frac`` up and distances
        down across passes. ``symmetry_pairs``/``collinear_groups`` add a
        geometry-consistency report (``score.geometry``) — symmetry-axis and edge
        collinearity residuals a whole-image luminance match cannot see. Edges are an
        adaptive-Sobel heuristic — a RELATIVE guide, not ground truth (PALS's Law).
        """
        result = _logged_enveloped_call(
            log_path,
            "score_reconstruction",
            {
                "image": image, "shapes": shapes, "from_workspace": from_workspace,
                "roi": roi, "tol": tol, "symmetry_pairs": symmetry_pairs,
                "collinear_groups": collinear_groups, "session_id": session_id,
            },
            lambda: _uc_score_reconstruction(
                image, shapes, from_workspace=from_workspace, roi=roi, tol=tol,
                symmetry_pairs=symmetry_pairs, collinear_groups=collinear_groups,
                session_id=session_id, session_root=root,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("map_coordinates")
    def map_coordinates(
        mode: Annotated[
            str,
            Field(description="'homography' (fit + apply a projective transform to points), 'to_3d' (lift 2D onto a plane), 'project' (3D→2D via a camera), or 'warp' (rectify an image by the fitted homography)."),
        ],
        points: Annotated[
            list[list[float]] | None,
            Field(description="Points to transform: [x, y] for homography/to_3d, [x, y, z] for project."),
        ] = None,
        pairs: Annotated[
            list[dict] | None,
            Field(description='For "homography"/"warp": >=4 correspondences [{"src": [x, y], "dst": [x, y]}].'),
        ] = None,
        plane: Annotated[
            dict | None,
            Field(description='For "to_3d": {"origin": [x,y,z], "u": [x,y,z], "v": [x,y,z]} (default: z=0 plane).'),
        ] = None,
        camera: Annotated[
            dict | None,
            Field(description='For "project": {"eye", "target", "up": [x,y,z], "fov", "aspect", "near", "far"} (all optional).'),
        ] = None,
        image: Annotated[
            str | None,
            Field(description="For 'warp': the image (path or session URI) to rectify."),
        ] = None,
        out_size: Annotated[
            list[int] | None,
            Field(description="For 'warp': output canvas [w, h] (default: the source size)."),
        ] = None,
        width: Annotated[int | None, Field(description="For 'project': map NDC to pixels of this width.")] = None,
        height: Annotated[int | None, Field(description="For 'project': map NDC to pixels of this height.")] = None,
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
    ):
        """Transpose coordinates between 2D and 3D frames for perspective/spatial reconstruction.

        `homography` rectifies a perspective-distorted plane (or maps source→reference)
        from >=4 point pairs; `to_3d` lifts 2D image points onto a 3D plane; `project`
        projects 3D points to 2D through the SDK camera; `warp` applies the fitted
        homography to actually dewarp an image (emits the rectified PNG). Honest scope: a
        plane-to-plane projective map + a pinhole camera — no lens distortion or
        multi-view calibration.
        """
        result = _logged_enveloped_call(
            log_path,
            "map_coordinates",
            {
                "mode": mode, "points": points, "pairs": pairs, "plane": plane,
                "camera": camera, "image": image, "out_size": out_size,
                "width": width, "height": height, "session_id": session_id,
            },
            lambda: _uc_map_coordinates(
                mode, points=points, pairs=pairs, plane=plane, camera=camera,
                image=image, out_size=out_size,
                width=width, height=height, session_id=session_id, session_root=root,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("vectorize_image")
    def vectorize_image(
        image: Annotated[
            str,
            Field(description="Image to vectorize: a filesystem path, a frameforge://session/<id>/page/<n>.png URI, or a data:image/<type>;base64,<payload> URI."),
        ],
        mode: Annotated[
            str,
            Field(description="'region' (k-means colour → filled polygons; default), 'outline' (edges → polylines), 'trace' (potrace Bézier → SVG ingest; smooth curves, needs potrace), 'layers' (solid-bg logo tracer: AA-aware palette + even-odd holes — the highest-fidelity flat-logo mode), or 'auto' (classify the raster and route to the best of the four; the decision, classification, and applied presets are reported under result.vectorize.auto — explicit args always win over the presets)."),
        ] = "region",
        region_box: Annotated[
            list[float] | None,
            Field(description="Vectorize only this normalized [x, y, w, h] crop, placed back in full-image coordinates. Omit to vectorize the whole image."),
        ] = None,
        colors: Annotated[int | None, Field(description="region mode: number of quantised colours to trace (default 8; leave unset to let mode='auto' pick its route preset — an explicit value always wins).")] = None,
        detail: Annotated[float | None, Field(description="Douglas–Peucker epsilon as a fraction of contour length (higher = simpler; default 0.004; unset lets mode='auto' pick).")] = None,
        min_area: Annotated[float | None, Field(description="Drop contours below this pixel area (noise floor; default 90; unset lets mode='auto' pick).")] = None,
        max_dim: Annotated[int | None, Field(description="Downscale the longest side to this before tracing (whole-image region/outline; default 900, 0 = no scaling; unset lets mode='auto' pick).")] = None,
        ink: Annotated[str, Field(description="outline mode: stroke colour for the polylines.")] = "#1E2440",
        stroke_width: Annotated[float, Field(description="outline mode: stroke width for the polylines, in px.")] = 1.0,
        background: Annotated[str | None, Field(description="Optional page background colour (e.g. '#2e3238' for a light mark on dark).")] = None,
        threshold: Annotated[int | None, Field(description="trace mode: 0..255 bi-level threshold (omit = 128).")] = None,
        invert: Annotated[bool | None, Field(description="trace mode: invert so bright pixels are the traced foreground; omit for auto (invert when the ground is dark).")] = None,
        turdsize: Annotated[int, Field(description="trace mode: potrace speckle suppression — drop paths of fewer than this many pixels.")] = 2,
        alphamax: Annotated[float, Field(description="trace mode: potrace corner threshold (0 = sharp polygons only, 1.0 = default smoothing, up to 4/3 = smoothest).")] = 1.0,
        opttolerance: Annotated[float, Field(description="trace mode: potrace curve-optimization tolerance (higher = fewer, looser Bézier segments).")] = 0.2,
        fill: Annotated[str, Field(description="trace mode: fill colour for the traced paths.")] = "#000000",
        supersample: Annotated[int, Field(description="trace mode: AA-aware subpixel stage (1..4; default 1 = off). Upscales the grayscale BEFORE thresholding so the anti-aliased boundary is located on a 1/s px grid instead of quantising to whole pixels — kills the traced-edge halo on soft-edged sources. turdsize keeps source-pixel semantics; cost grows ~s²; 2..3 is the sweet spot.")] = 1,
        fill_mode: Annotated[str, Field(description="'flat' (default — quantised solid fills, unchanged behaviour) or 'gradient' (re-paint every traced shape from the SOURCE pixels: per-shape linear/radial gradient fills ranked by colour rms, flat mean colour when a gradient does not beat it — emitted as EXACT user-space geometry: linear `line` endpoints / radial px `at`+`radius` in each object's local space; region/trace/layers only, summary under result.vectorize.paint).")] = "flat",
        thresholds: Annotated[list[int] | None, Field(description="trace mode: run one potrace pass per 0..255 luminance level and stack the layers darkest-first — the multi-level technique for shaded/gradient logo art (e.g. [30, 110, 190]). Overrides 'threshold'; combine with fill_mode='gradient'.")] = None,
        ocr: Annotated[bool, Field(description="Also add Tesseract-detected text objects (needs the tesseract binary).")] = False,
        title: Annotated[str, Field(description="Title for the reconstruction document.")] = "Vectorized reconstruction",
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
    ):
        """Trace a raster into editable FrameForge vector objects, then validate + render it.

        The pixel-accurate complement to manual pin-and-construct: `region` k-means-traces
        flat colour into filled polygons (ideal for logos/flat art), `outline` traces edges
        into polylines, and `trace` runs potrace for smooth Bézier outlines lowered through
        the SVG-ingest path. `region_box` vectorizes just a crop, placed 1:1 in the full
        image; `ocr` adds text objects. For gradient/shaded art, `fill_mode='gradient'`
        fits per-shape gradient fills from the source and `thresholds=[...]` stacks
        multi-level trace layers. Diff the render against the source with `compare_images`.
        """
        result = _logged_enveloped_call(
            log_path,
            "vectorize_image",
            {
                "image": image, "mode": mode, "region_box": region_box, "colors": colors,
                "detail": detail, "min_area": min_area, "max_dim": max_dim, "ink": ink,
                "stroke_width": stroke_width, "background": background,
                "threshold": threshold, "invert": invert, "turdsize": turdsize,
                "alphamax": alphamax, "opttolerance": opttolerance,
                "fill": fill, "supersample": supersample,
                "fill_mode": fill_mode, "thresholds": thresholds,
                "ocr": ocr, "title": title, "session_id": session_id,
            },
            lambda: _uc_vectorize_image(
                image, mode=mode, region_box=region_box, colors=colors, detail=detail,
                min_area=min_area, max_dim=max_dim, ink=ink, stroke_width=stroke_width,
                background=background,
                threshold=threshold, invert="auto" if invert is None else invert,
                turdsize=turdsize, alphamax=alphamax, opttolerance=opttolerance,
                fill=fill, supersample=supersample,
                fill_mode=fill_mode, thresholds=thresholds,
                ocr=ocr, title=title, session_id=session_id, session_root=root,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("refine_reconstruction")
    def refine_reconstruction(
        session_id: Annotated[str, Field(description="Session whose generated.fg.yaml holds the reconstruction to refine (e.g. a prior vectorize_image session).")],
        image: Annotated[str, Field(description="The reference/source image the reconstruction targets: a filesystem path, frameforge:// URI, or data: URI. Must match the page canvas pixel-for-pixel.")],
        raster_png: Annotated[bool, Field(description="Re-render the refined document to PNG so the improvement is visible.")] = True,
        min_pixels: Annotated[int, Field(description="Smallest visible-pixel count an entry needs before its paint is refitted (below it the existing paint is kept).")] = 24,
        geometry: Annotated[bool, Field(description="G3: also descend stroke_outline GEOMETRY before refitting paints — objects carrying meta.stroke_outline provenance get a bounded coordinate descent over a 9-parameter displacement family (global/tip/base/bow shifts + width scale) against the reference; dependent rim/clip overlays are re-pointed at the refined outline. Summary under result.refine.geometry.")] = False,
        bands: Annotated[int, Field(description="H1: rim-band shading fitted on VISIBLE pixels only — for every deep-enough fill body, band thresholds come from the distance quantiles of its visible interior and each ring's paint is fitted on visible-band pixels (the A2 idiom on the B6 ownership discipline; full-mask banding measurably degrades misaligned documents). Rings are meta.band-tagged self-clipped strokes, replaced idempotently on re-runs; 1 = off. Summary under result.refine.shading.")] = 1,
    ):
        """Refine a reconstruction against its source image (the B6 descent pass).

        Recomputes per-pixel paint OWNERSHIP in z-order and refits every evaluable
        paint on its VISIBLE pixels only — the fitting lane samples full masks, so
        overlapped shapes inherit contaminated fits this pass corrects. A refit is
        kept only when its analytic rms improves (the pass can only descend; it is
        deterministic and idempotent). Summary under `result.refine`
        (`refit`/`improved`/`rms_before`/`rms_after`); the refined document
        replaces the session's generated.fg.yaml and is re-rendered. Verify with
        `compare_images` against the same reference.
        """
        result = _logged_enveloped_call(
            log_path,
            "refine_reconstruction",
            {"session_id": session_id, "image": image,
             "raster_png": raster_png, "min_pixels": min_pixels,
             "geometry": geometry, "bands": bands},
            lambda: _uc_refine_reconstruction(
                session_id, image, raster_png=raster_png,
                min_pixels=min_pixels, geometry=geometry, bands=bands,
                session_root=root,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("detect_regions")
    def detect_regions(
        image: Annotated[
            str,
            Field(description="Image to analyze: a filesystem path (raster, or .svg — rasterised first) or a frameforge://session/<id>/page/<n>.png URI."),
        ],
        method: Annotated[str, Field(description=_DESC_REGION_METHOD)] = "consensus",
        cluster: Annotated[
            str | None,
            Field(description="Optionally group regions into shape-equivalence classes: 'translation' (same shape AND orientation — the repeated-tile count) or 'congruent' (same shape, any pose). Adds spatial.classes plus a shape_class per region."),
        ] = None,
        cluster_tol: Annotated[
            float,
            Field(description="Cluster match threshold: translation = minimum top-left-aligned mask IoU; congruent = 1-tol relative feature tolerance."),
        ] = 0.90,
        overlay: Annotated[
            bool,
            Field(description="Render the annotated region overlay PNG as the session's page 1 (regions painted with their sampled fill, borders drawn, a one-line count banner)."),
        ] = True,
        max_regions: Annotated[
            int,
            Field(description="Report at most this many regions (largest area first); spatial.region_count still carries the full count."),
        ] = 400,
        include_polygons: Annotated[
            bool,
            Field(description="Include each region's simplified boundary polygon (+ hole polygons) in image pixels."),
        ] = True,
        fit_spines: Annotated[
            bool,
            Field(description="G1 inverse primitive fitting: attach a `spine` fit to every big-enough region — spine polyline + anchored least-squares cubic (+rms) + width_max + normalized width profile + peak + elongation, the exact parameters sdk.outline.stroke_outline speaks. Feed spine/width_max/profile straight into stroke_outline (spine_profile(profile) makes the callable) to AUTHOR the region as one parametric object instead of tracing it; elongation < ~2 says the region is not spine-like."),
        ] = False,
        tunables: Annotated[dict | None, Field(description=_DESC_REGION_TUNABLES)] = None,
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
    ):
        """Detect an image's closed/filled/stable regions and extract their exact geometry.

        Three methods, one funnel: `closed` finds purely topological enclosed faces
        (line art), `flat` partitions every maximal uniform fill (solid shapes and
        hollow interiors alike, with outline-stroke recovery), and `consensus` keeps
        what an ensemble of mollified level sets agrees on (smooth C-infinity
        boundaries; robust on tangled linework). The `spatial` payload carries each
        region's bbox_px + box_norm + centroid (px and normalized) + sampled fill +
        polygon/holes — coordinates that feed `workspace` pins and
        `construct_vectors` points directly. ⚠ Heuristic output (PALS's Law): verify
        the overlay + numbers against the source.
        """
        result = _logged_enveloped_call(
            log_path,
            "detect_regions",
            {
                "image": image, "method": method, "cluster": cluster,
                "cluster_tol": cluster_tol, "overlay": overlay,
                "max_regions": max_regions, "include_polygons": include_polygons,
                "fit_spines": fit_spines,
                "tunables": tunables, "session_id": session_id,
            },
            lambda: _uc_detect_regions(
                image, method=method, cluster=cluster, cluster_tol=cluster_tol,
                overlay=overlay, max_regions=max_regions,
                include_polygons=include_polygons, fit_spines=fit_spines,
                tunables=tunables,
                session_id=session_id, session_root=root,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("fit_primitives")
    def fit_primitives(
        shapes: Annotated[
            list[dict],
            Field(description="Shapes to fit, as [{\"name\"?: str, \"points\": [[x, y], ...]}] — region boundary polygons or pixel samples (e.g. straight from detect_regions polygons). Each needs >= 3 points."),
        ],
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
    ):
        """Fit parametric primitives to measured point sets — the bridge from
        detected regions to primitives-first authoring.

        For each shape the tool fits a line (PCA: endpoints/angle/length/band
        width), a circle arc (geometrically refined centre/radius/angular
        span/stroke thickness), and an axis-aligned ellipse arc (centre +
        radii), then classifies the best family by like-for-like radial rms —
        an ellipse must show a consistent axis difference above the band's
        noise floor to beat the circle. Returns per-shape `best` plus all
        `candidates` ranked by rms: parameters you type straight into SDK
        primitives instead of tracing paths. ⚠ Heuristic fits (PALS's Law):
        render and compare against the source before trusting them.
        """
        result = _logged_enveloped_call(
            log_path,
            "fit_primitives",
            {"shapes": f"<{len(shapes)} shape(s)>", "session_id": session_id},
            lambda: _uc_fit_primitives(
                shapes=shapes, session_id=session_id, session_root=root,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("diff_renders")
    def diff_renders(
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
        reference_rev: Annotated[
            int | None,
            Field(description="History revision to diff against (rev number from a render result's `history.revisions`). Omit for the revision just before the candidate."),
        ] = None,
        candidate_rev: Annotated[
            int | None,
            Field(description="History revision under test. Omit for the latest archived revision."),
        ] = None,
        page: Annotated[int, Field(description="1-based page whose raster is diffed.")] = 1,
        regions: Annotated[
            list[dict] | None,
            Field(description="Named crops to zoom into, as [{\"name\": str, \"box\": [x, y, w, h]}] normalized 0..1. Omit to auto-split."),
        ] = None,
        grid: Annotated[
            list[int] | None,
            Field(description="Auto-split into a [cols, rows] grid of regions when `regions` is omitted."),
        ] = None,
    ):
        """Diff two archived render revisions of a session — latest vs previous by default.

        Every successful render archives its page artifacts into a history ring
        (last five revisions, reported as `revision` + `history` on the render
        result), so an iteration loop can measure whether a change helped
        instead of remembering. Reuses the compare_images panels + metrics;
        rasters are required (render with raster_png on).
        """
        result = _logged_enveloped_call(
            log_path,
            "diff_renders",
            {
                "session_id": session_id, "reference_rev": reference_rev,
                "candidate_rev": candidate_rev, "page": page,
                "regions": regions, "grid": grid,
            },
            lambda: _uc_diff_renders(
                session_id=session_id, session_root=root,
                reference_rev=reference_rev, candidate_rev=candidate_rev,
                page=page, regions=regions, grid=grid,
            ),
        )
        return _maybe_call_tool_result(result)

    @_reporting_tool("fit_text")
    def fit_text(
        text: Annotated[str, Field(description="Literal text to measure before assigning a box.")],
        font_family: Annotated[
            str | list[str],
            Field(description="Font family or ordered CSS fallback stack, matching text style.font_family."),
        ],
        font_size: Annotated[float, Field(description="Font size in FrameForge px/pt units.", gt=0)],
        bold: Annotated[bool, Field(description="Measure the bold face/weight.")] = False,
        real_metrics: Annotated[
            bool | str,
            Field(description="True/False or 'auto'; use the same value for rendering and overflow checks."),
        ] = "auto",
        font_closure: Annotated[str | None, Field(description=_DESC_FONT_CLOSURE)] = None,
        font_generics: Annotated[
            dict[str, str] | None, Field(description=_DESC_FONT_GENERICS)
        ] = None,
    ):
        """Measure text and return a line-breaker-safe positioned box width.

        The result names the resolved metric mode and includes both the measured
        width and ``fit_width`` (the measurement plus the renderer tolerance).
        Use this before placing per-token or other absolutely positioned text.
        """
        return _plain_tool_result(_logged_enveloped_call(
            log_path,
            "fit_text",
            {
                "text": text,
                "font_family": font_family,
                "font_size": font_size,
                "bold": bold,
                "real_metrics": real_metrics,
                "font_closure": font_closure,
                "font_generics": font_generics,
            },
            lambda: _uc_fit_text(
                text, font_family, font_size, bold, real_metrics,
                font_closure, font_generics),
        ))

    @_reporting_tool("match_font")
    def match_font(
        reference: Annotated[
            str,
            Field(description="Reference image showing the type to match: a filesystem path, a frameforge://session/<id>/page/<n>.png URI, or a data:image/<type>;base64,<payload> URI."),
        ],
        text: Annotated[str, Field(description="The text visible in the reference — each candidate family renders exactly this string for comparison.")],
        candidates: Annotated[
            list[str] | None,
            Field(description="Font families to rank (as list_fonts reports them). Omit to rank the enumerable families, capped at max_candidates."),
        ] = None,
        box: Annotated[
            list[float] | None,
            Field(description="Optional normalized [x, y, w, h] crop of the reference isolating the type sample."),
        ] = None,
        max_candidates: Annotated[
            int, Field(description="Cap when candidates is omitted."),
        ] = 60,
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
    ):
        """Rank resolvable font families by shape similarity to a reference crop.

        Each candidate renders `text` through its fontconfig-resolved file and is
        scored against the ink-cropped reference: height-normalized NCC minus an
        aspect-ratio penalty (condensed vs wide). Returns the ranking plus `best`.
        Heuristic — verify the winner in a real render before committing
        (PALS's Law); unresolvable families are reported, never silently dropped.
        """
        result = _logged_enveloped_call(
            log_path,
            "match_font",
            {
                "reference": reference if len(reference) < 200 else "<inline data URI>",
                "text": text, "candidates": candidates, "box": box,
                "max_candidates": max_candidates, "session_id": session_id,
            },
            lambda: _uc_match_font(
                reference=reference, text=text, candidates=candidates, box=box,
                max_candidates=max_candidates, session_id=session_id,
                session_root=root,
            ),
        )
        return _maybe_call_tool_result(result)

    @server.prompt()
    def frameforge_guide() -> str:
        """Guide to what the FrameForge SDK offers and the server's authoring + proposal tools."""
        return _logged_call(
            log_path,
            "prompt.frameforge_guide",
            {},
            lambda: _live_guide(repo_root=repo),
        )

    @_reporting_tool("get_guide", structured=False)
    def get_guide() -> str:
        """Return the FrameForge capability guide — the same text as the `frameforge_guide` prompt.

        The guide is registered as a prompt, but not every MCP client surfaces
        prompts; this tool is the fallback so any agent can retrieve the full
        SDK + workflow reference in-band.
        """
        return _logged_call(
            log_path,
            "get_guide",
            {},
            lambda: _live_guide(repo_root=repo),
        )

    @_reporting_tool("describe_capabilities")
    def describe_capabilities(
        topic: Annotated[str | None, Field(description=_DESC_TOPIC)] = None,
    ):
        """Runtime discovery of the FrameForge document model (live, read-only introspection).

        Sourced in a fresh interpreter from the configured checkout's authoritative
        Pydantic model (``frameforge.model``), so a long-running server does not
        retain a stale import. The payload includes ``introspected_at`` and a
        source-tree ``source_token``. Omit ``topic`` for the compact capability index; pass a catalog
        topic (``flowables``/``inlines``/``style``/``presets``/``tools``) or a
        type name (``rect``, ``paragraph``, ``document``, ...) for details +
        JSON schema. Use it to look up fields BEFORE authoring instead of
        iterating on validation errors.
        """
        return _plain_tool_result(_logged_enveloped_call(
            log_path,
            "describe_capabilities",
            {"topic": topic},
            lambda: _live_describe_capabilities(
                topic,
                tool_names=_registered_tool_names(server),
                repo_root=repo,
            ),
        ))

    @_reporting_tool("list_fonts")
    def list_fonts(
        family: Annotated[
            str | None,
            Field(description="Optional family name to resolution-check (e.g. 'Inter ExtraLight'): reports what fontconfig actually resolves it to under `resolves`, so a silent substitution is caught BEFORE rendering."),
        ] = None,
        contains: Annotated[
            str | None,
            Field(description="Case-insensitive substring filter for the enumerated families."),
        ] = None,
        limit: Annotated[
            int, Field(description="Return at most this many families (<=0 = all); `family_count` always reports the full match count."),
        ] = 500,
        session_id: Annotated[str | None, Field(description=_DESC_SESSION_ID)] = None,
    ):
        """Enumerate the font families fontconfig can resolve, plus a session's pinned fonts.

        Rendering resolves families via fontconfig, and an unresolved family
        silently substitutes a default face — check availability here first.
        When the session holds a rendered document, its ``defs.tokens.fonts``
        pins are reported as ``pinned_fonts``. Degrades to a structured error
        (with an install hint) when fontconfig is absent.
        """
        return _plain_tool_result(_logged_enveloped_call(
            log_path,
            "list_fonts",
            {"family": family, "contains": contains, "limit": limit, "session_id": session_id},
            lambda: _uc_list_fonts(
                family, contains=contains, limit=limit,
                session_id=session_id, session_root=root,
            ),
        ))

    @_reporting_tool("get_session_resource")
    def get_session_resource(
        uri: Annotated[
            str,
            Field(description="A frameforge://session/<id>/<artifact> URI: document.yaml, document.pdf, diagnostics.json, workspace.json, audit.json, audit.md, page/N.svg, or page/N.png."),
        ],
        mode: Annotated[
            str,
            Field(description="Binary artifacts (png/pdf): 'auto'/'meta' (default) returns reference metadata — bytes, sha256, path — never a blob; 'blob' inlines a base64 copy for SMALL files only (capped by the result budget). Raster pages are already inlined as vision content by the render tools."),
        ] = "auto",
        offset: Annotated[
            int,
            Field(description="Text artifacts: start the returned slice at this character offset (pagination). The result reports total_chars, truncated, and next_offset."),
        ] = 0,
        max_chars: Annotated[
            int | None,
            Field(description="Text artifacts: return at most this many characters (clamped to the slice budget, FRAMEFORGE_MCP_MAX_TEXT_CHARS). Omit for a full budget-sized slice."),
        ] = None,
        query: Annotated[
            str | None,
            Field(description="JSON artifacts only: an RFC 6901 JSON pointer (e.g. '/warnings/0/kind') — returns just that fragment as `value`, the cheapest way to answer a targeted question about diagnostics.json/workspace.json/audit.json."),
        ] = None,
    ):
        """Read a FrameForge MCP session resource by URI, transport-budgeted.

        Text artifacts paginate (``offset``/``max_chars``) and answer targeted
        JSON-pointer ``query`` requests; binary artifacts return reference
        metadata (path + bytes + sha256) unless a small blob is explicitly
        requested. No call ever ships a payload larger than the result budget —
        oversized data stays on disk at the reported ``path``.
        """
        return _plain_tool_result(_logged_enveloped_call(
            log_path,
            "get_session_resource",
            {"uri": uri, "mode": mode, "offset": offset,
             "max_chars": max_chars, "query": query},
            lambda: read_session_resource(
                uri, session_root=root, mode=mode,
                offset=offset, max_chars=max_chars, query=query,
            ),
        ))

    @_reporting_tool("list_sessions")
    def list_sessions():
        """List per-session scratch directories with their artifact counts and size."""
        return _plain_tool_result(_logged_enveloped_call(
            log_path,
            "list_sessions",
            {},
            lambda: _uc_list_sessions(session_root=root),
        ))

    @_reporting_tool("cleanup_sessions")
    def cleanup_sessions(
        session_ids: Annotated[
            list[str] | None,
            Field(description="Remove exactly these session ids. Takes precedence over older_than_seconds."),
        ] = None,
        older_than_seconds: Annotated[
            float | None,
            Field(description="Remove sessions whose directory is older than this many seconds (used only when session_ids is omitted)."),
        ] = None,
        dry_run: Annotated[
            bool, Field(description="Report the selection without deleting anything.")
        ] = False,
    ):
        """Remove session scratch dirs by id or age (no selector removes nothing).

        Hard age-based deletes below the minimum-age floor (60s by default, per-call
        override via FRAMEFORGE_MCP_MIN_CLEANUP_AGE) are refused with ok:false —
        preview with dry_run or target explicit session_ids instead.
        """
        return _plain_tool_result(_logged_enveloped_call(
            log_path,
            "cleanup_sessions",
            {"session_ids": session_ids, "older_than_seconds": older_than_seconds, "dry_run": dry_run},
            lambda: _uc_cleanup_sessions(
                session_root=root,
                session_ids=session_ids,
                older_than_seconds=older_than_seconds,
                dry_run=dry_run,
            ),
        ))

    @server.resource("frameforge://session/{session_id}/document.yaml")
    def session_document(session_id: str) -> str:
        """The validated FrameForge YAML a render tool produced for this session."""
        return _logged_call(
            log_path,
            "resource.session_document",
            {"session_id": session_id},
            lambda: session_resource_endpoint_text(
                f"frameforge://session/{session_id}/document.yaml",
                session_root=root,
            ),
        )

    @server.resource("frameforge://session/{session_id}/page/{page_number}.svg")
    def session_page(session_id: str, page_number: str) -> str:
        """The vector SVG for page N (1-based) — exact geometry; not vision-decodable."""
        page = _positive_int(page_number, "page_number")
        return _logged_call(
            log_path,
            "resource.session_page",
            {"session_id": session_id, "page_number": page_number},
            lambda: session_resource_endpoint_text(
                f"frameforge://session/{session_id}/page/{page}.svg",
                session_root=root,
            ),
        )

    @server.resource(
        "frameforge://session/{session_id}/page/{page_number}.png", mime_type="image/png"
    )
    def session_page_png(session_id: str, page_number: str) -> bytes:
        """The rasterized PNG for page N (1-based) — the vision-decodable render to verify against."""
        page = _positive_int(page_number, "page_number")
        return _logged_call(
            log_path,
            "resource.session_page_png",
            {"session_id": session_id, "page_number": page_number},
            lambda: session_resource_endpoint_bytes(
                f"frameforge://session/{session_id}/page/{page}.png",
                session_root=root,
            ),
        )

    @server.resource(
        "frameforge://session/{session_id}/document.pdf", mime_type="application/pdf"
    )
    def session_document_pdf(session_id: str) -> bytes:
        """The assembled vector PDF — present after a render tool ran with to='pdf'."""
        return _logged_call(
            log_path,
            "resource.session_document_pdf",
            {"session_id": session_id},
            lambda: session_resource_endpoint_bytes(
                f"frameforge://session/{session_id}/document.pdf",
                session_root=root,
            ),
        )

    @server.resource("frameforge://session/{session_id}/diagnostics.json")
    def session_diagnostics(session_id: str) -> str:
        """The full result of the last call in this session — validation issues, render
        metadata, subprocess streams, and the complete `spatial` coordinate payload
        (coordinate system, regions, landmarks, crop transforms, pins) that the tool
        response summarizes. Read this for the exact numbers behind a measurement."""
        return _logged_call(
            log_path,
            "resource.session_diagnostics",
            {"session_id": session_id},
            lambda: session_resource_endpoint_text(
                f"frameforge://session/{session_id}/diagnostics.json",
                session_root=root,
            ),
        )

    @server.resource("frameforge://session/{session_id}/workspace.json")
    def session_workspace(session_id: str) -> str:
        """The persisted `workspace` state for this session: the bound image, the pin
        set (ids, image-pixel coordinates, groups, labels), and the current viewport.
        Present only after `workspace` action='open'; this is what makes pins survive
        across calls for multi-pass reconstruction."""
        return _logged_call(
            log_path,
            "resource.session_workspace",
            {"session_id": session_id},
            lambda: session_resource_endpoint_text(
                f"frameforge://session/{session_id}/workspace.json",
                session_root=root,
            ),
        )

    return server


def run() -> None:
    """Run the FrameForge MCP server over the default FastMCP transport."""
    create_server().run()


__all__ = [
    "create_server",
    "run",
    "run_sdk_code",
    "run_sdk_client",
    "render_frameforge_yaml",
    "design_audit",
    "propose_from_image",
    "propose_from_document",
    "propose_from_svg",
    "compare_images",
    "fit_text",
    "measure_image",
    "mark_points",
    "overlay_images",
    "workspace",
    "construct_vectors",
    "detect_regions",
    "score_reconstruction",
    "map_coordinates",
    "vectorize_image",
    "list_sdk_clients",
    "read_sdk_client",
    "write_sdk_client",
    "read_session_resource",
    "list_sessions",
    "cleanup_sessions",
    "describe_capabilities",
    "list_fonts",
    "mcp_content_blocks",
    "get_default_session_root",
    "get_default_repo_root",
    "FRAMEFORGE_GUIDE",
]
