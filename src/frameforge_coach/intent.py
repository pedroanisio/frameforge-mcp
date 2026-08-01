"""Intent normalization — structure a free-text brief, fill sane defaults.

A deterministic heuristic scaffold (review §A): it never blocks on missing
constraints, it supplies defaults the model can override. It does not "understand"
the subject — that's the model's job — it just gives the loop a typed starting
brief instead of a raw string.
"""
from __future__ import annotations

from dataclasses import dataclass

from frameforge_coach.style import STYLES

_PERSPECTIVES = {
    "front": "front", "side": "side", "profile": "side",
    "three quarter": "three_quarter", "three-quarter": "three_quarter", "3/4": "three_quarter",
    "top-down": "top_down", "top down": "top_down", "overhead": "top_down",
    "low-angle": "low_angle", "low angle": "low_angle", "from below": "low_angle",
    "isometric": "isometric", "iso ": "isometric",
}


@dataclass
class DrawingIntent:
    subject: str
    style: str = "clean_line"
    perspective: str = "three_quarter"
    mood: str = ""
    width: int = 1600
    height: int = 1200
    detail_level: str = "medium-high"


def parse_intent(text: str, **overrides) -> DrawingIntent:
    """Heuristically structure ``text`` into a :class:`DrawingIntent` with defaults.

    Detects a known style name and a perspective phrase from the text; everything
    else falls back to a sensible default. Pass keyword ``overrides`` (e.g.
    ``width=2000``) to pin any field explicitly.
    """
    low = text.lower()
    style = next((name for name in STYLES if name.replace("_", " ") in low or name in low),
                 "clean_line")
    perspective = "three_quarter"
    for phrase, value in _PERSPECTIVES.items():
        if phrase in low:
            perspective = value
            break
    di = DrawingIntent(subject=text.strip(), style=style, perspective=perspective)
    for key, value in overrides.items():
        if hasattr(di, key):
            setattr(di, key, value)
    return di


__all__ = ["DrawingIntent", "parse_intent"]
