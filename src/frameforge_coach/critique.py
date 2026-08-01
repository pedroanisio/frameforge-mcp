"""Critique rubrics — the deterministic checklist; the *judgement* is the VLM's.

The review's hardest warning: a critic that emits a confident ``0.78`` it cannot
justify is the PALS's-Law trap. So the coach ships only the per-stage *rubric*
(what to look at) as deterministic text. The model/VLM renders the stage and
answers the rubric against the pixels — and that answer is explicitly an
advisory opinion, never presented as a measurement.
"""
from __future__ import annotations

RUBRICS: dict[str, list[str]] = {
    "construction": [
        "Do the volumes sit on a single, consistent perspective/scale?",
        "Is the gesture / action line readable?",
        "Are overlaps resolving depth correctly (nothing ambiguous)?",
    ],
    "silhouette": [
        "Can the subject be recognized from the solid black shape alone?",
        "Is the focal point clear, or do shapes merge into a blob?",
        "Does the pose read as intentional at small size?",
        "STOP if this fails — fix gesture/scale/occlusion before any detail.",
    ],
    "style": [
        "Are outer contours heavier than inner detail (weight hierarchy)?",
        "Is the palette limited to the style's colours?",
        "Is negative space preserved (not cluttered)?",
        "Any drift from the named style's rules?",
    ],
    "detail": [
        "Does every detail follow the underlying form/perspective?",
        "Does detail reinforce the focal point rather than scatter attention?",
        "Is detail density consistent with the style's level?",
    ],
    "final": [
        "Subject reads in < 2 seconds.",
        "Composition is balanced with deliberate negative space.",
        "Colour/line/contrast are consistent across the whole image.",
    ],
}


def stage_rubric(stage: str) -> list[str]:
    """Return the readability/quality checklist for a named stage.

    Unknown stage names fall back to the ``final`` rubric so the loop never
    silently has nothing to check.
    """
    return list(RUBRICS.get(stage, RUBRICS["final"]))


__all__ = ["RUBRICS", "stage_rubric"]
