"""Tunable constants and environment-variable readers for the MCP server.

Every limit, cap, timeout, and pattern the server enforces is declared here so
the policy lives in one place. The ``_positive_env`` / ``_truthy_env`` helpers are
the only sanctioned way to read an override from the environment.
"""
from __future__ import annotations

import os
import re


SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
# Wall-clock budget for the code-execution subprocess. A build that exceeds it is
# reported as a structured ``ok:false`` (see ``_subprocess_timeout_result``), not a
# raised traceback. 20s leaves headroom for heavier decks (3D meshes, large fixtures)
# while still bounding a runaway client; callers can raise it per call.
DEFAULT_TIMEOUT_SECONDS = 20
MAX_CODE_BYTES = 200_000
MAX_CLIENT_BYTES = 2_000_000
DEFAULT_CLIENT_ROOTS = ("static/examples",)
BUILD_FUNCTION_NAMES = ("build", "build_deck", "build_book", "build_package")
FRAMEFORGE_YAML_PATTERNS = ("*.fg.yaml", "*.fg.yml", "*.frameforge.yaml", "*.frameforge.yml")
STRUCTURED_LOG_SCHEMA = "frameforge_mcp.structured_log.v1"

# Vision models can only decode raster image bytes; SVG is not a viewable image
# media type, so an ``image/svg+xml`` content block reaches the model as an
# undecodable payload (silently dropped at best). Only these mimes are emitted as
# image content blocks — SVG stays a resource link / text artifact.
VIEWABLE_IMAGE_MIME = ("image/png", "image/jpeg", "image/gif", "image/webp")
# The in-process SVG renderer is not subprocess-isolated; a pathological (but
# schema-valid) document could spin without bound. This soft ceiling caps the
# response latency. Honest limit: it bounds the *response*, not the CPU work — a
# runaway render keeps running in a detached daemon thread until it finishes.
DEFAULT_RENDER_TIMEOUT_SECONDS = 30
# Hard input ceilings for the in-process render. The render runs in a daemon thread
# bounded only by a *soft* timeout (the thread is not force-killed — Python cannot
# interrupt CPU-bound bytecode), so a pathological document could leave a thread
# spinning. These caps refuse an obviously-runaway document *before* the thread starts,
# bounding the work it can ever do; the timeout stays the backstop for in-budget slow
# renders. Set generously so real decks never hit them; env-overridable.
DEFAULT_RENDER_MAX_PAGES_HARD = 200
DEFAULT_RENDER_MAX_OBJECTS = 50_000
# Rasterization is far heavier than the SVG render: every page launches a fresh
# headless Chromium. To keep a many-page deck from stalling (or dropping) the stdio
# loop, the raster lane is bounded by a page cap and a soft wall-clock budget; pages
# beyond the bound keep their SVG render and are surfaced as a ``render_warning``.
# Both are env-overridable (``FRAMEFORGE_MCP_RASTER_MAX_PAGES`` / ``_RASTER_TIMEOUT``).
DEFAULT_RASTER_MAX_PAGES = 8
DEFAULT_RASTER_TIMEOUT_SECONDS = 60
# A vision result may carry many raster pages, but inlining every PNG as an image
# content block bloats the response (base64) and risks transport limits. Only the
# first N PNGs are inlined; the rest remain reachable as resource links. Override
# with ``FRAMEFORGE_MCP_MAX_INLINE_IMAGES``.
DEFAULT_MAX_INLINE_IMAGES = 4
# Structured-log hygiene: rotate the JSONL once it crosses this size and clamp
# any single oversized instruction/response string so one giant payload cannot
# bloat (or leak) the whole log.
STRUCTURED_LOG_MAX_BYTES = 5_000_000
STRUCTURED_LOG_MAX_FIELD_CHARS = 20_000
# The MCP tool result mirrors the full run dict as ``structuredContent``, which many
# clients inject into the model context. Subprocess stdout/stderr are unbounded, so a
# chatty SDK script could bloat the conversation. The transported copy clamps the
# streams to this budget; the library result and the on-disk diagnostics resource keep
# the full streams for debugging.
TRANSPORT_STREAM_MAX_CHARS = 10_000
# Env var name fragments that almost always carry a secret. The code-execution
# subprocess runs untrusted SDK code, so these are stripped from its environment
# unless ``FRAMEFORGE_MCP_KEEP_ENV`` is truthy. Matching is case-insensitive.
SECRET_ENV_RE = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE", re.IGNORECASE)
# Key-value secret literals inside logged text (``API_KEY = "..."``, ``token: '...'``,
# ``Authorization: Bearer ...``). The structured log records every instruction and
# response verbatim, so a secret pasted into submitted SDK code would land on disk in
# cleartext; ``logging._redact_secrets`` masks the VALUE with ``[REDACTED]`` before the
# event is written, keeping the key name visible for debugging. Key-name fragments
# mirror ``SECRET_ENV_RE``; the value capture is deliberately conservative — only a
# quoted literal or a bearer-style token qualifies — so ordinary code
# (``token = get_token()``, ``fill = "red"``, ``max_tokens: 4096``) is never mangled.
SECRET_LITERAL_RE = re.compile(
    r"(?P<key>[A-Za-z0-9_-]*(?:api[_-]?key|access[_-]?key|secret|token|password|passwd"
    r"|credential|private[_-]?key|authorization|bearer)[A-Za-z0-9_-]*)"
    r"(?P<sep>[\"']?\s*[:=]\s*)"
    r"(?P<value>\"[^\"\n]+\"|'[^'\n]+'|Bearer[ \t]+[A-Za-z0-9._~+/-]+=*)",
    re.IGNORECASE,
)
# A hard delete driven by ``older_than_seconds`` below this floor is almost always a
# mistake: ``older_than_seconds=0`` matches EVERY session and wipes the whole scratch
# root in one call. ``cleanup_sessions`` refuses below-floor hard deletes with a
# structured error (``dry_run`` previews and the explicit ``session_ids`` selector are
# exempt); override per call via ``FRAMEFORGE_MCP_MIN_CLEANUP_AGE``.
DEFAULT_MIN_CLEANUP_AGE_SECONDS = 60
# The whole transported tool result — the JSON text block AND the mirrored
# structuredContent — lands in the client's model context, and clients enforce
# their own token caps by REJECTING the entire result (a ~124KB PDF blob once
# became a 165K-char response the client threw away after paying for the
# transfer). The server therefore refuses to emit any single result larger than
# this budget: the shared envelope replaces an oversized payload with a small
# structured summary (sizes, salvaged scalars, remediation), so the same
# failure costs a few hundred chars and is actionable in one round-trip.
DEFAULT_MAX_RESULT_CHARS = 60_000
# Default page size for a text-artifact slice served by ``get_session_resource``
# (offset/max_chars pagination). Kept below the result budget so a full slice
# plus its envelope always fits.
DEFAULT_MAX_TEXT_CHARS = 40_000
# Serializing a payload into the result envelope costs keys, quotes, and
# indentation around it; the blob/text caps subtract this allowance from the
# result budget so the *enveloped* result stays under budget too.
RESULT_BUDGET_OVERHEAD_CHARS = 2_000


