"""MCP content-block shaping and transport-stream bounding.

Only raster (PNG) renders become image blocks; SVG is a resource link. The
model-facing structuredContent has its subprocess streams clamped here.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from frameforge_mcp.config import (
    DEFAULT_MAX_INLINE_IMAGES,
    TRANSPORT_STREAM_MAX_CHARS,
    VIEWABLE_IMAGE_MIME,
)


def _max_inline_images() -> int:
    """Cap on how many raster pages are inlined as image content blocks (env-overridable)."""
    raw = os.environ.get("FRAMEFORGE_MCP_MAX_INLINE_IMAGES")
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return DEFAULT_MAX_INLINE_IMAGES


def mcp_content_blocks(result: dict[str, Any]) -> list[dict[str, str]]:
    """Return MCP-style text/image content blocks for a run result.

    Only raster renders (:data:`VIEWABLE_IMAGE_MIME`) become image blocks — SVG is
    not a vision-decodable media type, so it is reported as a resource link in the
    text summary instead of an undecodable image payload. At most
    :func:`_max_inline_images` PNGs are inlined; any beyond that remain reachable as
    resource links (the summary reports ``images_total`` vs ``images_inlined``) so a
    many-page deck does not bloat the response with base64.
    """
    image_renders = [
        render
        for render in result.get("renders", [])
        if render.get("path") and str(render.get("mimeType")) in VIEWABLE_IMAGE_MIME
    ]
    cap = _max_inline_images()
    summary = {
        "ok": result.get("ok"),
        "session_id": result.get("session_id"),
        "yaml_uri": result.get("yaml_uri"),
        "diagnostics_uri": result.get("diagnostics_uri"),
        "validation": result.get("validation"),
        "renders": [
            {key: render.get(key) for key in ("page", "uri", "mimeType", "sha256") if key in render}
            for render in result.get("renders", [])
        ],
        "render_warning": result.get("render_warning"),
        "error": result.get("error"),
        "images_total": len(image_renders),
        "images_inlined": min(len(image_renders), cap),
    }
    if result.get("signed"):
        summary["signed"] = result.get("signed")
    if result.get("hint"):
        # structured failures carry an actionable next step; keep it next to the
        # error in the model-facing summary instead of only in structuredContent.
        summary["hint"] = result.get("hint")
    if result.get("pdf"):
        # the to='pdf' lane reports its outcome (path/uri/pages, or a structured
        # failure with its own install hint) — surface it so the export result is
        # visible without a diagnostics round-trip.
        summary["pdf"] = result.get("pdf")
    if result.get("replaced_renders"):
        # cross-tool session reuse just overwrote a prior tool's renders; the
        # summary names the prior tool so the silent-clobber case stays visible.
        summary["replaced_renders"] = result.get("replaced_renders")
    if result.get("comparison"):
        # compare_images carries per-region pixel-match hints; surface them in the
        # text summary so the score sits next to the inlined comparison panels.
        summary["comparison"] = result.get("comparison")
    if result.get("spatial"):
        # measure_image carries the exact coordinate system / regions / landmarks /
        # crop transforms; surface them so the numbers sit next to the inlined
        # overlay (the whole point is a reliable coordinate reference).
        summary["spatial"] = result.get("spatial")
    if result.get("score"):
        # score_reconstruction carries the edge-match convergence numbers; surface
        # them so on_edge_frac/mean_dist sit next to the inlined match overlay.
        summary["score"] = result.get("score")
    if not result.get("ok"):
        # Surface the failure's traceback tail inline so the caller can diagnose
        # without a second round-trip to the diagnostics resource.
        tail = _stderr_tail(result.get("stderr"))
        if tail:
            summary["stderr_tail"] = tail
    blocks: list[dict[str, str]] = [
        {"type": "text", "text": json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)}
    ]
    for render in image_renders[:cap]:
        data = Path(str(render["path"])).read_bytes()
        blocks.append(
            {
                "type": "image",
                "data": base64.b64encode(data).decode("ascii"),
                "mimeType": str(render["mimeType"]),
            }
        )
    return blocks


_STDERR_TAIL_MAX_CHARS = 1600


def _stderr_tail(stderr: Any, *, max_chars: int = _STDERR_TAIL_MAX_CHARS) -> str:
    """The last lines of a subprocess stderr, bounded for the model-facing summary."""
    if not isinstance(stderr, str) or not stderr.strip():
        return ""
    text = stderr.rstrip()
    if len(text) <= max_chars:
        return text
    clipped = text[-max_chars:]
    newline = clipped.find("\n")
    if newline != -1:
        clipped = clipped[newline + 1:]
    return "…\n" + clipped


def _clamp_stream(text: str, limit: int) -> str:
    """Clamp an oversized subprocess stream, keeping its head and tail.

    A traceback's signal lives at both ends — where it started and the final
    exception line — so the middle is dropped with a marker rather than truncating
    one end. A stream within ``limit`` is returned unchanged.
    """
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    omitted = len(text) - limit
    return f"{text[:head]}\n…[{omitted} chars truncated]…\n{text[-tail:]}"


def _bounded_transport_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``result`` with subprocess streams bounded for transport.

    Only the model-facing ``structuredContent`` is clamped; the original result
    (returned to direct callers such as the live server) and the on-disk diagnostics
    keep the full ``stdout``/``stderr``, which stay reachable via the diagnostics
    resource. When nothing exceeds the budget the original object is returned as-is.
    """
    oversized = [
        key
        for key in ("stdout", "stderr")
        if isinstance(result.get(key), str) and len(result[key]) > TRANSPORT_STREAM_MAX_CHARS
    ]
    if not oversized:
        return result
    bounded = dict(result)
    for key in oversized:
        bounded[key] = _clamp_stream(result[key], TRANSPORT_STREAM_MAX_CHARS)
    return bounded


def _maybe_call_tool_result(result: dict[str, Any]):
    try:
        from mcp.types import CallToolResult, ImageContent, TextContent
    except ImportError:
        return result

    content = []
    for block in mcp_content_blocks(result):
        if block["type"] == "text":
            content.append(TextContent(type="text", text=block["text"]))
        elif block["type"] == "image":
            content.append(
                ImageContent(
                    type="image",
                    data=block["data"],
                    mimeType=block["mimeType"],
                )
            )
    return CallToolResult(
        content=content,
        structuredContent=_bounded_transport_result(result),
        isError=not result.get("ok", False),
    )
