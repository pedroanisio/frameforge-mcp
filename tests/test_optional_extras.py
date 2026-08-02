"""The optional lanes install their backends, and say so consistently.

The gap this file pins: ``frameforge-mcp[vision]`` declared the *distribution*
``frameforge-vision`` but not the extra that carries its backend, so a full
``uv sync --all-extras`` produced a server whose CV tools all failed with
``No module named 'cv2'``. The same shape hit ``[vlm]`` and ``[pdf]``, which
named their backends but not ``frameforge-vision`` at all.

Three surfaces are asserted together, because the failure was only visible when
they disagreed: the DECLARATION (pyproject + installed metadata), the RUNTIME
report (:mod:`frameforge_mcp.extras` / ``describe_capabilities``), and the
TOOL ENVELOPES that tell a caller how to fix an unavailable lane.
"""
from __future__ import annotations

import importlib.metadata as importlib_metadata
import importlib.util
import re
from pathlib import Path

import pytest
import tomllib

from frameforge_mcp import extras
from frameforge_mcp.discovery import describe_capabilities

REPO = Path(__file__).parents[1]
PROJECT = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
OPTIONAL = PROJECT["project"]["optional-dependencies"]


# --------------------------------------------------------------------------- #
#  The declaration: an extra must install every backend its lane imports       #
# --------------------------------------------------------------------------- #


def test_vision_extra_installs_the_cv_backend():
    """The reported failure: `[vision]` without OpenCV is a dead lane."""
    assert any(
        requirement.startswith("frameforge-vision[") and "cv" in requirement
        for requirement in OPTIONAL["vision"]
    ), f"vision extra must pull frameforge-vision[cv]; got {OPTIONAL['vision']}"


def test_vlm_extra_installs_the_vision_distribution():
    """`describe_render` imports `frameforge_vision.vlm` — torch alone is not enough."""
    assert any(
        requirement.startswith("frameforge-vision") for requirement in OPTIONAL["vlm"]
    ), f"vlm extra must pull frameforge-vision; got {OPTIONAL['vlm']}"


def test_pdf_extra_installs_the_vision_distribution():
    """`propose_from_document` reaches PyMuPDF *through* frameforge_vision."""
    assert any(
        requirement.startswith("frameforge-vision") for requirement in OPTIONAL["pdf"]
    ), f"pdf extra must pull frameforge-vision; got {OPTIONAL['pdf']}"


def test_installed_metadata_agrees_with_the_declared_extras():
    """The built distribution carries the same requirement the source declares.

    pyproject can be fixed while the installed environment still reflects the
    old declaration; that skew is exactly what made the gap survive a green
    test run, so assert the metadata the resolver actually reads.
    """
    # Environment markers may be single- or double-quoted depending on the
    # backend that wrote the metadata; normalise before matching.
    requires = [
        line.replace('"', "'") for line in importlib_metadata.requires("frameforge-mcp") or []
    ]
    vision = [line for line in requires if "extra == 'vision'" in line]
    assert vision, "installed metadata declares no `vision` extra"
    assert any("frameforge-vision[cv]" in line for line in vision), (
        f"installed `vision` extra does not pull the cv backend: {vision}"
    )


# --------------------------------------------------------------------------- #
#  The registry: one table describes the lanes, and it matches pyproject       #
# --------------------------------------------------------------------------- #


def test_every_declared_extra_has_a_lane_and_every_lane_is_a_declared_extra():
    assert {lane.name for lane in extras.LANES} == set(OPTIONAL)


def test_the_vlm_lane_probes_the_image_processor_backend():
    """transformers 5.x split image processors into `pil` / `torchvision`
    backends, and BOTH Idefics3 classes (SmolVLM, the default model) require
    torchvision. Probing only torch + transformers reported the lane available
    and `describe_render` then died inside `AutoProcessor.from_pretrained`."""
    assert "torchvision" in extras.lane("vlm").probes


def test_the_vlm_probes_cover_what_the_vision_package_says_it_needs():
    """Cross-package drift guard.

    `frameforge_vision.vlm.BACKEND_MODULES` is that package's own statement of
    what the lane needs to run. This table is deliberately a separate copy —
    it has to answer before `frameforge_vision` is installed at all — so the two
    can drift. They must not: whatever upstream adds, this lane must probe, or
    the MCP reports available for an environment upstream knows is unusable.
    """
    vision_vlm = pytest.importorskip("frameforge_vision.vlm")

    upstream = set(vision_vlm.BACKEND_MODULES)
    assert upstream <= set(extras.lane("vlm").probes), (
        f"frameforge_vision.vlm needs {sorted(upstream)}; this lane probes "
        f"{sorted(extras.lane('vlm').probes)}"
    )


def test_each_lane_names_the_modules_it_needs_and_the_tools_it_gates():
    vision = extras.lane("vision")
    assert "cv2" in vision.probes
    assert "frameforge_vision" in vision.probes
    assert {"detect_regions", "vectorize_image"} <= set(vision.tools)
    assert "describe_render" in extras.lane("vlm").tools
    assert "propose_from_document" in extras.lane("pdf").tools