def max_result_chars() -> int:
    """The per-result transport budget (``FRAMEFORGE_MCP_MAX_RESULT_CHARS``)."""
    return _positive_env("FRAMEFORGE_MCP_MAX_RESULT_CHARS", DEFAULT_MAX_RESULT_CHARS)


def max_text_chars() -> int:
    """The text-slice page size, clamped under the result budget."""
    requested = _positive_env("FRAMEFORGE_MCP_MAX_TEXT_CHARS", DEFAULT_MAX_TEXT_CHARS)
    ceiling = max(max_result_chars() - RESULT_BUDGET_OVERHEAD_CHARS, 256)
    return min(requested, ceiling)


def max_blob_bytes() -> int:
    """The largest binary an opt-in ``mode="blob"`` may inline.

    Derived from the result budget: base64 inflates bytes by 4/3, so the byte
    cap is whatever encodes to a payload that still fits under the budget with
    envelope overhead."""
    b64_budget = max(max_result_chars() - RESULT_BUDGET_OVERHEAD_CHARS, 256)
    return (b64_budget // 4) * 3


def max_resource_bytes() -> int:
    """Byte cap for the registered binary resource endpoints
    (``FRAMEFORGE_MCP_MAX_RESOURCE_BYTES``; defaults to the blob cap)."""
    return _positive_env("FRAMEFORGE_MCP_MAX_RESOURCE_BYTES", max_blob_bytes())


def publish_root():
    """Durable root for published session artifacts
    (``FRAMEFORGE_MCP_PUBLISH_ROOT``). ``None`` = publishing disabled: render
    tools refuse ``publish=true`` with a structured error instead of silently
    dropping the request."""
    from pathlib import Path

    configured = os.environ.get("FRAMEFORGE_MCP_PUBLISH_ROOT", "").strip()
    return Path(configured).expanduser() if configured else None


def _positive_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return default


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
