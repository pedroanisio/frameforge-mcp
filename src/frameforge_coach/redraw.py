"""Redraw the line-art — rough traced contours → clean, intentional strokes.

The ``06_line_art`` stage of the layer plan. ``coach.clean`` decimates and lightly
smooths *polylines* (the points stay a polyline); this module goes further and
re-draws them: each stroke becomes a smooth Catmull-Rom **cubic-Bézier path**, and
a contour that is really a circle or a box is **snapped to a clean primitive**
(``ellipse`` / ``rect``). The result is deliberate vector line-art, not a
mechanical contour dump.

It reuses ``coach.clean``'s RDP simplification (one implementation of the
decimation lever) and the SDK's ``Path`` builder for the Béziers — so it stays
within the package boundary (``frameforge_sdk`` + stdlib, no ``tooling``) and adds
no duplicate geometry code.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Iterable, Sequence

from frameforge_coach.clean import simplify_strokes
from frameforge_sdk import Path

Obj = dict[str, Any]
Pt = Sequence[float]
_PTS = {"polyline", "polygon"}


# --------------------------------------------------------------------------- #
# Primitive recognition (pure geometry).
# --------------------------------------------------------------------------- #
def _bbox(points: Sequence[Pt]) -> tuple[float, float, float, float]:
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _poly_area(points: Sequence[Pt]) -> float:
    n = len(points)
    a = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def is_circular(points: Sequence[Pt], tol: float = 0.16) -> bool:
    """True for a blob-circle: vertices near-equidistant from the centroid AND the
    polygon fills ~pi/4 of its bounding box (the area test excludes a square,
    whose corner/edge radii alone can slip under the equidistance threshold)."""
    if len(points) < 6:
        return False
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    rs = [math.hypot(p[0] - cx, p[1] - cy) for p in points]
    mean = sum(rs) / len(rs)
    if mean <= 0:
        return False
    var = sum((r - mean) ** 2 for r in rs) / len(rs)
    if (var ** 0.5) / mean > tol:
        return False
    x0, y0, x1, y1 = _bbox(points)
    box = (x1 - x0) * (y1 - y0)
    fill = _poly_area(points) / box if box > 0 else 0.0
    return 0.6 <= fill <= 0.92          # circle ~= pi/4 (0.785); square ~= 1.0


def is_rectangular(points: Sequence[Pt], tol: float = 0.12) -> bool:
    """True if a 4–6 corner simplification fills ~its bounding box (an axis-ish box)."""
    x0, y0, x1, y1 = _bbox(points)
    span = max(x1 - x0, y1 - y0)
    s = simplify_strokes([{"type": "polygon", "points": [list(p) for p in points]}],
                         eps=max(1.0, 0.02 * span))[0]["points"]
    s = s[:-1] if len(s) > 1 and s[0] == s[-1] else s
    if not 4 <= len(s) <= 6:
        return False
    box = (x1 - x0) * (y1 - y0)
    return box > 0 and _poly_area(points) / box >= (1.0 - tol)


def snap_primitives(objs: Iterable[Obj], *, circ_tol: float = 0.16) -> list[Obj]:
    """Replace near-circular / near-rectangular polygons with clean primitives."""
    out: list[Obj] = []
    for o in objs:
        if o.get("type") == "polygon" and o.get("points") and len(o["points"]) >= 5:
            pts = o["points"]
            x0, y0, x1, y1 = _bbox(pts)
            if is_circular(pts, circ_tol):
                obj = {"type": "ellipse", "center": [(x0 + x1) / 2, (y0 + y1) / 2],
                       "rx": (x1 - x0) / 2, "ry": (y1 - y0) / 2, "fill": o.get("fill", "#000000")}
                _carry_style(o, obj)
                out.append(obj)
                continue
            if is_rectangular(pts):
                obj = {"type": "rect", "box": [x0, y0, x1 - x0, y1 - y0], "fill": o.get("fill", "#000000")}
                _carry_style(o, obj)
                out.append(obj)
                continue
        out.append(copy.deepcopy(o))
    return out


# --------------------------------------------------------------------------- #
# Smooth re-draw (Catmull-Rom -> cubic Bézier paths).
# --------------------------------------------------------------------------- #
def _carry_style(src: Obj, dst: Obj) -> Obj:
    if isinstance(src.get("style"), dict):
        dst["style"] = copy.deepcopy(src["style"])
    return dst


def redraw_smooth(objs: Iterable[Obj], *, simplify_tol: float = 1.5,
                  width: float = 1.4, stroke: str | None = None) -> list[Obj]:
    """Re-emit polylines/polygons as smooth Catmull-Rom ``path`` objects.

    ``simplify_tol`` first RDP-decimates the points (via ``coach.clean``) so the
    curve rides clean control points; ``width``/``stroke`` set the line. Polygons
    stay closed and keep their fill; polylines become open, round-capped strokes.
    Objects that are not polylines/polygons (or are too short) pass through.
    """
    src = simplify_strokes(list(objs), eps=simplify_tol) if simplify_tol > 0 else [copy.deepcopy(o) for o in objs]
    out: list[Obj] = []
    for o in src:
        t = o.get("type")
        pts = o.get("points")
        if t == "polyline" and pts and len(pts) >= 3:
            obj = Path().through(pts).object(
                stroke=stroke or o.get("stroke", "#1E2440"), fill="none",
                stroke_style={"stroke_width": width, "stroke_linecap": "round",
                              "stroke_linejoin": "round"})
            out.append(_carry_style(o, obj))
        elif t == "polygon" and pts and len(pts) >= 3:
            obj = Path().through([*pts, pts[0]]).close().object(fill=o.get("fill", "#000000"))
            out.append(_carry_style(o, obj))
        else:
            out.append(o)
    return out


def redraw(objs: Iterable[Obj], *, simplify_tol: float = 1.5, width: float = 1.4,
           stroke: str | None = None, snap: bool = True, circ_tol: float = 0.16) -> list[Obj]:
    """One-call line-art redraw: snap primitives (optional) → smooth Bézier paths."""
    work = snap_primitives(objs, circ_tol=circ_tol) if snap else list(objs)
    return redraw_smooth(work, simplify_tol=simplify_tol, width=width, stroke=stroke)


def curve_count(objs: Iterable[Obj]) -> int:
    """How many objects are paths whose ``d`` carries a cubic/quad curve command."""
    n = 0
    for o in objs:
        if o.get("type") == "path":
            d = o.get("d")
            s = d if isinstance(d, str) else " ".join(seg[0] for seg in d if seg)
            if "C" in s or "Q" in s or "S" in s:
                n += 1
    return n


__all__ = ["redraw", "redraw_smooth", "snap_primitives", "is_circular",
           "is_rectangular", "curve_count"]
