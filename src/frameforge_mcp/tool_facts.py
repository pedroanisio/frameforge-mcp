"""What each tool does to the caller's environment — the source of truth for MCP hints.

MCP lets a server declare, per tool, whether a call is read-only, whether it may
destroy existing state, whether repeating it changes anything, and whether it
reaches beyond this machine. Hosts gate approval on those four booleans, so the
difference between ``list_fonts`` (reads fontconfig) and ``run_sdk_code`` (runs
untrusted Python in a subprocess ``security_posture()`` reports as
``sandboxed: false``) has to be *declared*, not merely true.

The table lives here rather than on the 35 decorators for one reason: a
classification scattered across a 2000-line composition root cannot be checked.
Here it is data, so ``tests/test_tool_surface.py`` can assert that every
registered tool has an entry, that the live server publishes exactly these
values, and — the guard that matters — that no tool claiming ``read_only``
reaches a filesystem-writing primitive.

``writes`` is the *reason* for the verdict, not decoration: a non-read-only tool
must name what it touches, which is what makes a wrong entry visible in review.

Definitions follow the MCP spec:

``read_only``
    The call does not modify its environment. Implies ``idempotent`` and
    forbids ``destructive``.
``destructive``
    The call may overwrite or remove state that already existed. Additive-only
    work (writing a new artifact beside the old ones) is *not* destructive.
``idempotent``
    Repeating the call with the same arguments has no effect beyond the first.
    Under-claiming is safe; over-claiming tells a host a retry is free when it
    is not, so anything non-deterministic stays ``False``.
``open_world``
    The call may interact with entities outside this machine.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolFacts:
    """The declared environmental contract of one MCP tool."""

    title: str
    read_only: bool
    destructive: bool
    idempotent: bool
    open_world: bool = False
    #: Short phrases naming what a non-read-only call touches. Empty when read-only.
    writes: tuple[str, ...] = ()


def _reads(title: str) -> ToolFacts:
    """A pure read: no mutation, therefore idempotent and never destructive."""
    return ToolFacts(title=title, read_only=True, destructive=False, idempotent=True)


def _adds(title: str, *writes: str, idempotent: bool = True) -> ToolFacts:
    """Additive-only: creates artifacts without destroying what was there."""
    return ToolFacts(
        title=title,
        read_only=False,
        destructive=False,
        idempotent=idempotent,
        writes=writes,
    )


def _replaces(title: str, *writes: str, idempotent: bool = False, open_world: bool = False) -> ToolFacts:
    """Destructive: overwrites or removes state the caller may still want."""
    return ToolFacts(
        title=title,
        read_only=False,
        destructive=True,
        idempotent=idempotent,
        open_world=open_world,
        writes=writes,
    )


#: Every render/measure tool clears the session's previous outputs before it
#: writes new ones (``sessions._reset_session_outputs``), so only the LAST call's
#: artifacts survive. That is a destructive update to the session scratchpad, and
#: the server's own failure hints already warn callers about it.
_SESSION_RESET = "resets this session's page-*.svg / p*.png and diagnostics.json"

TOOL_FACTS: dict[str, ToolFacts] = {
    # -- Contract / migration: pure functions over YAML text -------------------
    "list_deprecated_forms": _reads("List deprecated forms"),
    "migrate_deprecated_forms": _reads("Migrate deprecated forms"),
    # -- Discovery: the cheap first step, so it must be free to call -----------
    "describe_capabilities": _reads("Describe document-model capabilities"),
    "get_guide": _reads("Get the FrameForge guide"),
    "list_fonts": _reads("List resolvable fonts"),
    "fit_text": _reads("Measure text fit"),
    "list_sessions": _reads("List sessions"),
    "get_session_resource": _reads("Read a session resource"),
    "diff_renders": _reads("Diff two render revisions"),
    "describe_render": _reads("Describe a render (VLM)"),
    # -- SDK client files ------------------------------------------------------
    "list_sdk_clients": _reads("List SDK clients"),
    "read_sdk_client": _reads("Read an SDK client"),
    "write_sdk_client": _replaces(
        "Write an SDK client",
        "creates or overwrites a .py file under the editable client roots",
        # `append=True` adds more text on every call, so a repeat is NOT free.
        idempotent=False,
    ),
    # -- Author -> render. Arbitrary Python: the widest blast radius here. -----
    "run_sdk_code": _replaces(
        "Run SDK code",
        "executes untrusted Python in an un-sandboxed subprocess",
        _SESSION_RESET,
        idempotent=False,
        open_world=True,
    ),
    "run_sdk_client": _replaces(
        "Run an SDK client",
        "executes untrusted Python in an un-sandboxed subprocess",
        _SESSION_RESET,
        idempotent=False,
        open_world=True,
    ),
    "render_frameforge_yaml": _replaces(
        "Render FrameForge YAML",
        _SESSION_RESET,
        # No Python runs: the same document renders to the same pages.
        idempotent=True,
    ),
    "design_audit": _adds(
        "Audit design tokens",
        "writes audit.json / audit.md beside the session's existing artifacts",
    ),
    # -- Image -> draft: CV/VLM proposals, explicitly unverified ---------------
    "propose_from_image": _replaces("Propose a draft from an image", _SESSION_RESET),
    "propose_from_document": _replaces("Propose a draft from a PDF page", _SESSION_RESET),
    "propose_from_svg": _replaces("Propose a draft from an SVG", _SESSION_RESET),
    "coach_vectorize": _replaces("Coach: vectorize an image", _SESSION_RESET),
    # -- Visual QA and the coordinate workspace --------------------------------
    "compare_images": _replaces("Compare two images", _SESSION_RESET, idempotent=True),
    "measure_image": _replaces("Measure an image", _SESSION_RESET, idempotent=True),
    "mark_points": _replaces("Mark points on an image", _SESSION_RESET, idempotent=True),
    "overlay_images": _replaces("Overlay two images", _SESSION_RESET, idempotent=True),
    "map_coordinates": _replaces("Map coordinates between frames", _SESSION_RESET, idempotent=True),
    "detect_regions": _replaces("Detect image regions", _SESSION_RESET, idempotent=True),
    "score_reconstruction": _replaces("Score a reconstruction", _SESSION_RESET, idempotent=True),
    "workspace": _replaces(
        "Coordinate workspace",
        "mutates the persisted pin board (workspace.json)",
        _SESSION_RESET,
        idempotent=False,
    ),
    "construct_vectors": _replaces("Construct vectors from points", _SESSION_RESET, idempotent=True),
    "vectorize_image": _replaces(
        "Vectorize an image",
        "removes and rewrites the session's trace working directory",
        _SESSION_RESET,
        idempotent=False,
    ),
    "refine_reconstruction": _replaces("Refine a reconstruction", _SESSION_RESET, idempotent=False),
    "fit_primitives": _adds("Fit primitives to points", "creates the session directory"),
    "match_font": _adds("Match a font to a reference", "creates the session directory"),
    # -- Session lifecycle -----------------------------------------------------
    "cleanup_sessions": _replaces(
        "Clean up sessions",
        "permanently deletes session scratch directories",
        # Deleting an already-deleted session leaves the same end state.
        idempotent=True,
    ),
}


def tool_facts(name: str) -> ToolFacts:
    """The declared facts for *name*.

    Raises ``KeyError`` rather than inventing a permissive default: an
    unclassified tool must fail loudly at registration, because the failure mode
    of a silent default is a destructive tool published as safe.
    """
    try:
        return TOOL_FACTS[name]
    except KeyError:
        raise KeyError(
            f"tool {name!r} has no entry in frameforge_mcp.tool_facts.TOOL_FACTS — "
            "classify it (read-only? destructive? idempotent? open-world?) before "
            "registering it, so hosts can gate approval on the answer"
        ) from None


def tool_kwargs(name: str) -> dict[str, Any]:
    """Keyword arguments for ``@server.tool(...)`` carrying this tool's declaration.

    Degrades to ``{}`` when the ``mcp`` types are unavailable (the test doubles
    register plain callables), so the annotation layer never becomes a hard
    import dependency of registration.
    """
    facts = tool_facts(name)
    try:
        from mcp.types import ToolAnnotations
    except ImportError:  # pragma: no cover - mcp is a base dependency
        return {}
    return {
        "title": facts.title,
        "annotations": ToolAnnotations(
            title=facts.title,
            readOnlyHint=facts.read_only,
            destructiveHint=facts.destructive,
            idempotentHint=facts.idempotent,
            openWorldHint=facts.open_world,
        ),
    }


def tool_facts_report() -> dict[str, Any]:
    """The whole table as JSON — what ``describe_capabilities(topic='tools')`` serves.

    Clients that do not surface ``tools/list`` annotations (and agents reasoning
    about which call is safe to retry) can read the same declaration in-band
    instead of guessing from the tool name.
    """
    return {
        "schema": "frameforge_mcp.tool_facts.v1",
        "hint_semantics": {
            "read_only": "the call does not modify its environment",
            "destructive": "the call may overwrite or remove pre-existing state",
            "idempotent": "repeating the call with the same arguments changes nothing further",
            "open_world": "the call may interact with entities outside this machine",
        },
        "tools": {
            name: {
                "title": facts.title,
                "read_only": facts.read_only,
                "destructive": facts.destructive,
                "idempotent": facts.idempotent,
                "open_world": facts.open_world,
                "writes": list(facts.writes),
            }
            for name, facts in sorted(TOOL_FACTS.items())
        },
    }


__all__ = ["TOOL_FACTS", "ToolFacts", "tool_facts", "tool_facts_report", "tool_kwargs"]
