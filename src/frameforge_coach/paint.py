"""Atmosphere & depth — the render-safe painting layer for the colour stages.

The coach can ingest, clean, and *recolour* geometry (``ingest`` / ``clean`` /
``recolor_to_style`` / ``gradientize``), but flat fills read as "filled", not
"painted". This module adds the depth cues a finished illustration has — soft
glow, atmospheric haze, a unifying wash, a vignette — for the ``07_flat_colors``
→ ``09_highlights`` stages of the layer plan.

Hard constraint baked in (verified, not assumed): the browser-free rasteriser
(cairosvg) renders gradients + alpha but DROPS SVG blur filters and
``mix-blend-mode``. So every primitive here fakes soft light with *transparent
gradient stops* — nothing relies on an effect that silently disappears on the
fallback path. (A browser/resvg rasteriser would additionally honour the blur
versions; these survive both.)

Boundary: pure dict builders + the ``StyleProfile`` registry — stdlib only, no
``tooling``, no OpenCV. So the primitives are unit-testable everywhere, and
``atmosphere`` is driven by the *resolved coach style* — paint that is on-brand
by construction.
"""
from __future__ import annotations

from typing import Any, Sequence

from frameforge_coach.style import StyleProfile

Obj = dict[str, Any]
Stop = dict[str, Any]


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _luma(hex_color: str) -> float:
    r, g, b = _rgb(hex_color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def fade(hex_color: str, alpha: float) -> str:
    """A colour at a given alpha as ``rgba(...)`` — the building block of soft light.

    Transparent gradient stops are how we fake glow/haze without a blur filter
    (which cairosvg drops). ``alpha`` is clamped to [0, 1]."""
    r, g, b = _rgb(hex_color)
    a = max(0.0, min(1.0, alpha))
    return f"rgba({r}, {g}, {b}, {a:g})"


def stop(color: str, position: float) -> Stop:
    """A gradient stop at ``position`` (a fraction 0..1 -> percent)."""
    return {"color": color, "position": f"{position * 100:g}%"}


def linear(stops: Sequence[Stop], angle: str = "180deg") -> dict[str, Any]:
    return {"kind": "linear", "angle": angle, "stops": list(stops)}


def radial(stops: Sequence[Stop], at: str = "50% 50%") -> dict[str, Any]:
    return {"kind": "radial", "at": at, "stops": list(stops)}


def glow(cx: float, cy: float, r: float, color: str = "#FFF3D0", *,
         core: float = 0.95, spread: float = 2.4) -> list[Obj]:
    """A soft light source: a bright core plus a wide halo fading to transparent."""
    halo = radial([stop(fade(color, 0.55), 0.0), stop(fade(color, 0.22), 0.45),
                   stop(fade(color, 0.0), 1.0)])
    disc = radial([stop(fade(color, core), 0.0), stop(fade(color, core * 0.9), 0.6),
                   stop(fade(color, 0.0), 1.0)])
    return [
        {"type": "ellipse", "center": [cx, cy], "rx": r * spread, "ry": r * spread, "fill": halo},
        {"type": "ellipse", "center": [cx, cy], "rx": r, "ry": r, "fill": disc},
    ]


def vignette(w: float, h: float, *, color: str = "#0A0E16", strength: float = 0.5) -> Obj:
    """A frame-darkening oval: transparent centre -> ``color`` at the edges."""
    return {"type": "rect", "box": [0, 0, w, h],
            "fill": radial([stop(fade(color, 0.0), 0.0), stop(fade(color, 0.0), 0.62),
                            stop(fade(color, strength), 1.0)], at="50% 48%")}


def haze(box: Sequence[float], color: str = "#DCEBFF", *, opacity: float = 0.35,
         angle: str = "180deg") -> Obj:
    """Atmospheric depth: ``color`` fading to transparent across ``box``."""
    x, y, bw, bh = box
    return {"type": "rect", "box": [x, y, bw, bh],
            "fill": linear([stop(fade(color, opacity), 0.0), stop(fade(color, 0.0), 1.0)], angle)}


def wash(box: Sequence[float], top: str, bottom: str, *, opacity: float = 0.25,
         angle: str = "180deg") -> Obj:
    """A unifying light gradient over the whole frame (low opacity)."""
    x, y, bw, bh = box
    return {"type": "rect", "box": [x, y, bw, bh],
            "fill": linear([stop(fade(top, opacity), 0.0), stop(fade(bottom, opacity), 1.0)], angle)}


def soft_shadow(cx: float, cy: float, rx: float, ry: float, *, color: str = "#0A1428",
                strength: float = 0.4) -> Obj:
    """A contact/cast shadow: a radial blob fading out (no blur filter needed)."""
    return {"type": "ellipse", "center": [cx, cy], "rx": rx, "ry": ry,
            "fill": radial([stop(fade(color, strength), 0.0), stop(fade(color, 0.0), 1.0)])}


def lightest(palette: Sequence[str]) -> str:
    """The highest-luminance colour in a palette (the natural light source)."""
    return max(palette, key=_luma)


def darkest(palette: Sequence[str]) -> str:
    """The lowest-luminance colour in a palette (the natural ink/vignette)."""
    return min(palette, key=_luma)


def atmosphere(style: StyleProfile, w: float, h: float, *,
               light: tuple[float, float] = (0.5, 0.42),
               vignette_strength: float = 0.36) -> dict[str, list[Obj]]:
    """Style-driven depth: returns ``{"back": [...], "front": [...]}`` to wrap a scene.

    ``back`` (an ambient wash + a soft key-light glow drawn from the palette's
    lightest colour) goes UNDER the subject; ``front`` (a vignette in the
    palette's darkest colour) goes OVER it. The look is on-brand by construction —
    it is built from the resolved :class:`StyleProfile` palette, not hand-picked.
    """
    pal = list(style.palette)
    key = lightest(pal)
    ink = darkest(pal)
    lx, ly = light[0] * w, light[1] * h
    back: list[Obj] = [
        {"type": "rect", "box": [0, 0, w, h],
         "fill": linear([stop(fade(key, 0.16), 0.0), stop(fade(ink, 0.12), 1.0)], "180deg")},
        *glow(lx, ly, min(w, h) * 0.10, key, core=0.45, spread=3.2),
    ]
    front: list[Obj] = [vignette(w, h, color=ink, strength=vignette_strength)]
    return {"back": back, "front": front}


__all__ = [
    "fade", "stop", "linear", "radial", "glow", "vignette", "haze", "wash",
    "soft_shadow", "lightest", "darkest", "atmosphere",
]