def test_pdf_export_lane_installs_its_backend():
    """The `document.pdf` session resource is advertised — something must install pypdf."""
    assert "pdfout" in OPTIONAL
    assert any(r.startswith("pypdf") for r in OPTIONAL["pdfout"]), OPTIONAL["pdfout"]


def test_lane_lookup_rejects_an_unknown_name():
    with pytest.raises(KeyError):
        extras.lane("nope")


# --------------------------------------------------------------------------- #
#  The hints: this distribution ships EXTRAS, not dependency groups            #
# --------------------------------------------------------------------------- #


def test_install_hint_names_a_command_that_exists_in_this_distribution():
    hint = extras.install_hint("vision")
    assert "--extra vision" in hint
    assert "frameforge-mcp[vision]" in hint
    assert "--group" not in hint


def test_no_source_file_tells_a_caller_to_sync_a_group_that_does_not_exist():
    """Regression: `uv sync --group vision` ERRORS here — there is no such group.

    A hint that cannot be run is worse than no hint: the caller believes the
    lane is broken rather than uninstalled. Checked against the groups this
    distribution actually declares, so the guard survives a future real group.
    """
    groups = set(PROJECT.get("dependency-groups", {}))
    pattern = re.compile(r"--group[= ]([A-Za-z0-9_.-]+)")
    offenders = []
    for path in sorted((REPO / "src").rglob("*.py")) + sorted((REPO / "src").rglob("*.md")):
        for name in pattern.findall(path.read_text(encoding="utf-8")):
            if name not in groups:
                offenders.append(f"{path.relative_to(REPO)}: --group {name}")
    assert not offenders, (
        "install hints name a dependency group this distribution does not declare "
        f"(declared: {sorted(groups) or 'none'}): " + "; ".join(offenders)
    )


def test_every_optional_backend_the_code_imports_is_installable_from_an_extra():
    """Regression: `to='pdf'` needed pypdf, which no extra installed at all.

    Every probe module in the lane table must be reachable from the extra that
    declares it — an advertised capability whose backend nothing can install is
    the same defect as one whose extra under-declares.
    """
    declared = " ".join(
        requirement for requirements in OPTIONAL.values() for requirement in requirements
    ) + " " + " ".join(PROJECT["project"]["dependencies"])

    # module import name -> the distribution that provides it
    providers = {
        "cv2": "frameforge-vision",   # via its [cv] extra
        "numpy": "frameforge-vision",
        "PIL": "cairosvg",            # base dependency
        "frameforge_vision": "frameforge-vision",
        "torch": "frameforge-vision",  # via its [vlm] extra
        "transformers": "frameforge-vision",
        "torchvision": "frameforge-vision",
        "fitz": "pymupdf",
        "playwright": "playwright",
        "cairosvg": "cairosvg",
        "pypdf": "pypdf",
    }
    for lane_entry in extras.LANES:
        for module in lane_entry.probes:
            assert module in providers, f"no known provider for probe {module!r}"
            assert providers[module] in declared, (
                f"lane {lane_entry.name!r} probes {module!r}, but nothing declares "
                f"{providers[module]!r}"
            )


# --------------------------------------------------------------------------- #
#  The runtime report                                                          #
# --------------------------------------------------------------------------- #


def test_optional_backends_reports_every_lane_with_its_fix():
    report = extras.optional_backends()

    assert report["distribution"] == "frameforge-mcp"
    assert report["packaging"] == "extras"
    assert set(report["lanes"]) == {lane.name for lane in extras.LANES}
    for name, lane in report["lanes"].items():
        assert isinstance(lane["available"], bool)
        assert lane["install"] == f"uv sync --extra {name}"
        assert lane["pip_install"] == f"pip install 'frameforge-mcp[{name}]'"
        assert set(lane["missing"]) <= set(lane["probes"])
        assert lane["available"] == (not lane["missing"])


def test_a_missing_backend_is_named_module_by_module(monkeypatch):
    real_find_spec = importlib.util.find_spec

    def blind(name, *args, **kwargs):
        if name == "cv2":
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(extras.importlib.util, "find_spec", blind)

    assert extras.missing_modules("vision") == ("cv2",)
    assert extras.lane_available("vision") is False
    report = extras.optional_backends()
    assert report["lanes"]["vision"]["available"] is False
    assert report["lanes"]["vision"]["missing"] == ["cv2"]


def test_a_backend_whose_import_is_broken_counts_as_missing(monkeypatch):
    """`find_spec` raises for a half-installed package — that is unavailable, not a crash."""

    def explode(name, *args, **kwargs):
        raise ValueError(f"{name}.__spec__ is None")

    monkeypatch.setattr(extras.importlib.util, "find_spec", explode)
    assert extras.lane_available("vision") is False


# --------------------------------------------------------------------------- #
#  The MCP discovery surface                                                   #
# --------------------------------------------------------------------------- #


def test_capability_index_reports_lane_availability():
    index = describe_capabilities()

    assert set(index["optional_backends"]) == {lane.name for lane in extras.LANES}
    assert all(isinstance(value, bool) for value in index["optional_backends"].values())


