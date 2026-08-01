"""The silhouette gate — the centerpiece reuse of the existing renderer.

Flatten any FrameForge document to solid black-on-white so the construction can
be judged for *readability* before any detail is added (review Stage 6: "Can the
subject be recognized in black silhouette?"). It reuses the SDK render path
entirely — this is a doc transform, not a new renderer.
"""
from __future__ import annotations

import copy
from typing import Any

from frameforge_sdk.author import DocumentBuilder
from frameforge_sdk.model import validate_document


def _as_dict(doc: Any) -> dict[str, Any]:
    if isinstance(doc, DocumentBuilder):
        return doc.build_dict()
    if hasattr(doc, "model_dump"):
        return doc.model_dump(by_alias=True, exclude_none=True)
    if isinstance(doc, dict):
        return doc
    raise TypeError(f"to_silhouette expects a DocumentBuilder/Document/dict, got {type(doc)!r}")


def _canvas_wh(page: dict[str, Any]) -> tuple[float, float]:
    c = page.get("canvas")
    if isinstance(c, dict) and isinstance(c.get("size"), (list, tuple)) and len(c["size"]) >= 2:
        return float(c["size"][0]), float(c["size"][1])
    return 1280.0, 800.0


def _is_background(obj: dict[str, Any], w: float, h: float) -> bool:
    box = obj.get("box")
    return (obj.get("type") == "rect" and isinstance(box, (list, tuple)) and len(box) >= 4
            and float(box[2]) >= 0.95 * w and float(box[3]) >= 0.95 * h)


def _recolor(obj: Any, ink: str, paper: str, wh: tuple[float, float]) -> None:
    if not isinstance(obj, dict):
        return
    w, h = wh
    bg = _is_background(obj, w, h)
    target = paper if bg else ink
    if "fill" in obj and obj.get("fill") not in (None, "none"):
        obj["fill"] = target
    elif bg:
        obj["fill"] = paper
    if "stroke" in obj and obj.get("stroke") not in (None, "none"):
        obj["stroke"] = paper if bg else ink
    for k in ("glow", "shadow"):
        obj.pop(k, None)
    st = obj.get("style")
    if isinstance(st, dict):
        st.pop("glow", None)
        st.pop("shadow", None)
        if "color" in st:
            st["color"] = ink
    for span in obj.get("spans", []) or []:
        sp = span.get("style") if isinstance(span, dict) else None
        if isinstance(sp, dict) and "color" in sp:
            sp["color"] = ink
    for child in obj.get("children", []) or []:
        _recolor(child, ink, paper, wh)


def to_silhouette(doc: Any, *, ink: str = "#000000", paper: str = "#FFFFFF"):
    """Return a validated ``Document`` with every object flattened to ink-on-paper.

    Backgrounds (full-canvas rects) become ``paper``; every other shape, line and
    glyph becomes solid ``ink``; glows/shadows/gradients are dropped. The result
    round-trips through :func:`validate_document` and the SDK renderer unchanged,
    so callers raster it with the normal render tools and run the readability
    judgement (a VLM opinion — advisory, not a measurement) on the PNG.
    """
    data = copy.deepcopy(_as_dict(doc))
    for page in data.get("pages", []):
        wh = _canvas_wh(page)
        for layer in page.get("layers", []):
            for obj in layer.get("objects", []):
                _recolor(obj, ink, paper, wh)
    return validate_document(data)


__all__ = ["to_silhouette"]
