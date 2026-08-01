"""Layer planning + order validation — "no detail before structure" (review Stage 6).

The single most valuable rule the review surfaced: bad vector art fails because
detail is laid over weak structure. This module encodes the canonical stage
stack and a deterministic validator that flags a layer authored before the
layers it depends on (detail before silhouette/forms; shadows before colors).
"""
from __future__ import annotations

from dataclasses import dataclass, field

STAGES: tuple[str, ...] = (
    "00_canvas",
    "01_guides",
    "02_construction",
    "03_silhouette",
    "04_forms",
    "05_details",
    "06_line_art",
    "07_flat_colors",
    "08_shadows",
    "09_highlights",
    "10_texture",
)

# (predicate on a layer name) -> substrings that must appear in an EARLIER layer.
_DEP_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("detail", ("silhouette", "forms")),     # detail needs stable structure first
    ("line", ("silhouette",)),               # line art traces the established silhouette
    ("shadow", ("color",)),                  # shadows fall on flat colours
    ("highlight", ("shadow",)),              # highlights sit over shadows
    ("texture", ("color",)),
)


@dataclass
class LayerPlan:
    layers: list[str] = field(default_factory=lambda: list(STAGES))


def create_plan(extra: list[str] | None = None) -> LayerPlan:
    """Return the canonical stage stack, optionally appending ``extra`` layers."""
    layers = list(STAGES)
    if extra:
        layers.extend(extra)
    return LayerPlan(layers)


def validate_order(layers: list[str]) -> list[str]:
    """Return human-readable issues for any layer authored before its dependency.

    Empty list == a disciplined order. Matching is by case-insensitive substring
    so callers may use richer names (``03_base_silhouette`` still matches
    ``silhouette``). This is the deterministic guard behind the silhouette gate.
    """
    issues: list[str] = []
    lower = [n.lower() for n in layers]
    for idx, name in enumerate(lower):
        earlier = lower[:idx]
        for trigger, needs in _DEP_RULES:
            if trigger in name:
                for need in needs:
                    if not any(need in e for e in earlier):
                        issues.append(
                            f"'{layers[idx]}' is a {trigger} layer but no '{need}' "
                            f"layer precedes it — establish {need} before {trigger}.")
    return issues


__all__ = ["STAGES", "LayerPlan", "create_plan", "validate_order"]
