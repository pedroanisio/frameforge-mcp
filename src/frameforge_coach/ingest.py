"""Ingest a raster into editable objects, then re-skin them to a StyleProfile.

This is the seam that joins the two halves of the session: the vision/vectorize
lane (raster → FrameForge objects) and the coach's style grammar (objects →
on-brand look). ``ingest`` lazily imports OpenCV (the ``vision`` group) so the
rest of ``frameforge_coach`` stays importable without it; ``recolor_to_style``
and ``gradientize`` are pure, geometry-preserving transforms — unit-testable
with no extra deps.
"""
from __future__ import annotations

import copy
from typing import Any

from frameforge_coach.style import StyleProfile

Obj = dict[str, Any]
_STROKE_TYPES = {"polyline", "line", "path"}
_FILL_TYPES = {"polygon", "rect", "ellipse", "circle", "path"}


def ingest(image: str, *, mode: str = "outline", colors: int = 8, detail: float = 0.0016,
           min_area: float = 24.0, max_dim: int = 1500) -> tuple[list[Obj], int, int]:
    """Vectorize a raster into FrameForge objects (lazy OpenCV import; ``vision`` group).

    ``mode="outline"`` returns open stroke paths (the line-art); ``mode="region"``
    returns closed, fillable polygons. Returns ``(objects, width, height)``. Raises a
    clear error if the vision group is not installed.
    """
    try:
        from frameforge_vision.infrastructure.vectorize import raster_to_objects
    except ImportError as exc:  # pragma: no cover - depends on optional group
        raise RuntimeError(
            "coach.ingest needs the vision group: `uv sync --group vision`"
        ) from exc
    return raster_to_objects(image, mode=mode, colors=colors, detail=detail,
                             min_area=min_area, max_dim=max_dim)


def _hexshift(hexc: str, amt: float) -> str:
    h = hexc.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return hexc
    def adj(c: int) -> int:
        c = c + amt * (255 - c) if amt >= 0 else c * (1 + amt)
        return max(0, min(255, int(round(c))))
    return "#%02X%02X%02X" % (adj(r), adj(g), adj(b))


def recolor_to_style(objs: list[Obj], style: StyleProfile, *, width: float | None = None) -> list[Obj]:
    """Re-skin ingested objects to ``style``: fills cycle the palette, strokes take
    the style ink (palette[0]) and a stroke weight. Geometry is never touched."""
    ink = style.palette[0]
    w = (style.inner or style.outer) if width is None else width
    pal = list(style.palette)
    out: list[Obj] = []
    i = 0
    for o in objs:
        o = copy.deepcopy(o)
        if o.get("type") in _FILL_TYPES and isinstance(o.get("fill"), str) and o["fill"] != "none":
            o["fill"] = pal[i % len(pal)]
            i += 1
        if o.get("type") in _STROKE_TYPES and isinstance(o.get("stroke"), str) and o["stroke"] != "none":
            o["stroke"] = ink
            if w:
                ss = dict(o.get("stroke_style") or {})
                ss["stroke_width"] = w
                o["stroke_style"] = ss
        out.append(o)
    return out


def gradientize(objs: list[Obj], *, angle: str = "120deg", light: float = 0.2,
                dark: float = -0.18) -> list[Obj]:
    """Lift every flat fill into a 2-stop linear gradient. Geometry untouched."""
    out: list[Obj] = []
    for o in objs:
        o = copy.deepcopy(o)
        f = o.get("fill")
        if o.get("type") in _FILL_TYPES and isinstance(f, str) and f != "none":
            o["fill"] = {"kind": "linear", "angle": angle,
                         "stops": [{"color": _hexshift(f, light), "position": "0%"},
                                   {"color": _hexshift(f, dark), "position": "100%"}]}
        out.append(o)
    return out


__all__ = ["ingest", "recolor_to_style", "gradientize"]
