"""The agent-facing guide must describe an SDK that actually exists.

`guide.py` is the server's contract with the agent: it is where a model learns
which SDK calls to reach for. A name in there that the SDK does not export is
worse than an undocumented feature — the agent writes code that cannot run, and
nothing catches it until the tool call fails.

This suite pins the SDK surface the guide promises. It is deliberately a curated
list rather than a regex over every backtick: the guide also names methods,
keyword arguments and prose, and a scraper over all of those would be noise that
nobody keeps green.
"""
from __future__ import annotations

import inspect

import frameforge_sdk as sdk
import pytest

from frameforge_mcp import guide

#: Top-level names the guide tells agents to import.
PROMISED_EXPORTS = [
    # viewing pipeline
    "ViewingPipeline", "window_to_viewport",
    # 3D scene + drawing
    "Scene3D", "Camera", "multiview",
    "face_vertex_intensities", "gouraud_gradient",
    # rational curves / NURBS / fitting
    "RationalBezier", "circular_arc", "nurbs_curve", "nurbs_surface",
    "hermite", "elevate_degree", "bezier_point",
    "curve_curve_intersections", "fit_cubic",
    # spatial acceleration
    "AABBTree", "Quadtree", "bounds_of",
    # planar kernel the guide cites alongside them
    "fill_regions",
]

#: Pipeline stages the guide lists by name.
PIPELINE_STAGES = [
    "clip_polyline", "clip_polygon", "project_polygon",
    "depth_key", "is_back_face", "fit", "project",
]

#: `Scene3D.render` keyword arguments the guide documents.
RENDER_KWARGS = ["shading", "cull_backfaces", "near_clip", "depth_sort", "pipeline"]

SHADING_MODES = ["none", "flat", "lambert", "smooth", "gouraud", "phong"]
DEPTH_SORTS = ["average", "newell", "none"]
HIDDEN_MODES = ["omit", "dash", "show"]


@pytest.mark.parametrize("name", PROMISED_EXPORTS)
def test_every_promised_export_exists(name):
    assert hasattr(sdk, name), f"guide.py names `{name}`, which frameforge_sdk does not export"
    assert name in sdk.__all__, f"`{name}` is reachable but missing from __all__"


@pytest.mark.parametrize("name", PROMISED_EXPORTS)
def test_every_promised_export_is_actually_mentioned_in_the_guide(name):
    """The other direction: this list must not rot into a list of things the
    guide stopped talking about."""
    assert name in guide.__doc__ or _guide_text().count(name), f"`{name}` is no longer in the guide"


def _guide_text() -> str:
    return inspect.getsource(guide)


@pytest.mark.parametrize("stage", PIPELINE_STAGES)
def test_viewing_pipeline_exposes_every_stage_the_guide_lists(stage):
    assert callable(getattr(sdk.ViewingPipeline, stage, None))


@pytest.mark.parametrize("kwarg", RENDER_KWARGS)
def test_scene3d_render_accepts_every_documented_keyword(kwarg):
    assert kwarg in inspect.signature(sdk.Scene3D.render).parameters


def test_scene3d_has_the_wireframe_renderer_the_guide_promises():
    params = inspect.signature(sdk.Scene3D.wireframe).parameters
    assert "hidden" in params
    assert "pipeline" in params


@pytest.mark.parametrize("mode", SHADING_MODES)
def test_every_documented_shading_mode_is_accepted(mode):
    scene = sdk.Scene3D().extrude([[0, 0], [1, 0], [1, 1]], 0.5)
    scene.render(box=[0, 0, 40, 40], shading=mode)


@pytest.mark.parametrize("mode", DEPTH_SORTS)
def test_every_documented_depth_sort_is_accepted(mode):
    scene = sdk.Scene3D().extrude([[0, 0], [1, 0], [1, 1]], 0.5)
    scene.render(box=[0, 0, 40, 40], depth_sort=mode)


@pytest.mark.parametrize("mode", HIDDEN_MODES)
def test_every_documented_hidden_line_mode_is_accepted(mode):
    scene = sdk.Scene3D().extrude([[0, 0], [1, 0], [1, 1]], 0.5)
    scene.wireframe(box=[0, 0, 40, 40], hidden=mode)


def test_multiview_accepts_the_wireframe_switch_the_guide_documents():
    params = inspect.signature(sdk.multiview).parameters
    assert "wireframe" in params
    assert "hidden" in params


def test_gouraud_is_the_only_interpolating_mode_as_documented():
    """The guide makes a specific claim about which mode interpolates. If that
    ever stops being true the guide is lying to every agent that reads it."""
    scene = sdk.Scene3D().revolve([[0.0, -1.0], [0.7, 0.0], [0.0, 1.0]], segments=8)
    cam = sdk.Camera(eye=sdk.Vec3(2.5, 2.0, 3.0))

    def has_gradient(mode: str) -> bool:
        group = scene.render(box=[0, 0, 120, 120], camera=cam, shading=mode)
        return any(isinstance(c.get("fill"), dict) for c in group["children"])

    assert has_gradient("gouraud")
    for flat_mode in ("none", "flat", "lambert", "smooth", "phong"):
        assert not has_gradient(flat_mode), f"{flat_mode} is documented as per-face"


def test_the_exact_conic_claim_in_the_guide_holds():
    """The guide justifies the rational curves by claiming a cubic carries
    ~2.7e-4 radial error while a rational quadratic is exact. Both halves."""
    import math

    arc = sdk.circular_arc(radius=1.0, sweep_angle=90.0)
    assert max(abs(math.hypot(arc.point(i / 40).x, arc.point(i / 40).y) - 1.0)
               for i in range(41)) < 1e-12

    k = sdk.quarter_circle_kappa()
    cubic = sdk.CubicBezier(sdk.Vec2(1, 0), sdk.Vec2(1, k), sdk.Vec2(k, 1), sdk.Vec2(0, 1))
    worst = max(abs(math.hypot(cubic.point(i / 40).x, cubic.point(i / 40).y) - 1.0)
                for i in range(41))
    assert 1e-5 < worst < 1e-3, f"the documented ~2.7e-4 approximation error is now {worst}"
