"""Image-agnostic contour/line cleanup — the generalizable lever from vela-nova.

The proportion/landmark/canon machinery there is human-specific and does NOT
generalize. What does, for ANY subject (figure, rocket, city, icon), is the
extraction-quality work on the *lines themselves*: simplify the polylines
(Ramer–Douglas–Peucker, bounded deviation), drop speckle, and lightly smooth.
These operate purely on point geometry — no anatomy, no priors — so they lift
every traced image: far fewer nodes (cleaner, editable, smaller) at a bounded
shape change.
"""
from __future__ import annotations

import copy
import math
from typing import Any

Obj = dict[str, Any]
_PTS = {"polyline", "polygon"}


def _bbox_diag(pts: list) -> float:
    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys)) if xs else 0.0


def _perp(p, a, b) -> float:
    """Perpendicular distance of point ``p`` to segment ``a``–``b``."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _rdp(points: list, eps: float) -> list:
    """Ramer–Douglas–Peucker decimation (iterative; no recursion-limit risk).

    Returns a subset of ``points`` whose max deviation from the original
    polyline is <= ``eps`` — so shape is preserved within a known tolerance.
    """
    pts = [(float(x), float(y)) for x, y in points]
    n = len(pts)
    if n < 3:
        return [list(p) for p in pts]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        s, e = stack.pop()
        dmax, idx = 0.0, -1
        for i in range(s + 1, e):
            d = _perp(pts[i], pts[s], pts[e])
            if d > dmax:
                dmax, idx = d, i
        if dmax > eps and idx != -1:
            keep[idx] = True
            stack.append((s, idx))
            stack.append((idx, e))
    return [list(pts[i]) for i in range(n) if keep[i]]


def denoise_strokes(objs: list[Obj], *, min_span: float = 6.0) -> list[Obj]:
    """Drop speckle: point-objects whose bounding-box diagonal < ``min_span``."""
    out: list[Obj] = []
    for o in objs:
        if o.get("type") in _PTS and o.get("points") and _bbox_diag(o["points"]) < min_span:
            continue
        out.append(copy.deepcopy(o))
    return out


def simplify_strokes(objs: list[Obj], *, eps: float = 1.5) -> list[Obj]:
    """RDP-simplify every polyline/polygon. Geometry kept within ``eps`` px."""
    out: list[Obj] = []
    for o in objs:
        o = copy.deepcopy(o)
        if o.get("type") in _PTS and o.get("points") and len(o["points"]) > 2:
            o["points"] = _rdp(o["points"], eps)
        out.append(o)
    return out


def smooth_strokes(objs: list[Obj], *, strength: float = 0.5) -> list[Obj]:
    """Light moving-average on interior vertices (endpoints fixed; count kept)."""
    s = max(0.0, min(1.0, strength))
    out: list[Obj] = []
    for o in objs:
        o = copy.deepcopy(o)
        pts = o.get("points")
        if o.get("type") in _PTS and pts and len(pts) > 2:
            p = [[float(x), float(y)] for x, y in pts]
            sm = [p[0]]
            for i in range(1, len(p) - 1):
                ax = (p[i - 1][0] + p[i + 1][0]) / 2.0
                ay = (p[i - 1][1] + p[i + 1][1]) / 2.0
                sm.append([p[i][0] * (1 - s) + ax * s, p[i][1] * (1 - s) + ay * s])
            sm.append(p[-1])
            o["points"] = sm
        out.append(o)
    return out


def clean(objs: list[Obj], *, min_span: float = 6.0, eps: float = 1.5,
          smooth: float = 0.0) -> list[Obj]:
    """Denoise → simplify (→ optionally smooth). The one-call general cleanup."""
    out = simplify_strokes(denoise_strokes(objs, min_span=min_span), eps=eps)
    return smooth_strokes(out, strength=smooth) if smooth else out


def node_count(objs: list[Obj]) -> int:
    """Total polyline/polygon vertices — the cleanliness/editability metric."""
    return sum(len(o["points"]) for o in objs if o.get("type") in _PTS and o.get("points"))


__all__ = ["denoise_strokes", "simplify_strokes", "smooth_strokes", "clean", "node_count"]
