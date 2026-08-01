"""End-to-end coach composition — a raster (or pre-traced objects) to one doc.

Wires the coach stages into a single call so the whole pipeline is one unit (and
one MCP tool): ingest → clean → redraw → recolor/gradientize → paint atmosphere,
assembled into a layer-plan-ordered FrameForge document.

Two seams:
- :func:`compose_objects` is pure (SDK only) — given already-traced region/outline
  objects it builds the styled document, so it is unit-testable without OpenCV.
- :func:`compose_from_image` adds the raster ingest in front (lazy OpenCV via
  ``coach.ingest``), the form the CLI and the MCP tool call.

Boundary: imports only ``frameforge_sdk`` + intra-package (no ``tooling``).
"""
from __future__ import annotations

import copy
from typing import Any, Optional, Sequence, Union

from frameforge_coach.clean import clean
from frameforge_coach.ingest import gradientize, recolor_to_style
from frameforge_coach.paint import atmosphere, lightest
from frameforge_coach.redraw import redraw
from frameforge_coach.style import StyleProfile, cleanup_params, redraw_params, resolve_style
from frameforge_sdk.author import DocumentBuilder

Obj = dict[str, Any]


def _place(objs: Sequence[Obj], box: Sequence[float], src: Sequence[float]) -> list[Obj]:
    """Fit ``src``-sized geometry into ``box`` (centered) via a style.transform."""
    bx, by, bw, bh = box
    sw, sh = src
    s = min(bw / sw, bh / sh) if sw and sh else 1.0
    tx, ty = bx + (bw - sw * s) / 2, by + (bh - sh * s) / 2
    pre = f"translate({tx:.3f} {ty:.3f}) scale({s:.5f})"
    out: list[Obj] = []
    for o in objs:
        o = copy.deepcopy(o)
        st = dict(o.get("style") or {})
        st["transform"] = f"{pre} {st['transform']}" if st.get("transform") else pre
        o["style"] = st
        out.append(o)
    return out


def compose_objects(
    region: Sequence[Obj],
    outline: Sequence[Obj],
    src: tuple[int, int],
    *,
    style: StyleProfile,
    paint: bool = True,
    canvas_width: int = 1280,
    title: Optional[str] = None,
) -> DocumentBuilder:
    """Assemble traced region/outline objects into a styled FrameForge document.

    Layer order follows the plan: atmosphere(back) → flat colours → line art →
    atmosphere(front). ``region`` fills are re-skinned to ``style`` and
    gradientised; ``outline`` is cleaned and redrawn to Bézier strokes — both
    parameterised by the style grammar. Pure (no OpenCV); fully unit-testable.
    """
    w, h = src
    W = int(canvas_width)
    H = max(1, round(W * h / w)) if w else int(canvas_width)
    box = [0, 0, W, H]

    b = DocumentBuilder(title=title or "coach-compose", lang="en")
    page = b.page("composed", canvas={"size": [W, H], "units": "px"}, coordinate_mode="absolute")

    # opaque base so the atmosphere/vignette has something to sit on
    base = lightest(style.palette) if paint else "#FFFFFF"
    page.layer("00_base").rect(box, fill=base, decorative=True)

    atm = atmosphere(style, W, H) if paint else {"back": [], "front": []}
    if atm["back"]:
        bg = page.layer("01_atmosphere_back")
        for o in atm["back"]:
            bg.add(o)

    if region:
        fills = gradientize(recolor_to_style(list(region), style))
        fl = page.layer("07_flat_colors")
        for o in _place(fills, box, src):
            fl.add(o)

    if outline:
        ink = redraw(clean(list(outline), **cleanup_params(style)),
                     **redraw_params(style), stroke=style.palette[0])
        li = page.layer("06_line_art")
        for o in _place(ink, box, src):
            li.add(o)

    if atm["front"]:
        fr = page.layer("09_highlights")
        for o in atm["front"]:
            fr.add(o)
    return b


def compose_from_image(
    image: str,
    *,
    style: Union[str, Sequence[str], StyleProfile] = "children_book",
    modes: Sequence[str] = ("region", "outline"),
    paint: bool = True,
    canvas_width: int = 1280,
    colors: int = 8,
    min_area: float = 120.0,
    detail: float = 0.0018,
    max_dim: int = 1100,
    title: Optional[str] = None,
) -> DocumentBuilder:
    """Ingest ``image`` and compose a styled coach document (lazy OpenCV).

    ``style`` may be a name, several names (hybrid), or a resolved StyleProfile.
    Raises ``RuntimeError`` if the optional vision group (OpenCV) is absent.
    """
    from frameforge_coach.ingest import ingest

    sty = style if isinstance(style, StyleProfile) else resolve_style(
        *([style] if isinstance(style, str) else list(style)))

    region: list[Obj] = []
    outline: list[Obj] = []
    w = h = None
    if "region" in modes:
        region, w, h = ingest(image, mode="region", colors=colors, min_area=min_area, max_dim=max_dim)
    if "outline" in modes:
        outline, w, h = ingest(image, mode="outline", detail=detail,
                               min_area=max(12.0, min_area / 6), max_dim=max(max_dim, 1400))
    if w is None:
        from frameforge_vision.infrastructure.vectorize import image_size
        w, h = image_size(image)
    return compose_objects(region, outline, (w, h), style=sty, paint=paint,
                           canvas_width=canvas_width, title=title or "coach-compose")


__all__ = ["compose_objects", "compose_from_image"]