def test_backends_topic_returns_the_full_report_and_is_advertised():
    index = describe_capabilities()
    assert "backends" in index["topics"]

    detail = describe_capabilities("backends")
    assert detail["ok"] is True
    assert detail["topic"] == "backends"
    assert detail["optional_backends"]["lanes"]["vision"]["install"] == "uv sync --extra vision"


def test_backends_topic_is_documented_in_the_tool_description():
    from frameforge_mcp.descriptions import _DESC_TOPIC

    assert "backends" in _DESC_TOPIC


# --------------------------------------------------------------------------- #
#  Integration: the tools that the gap silenced                                #
# --------------------------------------------------------------------------- #


def test_the_installed_vision_lane_provides_its_backend():
    """The end-to-end acceptance criterion for the packaging fix.

    Nothing but the `vision`/`pdf`/`vlm` extras pull `frameforge_vision`, so an
    environment that can import it was built from one of them — and must
    therefore have the CV backend that made the lane usable.
    """
    if importlib.util.find_spec("frameforge_vision") is None:
        pytest.skip("no optional lane installed in this environment")

    assert extras.missing_modules("vision") == (), (
        "frameforge_vision is installed without its CV backend — the extra under-declares"
    )


@pytest.fixture()
def probe_root(tmp_path, monkeypatch):
    """Let the tools read this test's scratch directory.

    `default_input_roots()` confines the propose/measure tools to the session
    root, the working directory and the repo — deliberately not `/tmp`. These
    tests are about the vision LANE, not the confinement policy, so they declare
    their fixture directory the way an operator would.
    """
    monkeypatch.setenv("FRAMEFORGE_MCP_INPUT_ROOTS", str(tmp_path))
    return tmp_path


def _render_probe(tmp_path: Path) -> Path:
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (120, 80), "white")
    for x in range(20, 100):
        for y in range(20, 60):
            image.putpixel((x, y), (10, 30, 90))
    path = tmp_path / "probe.png"
    image.save(path)
    return path


def test_detect_regions_runs_when_the_lane_is_installed(probe_root, tmp_path):
    pytest.importorskip("cv2")
    from frameforge_mcp import usecases

    result = usecases.detect_regions(
        str(_render_probe(tmp_path)),
        session_id="regions-probe",
        session_root=tmp_path / "sessions",
    )

    assert result["ok"] is True, result
    assert result["spatial"]["regions"]


def test_vectorize_image_runs_when_the_lane_is_installed(probe_root, tmp_path):
    pytest.importorskip("cv2")
    from frameforge_mcp import usecases

    result = usecases.vectorize_image(
        str(_render_probe(tmp_path)),
        session_id="vectorize-probe",
        session_root=tmp_path / "sessions",
        raster_png=False,
    )

    assert result["ok"] is True, result


def test_detect_regions_without_the_backend_returns_a_runnable_fix(probe_root, tmp_path, monkeypatch):
    """The envelope a caller sees when the lane is absent must name the extra.

    A ``None`` entry in ``sys.modules`` is the stdlib's own way of making an
    import fail, so this exercises the real ``except ImportError`` path. The
    parent's attribute has to go too: ``from pkg import mod`` is satisfied by
    the attribute alone once the submodule has been imported.
    """
    import sys

    pytest.importorskip("frameforge_vision.infrastructure.regions")
    import frameforge_vision.infrastructure as vision_infrastructure

    from frameforge_mcp import usecases

    monkeypatch.setitem(sys.modules, "frameforge_vision.infrastructure.regions", None)
    monkeypatch.delattr(vision_infrastructure, "regions", raising=False)

    probe = _render_probe(tmp_path)
    result = usecases.detect_regions(
        str(probe),
        session_id="no-backend",
        session_root=tmp_path / "sessions",
    )

    assert result["ok"] is False
    assert "--extra vision" in (result.get("hint") or "") + result["error"]


def test_describe_render_reports_the_missing_backend_rather_than_raising(monkeypatch, tmp_path):
    """The end-to-end shape of the reported failure: every Python import
    resolved, the tool ran, and transformers raised a ValueError the caller
    could do nothing with. With the backend probed, the same environment gets an
    `ok: false` envelope naming the fix."""
    import importlib.util as importlib_util

    from frameforge_mcp import usecases

    real_find_spec = importlib_util.find_spec
    monkeypatch.setattr(
        extras.importlib.util,
        "find_spec",
        lambda name, *a, **k: None if name == "torchvision" else real_find_spec(name, *a, **k),
    )

    assert extras.missing_modules("vlm") == ("torchvision",)

    result = usecases.describe_render(str(tmp_path / "page.png"))

    assert result["ok"] is False
    assert "--extra vlm" in (result.get("hint") or "")


def test_describe_render_without_the_vlm_lane_fails_soft(monkeypatch, tmp_path):
    """An absent lane is an `ok: false` envelope with a fix — never an exception."""
    from frameforge_mcp import usecases

    monkeypatch.setattr(extras, "lane_available", lambda name: False)

    result = usecases.describe_render(str(tmp_path / "nope.png"))

    assert result["ok"] is False
    assert "--extra vlm" in (result.get("hint") or "") + result["error"]
