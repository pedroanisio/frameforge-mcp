"""Style as grammar — named styles resolved into executable vector rules.

The review's §9 point: a model generalizes across styles only when "cyberpunk
ukiyo-e" becomes *constraints* (line weights, palette, fill mode, hatch, detail
density) rather than adjectives. This is a small, deterministic registry of
those constraints; the model reads them and the SDK enforces them.
"""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class StyleProfile:
    """Executable vector rules for a named visual style."""

    name: str
    outer: float          # outer-contour stroke weight (px)
    inner: float          # inner-structure stroke weight
    detail: float         # fine-detail stroke weight
    fill: str             # "flat" | "none" | "duotone"
    palette: tuple[str, ...]
    hatch: str            # "none" | "sparse" | "dense" | "woodcut"
    detail_level: str     # "low" | "medium" | "high"
    edge: str             # "clean_closed" | "sketchy" | "carved"


STYLES: dict[str, StyleProfile] = {
    "flat_icon": StyleProfile(
        "flat_icon", outer=0, inner=0, detail=0, fill="flat",
        palette=("#6D28D9", "#22D3EE", "#FFFFFF", "#1E2030"),
        hatch="none", detail_level="low", edge="clean_closed"),
    "clean_line": StyleProfile(
        "clean_line", outer=4, inner=1.6, detail=0.9, fill="flat",
        palette=("#1E2030", "#F5F3FF", "#6D28D9"),
        hatch="sparse", detail_level="medium", edge="clean_closed"),
    "blueprint": StyleProfile(
        "blueprint", outer=2, inner=1.2, detail=0.6, fill="none",
        palette=("#0B5FBF", "#9FD0FF", "#08315F"),
        hatch="sparse", detail_level="medium", edge="clean_closed"),
    "comic_ink": StyleProfile(
        "comic_ink", outer=5, inner=2.2, detail=1.2, fill="flat",
        palette=("#111114", "#FFFFFF", "#E0653C", "#3B6EA5"),
        hatch="dense", detail_level="high", edge="clean_closed"),
    "woodcut": StyleProfile(
        "woodcut", outer=4.5, inner=2.0, detail=1.0, fill="duotone",
        palette=("#1A1A1A", "#F3EAD6"),
        hatch="woodcut", detail_level="high", edge="carved"),
    "children_book": StyleProfile(
        "children_book", outer=3, inner=1.4, detail=0.8, fill="flat",
        palette=("#F6A823", "#43B0A0", "#E0653C", "#3B6EA5", "#FFF7E8"),
        hatch="none", detail_level="medium", edge="clean_closed"),
}

_DETAIL_ORDER = ("low", "medium", "high")
_HATCH_ORDER = ("none", "sparse", "dense", "woodcut")


def resolve_style(*names: str) -> StyleProfile:
    """Resolve one style name to its profile, or merge several into a hybrid.

    A single known name returns the registered profile unchanged. Several names
    merge with explicit precedence: line discipline (weights/edge) comes from the
    FIRST named style, the palette is the de-duplicated union, and ``hatch`` /
    ``detail_level`` take the most expressive of the inputs. Unknown names fall
    back to ``clean_line`` rather than raising — the model can still proceed.
    """
    known = [STYLES[n] for n in names if n in STYLES]
    if not known:
        return STYLES["clean_line"]
    if len(known) == 1 and len(names) == 1:
        return known[0]
    base = known[0]
    palette: tuple[str, ...] = tuple(dict.fromkeys(c for s in known for c in s.palette))
    hatch = max((s.hatch for s in known), key=lambda h: _HATCH_ORDER.index(h))
    detail = max((s.detail_level for s in known), key=lambda d: _DETAIL_ORDER.index(d))
    return replace(base, name="+".join(s.name for s in known),
                   palette=palette, hatch=hatch, detail_level=detail)


def apply_to_layerplan(style: StyleProfile, layers: list[str]) -> dict[str, dict]:
    """Map style rules onto the layers that consume them (line / color / shadow)."""
    out: dict[str, dict] = {}
    for layer in layers:
        n = layer.lower()
        if "line" in n:
            out[layer] = {"outer": style.outer, "inner": style.inner, "detail": style.detail,
                          "edge": style.edge}
        elif "color" in n or "flat" in n:
            out[layer] = {"palette": list(style.palette), "fill": style.fill}
        elif "shadow" in n:
            out[layer] = {"method": "flat" if style.fill == "flat" else "hatch",
                          "hatch": style.hatch}
        elif "texture" in n:
            out[layer] = {"hatch": style.hatch, "detail_level": style.detail_level}
    return out


def cleanup_params(style: StyleProfile) -> dict:
    """Derive ``coach.clean`` kwargs from a style — how aggressively to decimate.

    Detail level sets the RDP tolerance (low detail → simplify hard; high detail →
    keep nodes). The edge character sets smoothing: ``sketchy`` keeps the hand
    jitter (no smoothing), ``carved`` a touch, ``clean_closed`` the most. So the
    same trace is cleaned to match the named style, not a fixed default.
    """
    eps = {"low": 3.2, "medium": 1.8, "high": 1.0}.get(style.detail_level, 1.8)
    smooth = {"sketchy": 0.0, "carved": 0.2, "clean_closed": 0.45}.get(style.edge, 0.3)
    min_span = 8.0 if style.detail_level == "low" else 6.0
    return {"min_span": min_span, "eps": eps, "smooth": smooth}


def redraw_params(style: StyleProfile) -> dict:
    """Derive ``coach.redraw`` kwargs from a style — line weight, simplify, snap.

    The stroke ``width`` is the style's own line weight (outer contour, falling
    back to inner). ``simplify_tol`` tracks detail level. ``snap`` (blob →
    primitive) is enabled only for ``clean_closed`` edges — a geometric/icon look
    wants clean primitives; ``sketchy``/``carved`` styles keep organic contours.
    """
    simplify_tol = {"low": 3.5, "medium": 2.0, "high": 1.2}.get(style.detail_level, 2.0)
    width = style.outer or style.inner or 1.4
    return {"simplify_tol": simplify_tol, "width": width, "snap": style.edge == "clean_closed"}


__all__ = ["StyleProfile", "STYLES", "resolve_style", "apply_to_layerplan",
           "cleanup_params", "redraw_params"]
