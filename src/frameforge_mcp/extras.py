"""The optional install lanes of this distribution — one table, checked live.

Three things used to be stated separately and drifted apart: what an extra
DECLARES in ``pyproject.toml``, what the lane's code actually IMPORTS, and what
a failing tool TELLS the caller to install. The drift was not cosmetic —
``frameforge-mcp[vision]`` pulled the ``frameforge-vision`` distribution but not
its ``cv`` extra, so a full ``--all-extras`` install still answered every CV call
with ``No module named 'cv2'``, and the hint attached to that failure named a
dependency-group command this distribution does not have (it ships extras; the
monorepo it was extracted from had groups). A caller following the hint got an
error about the hint.

So the lane table below is the single source of truth. ``probes`` are the exact
top-level modules the lane's code imports, and they are resolved with
:func:`importlib.util.find_spec` — presence is checked WITHOUT importing, so
asking whether the VLM lane is installed never pays torch's import cost.
``tests/test_optional_extras.py`` pins the table against ``pyproject.toml`` in
both directions, so an extra can neither be added without a lane nor renamed
without the report noticing.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

#: This distribution's name on the index — the thing that carries the extras.
DISTRIBUTION = "frameforge-mcp"


@dataclass(frozen=True)
class OptionalLane:
    """One optional extra: what it is for, what it needs, what it unlocks."""

    name: str
    summary: str
    #: Top-level module names the lane's code imports.
    probes: tuple[str, ...]
    #: MCP tools that cannot answer without this lane.
    tools: tuple[str, ...]
    #: Anything the package manager cannot install for you.
    post_install: str | None = None

    @property
    def install(self) -> str:
        """The dev-checkout install command (uv, this repo)."""
        return f"uv sync --extra {self.name}"

    @property
    def pip_install(self) -> str:
        """The install command for a consumer of the published distribution."""
        return f"pip install '{DISTRIBUTION}[{self.name}]'"


LANES: tuple[OptionalLane, ...] = (
    OptionalLane(
        name="vision",
        summary=(
            "raster→vector reconstruction and coordinate-aware measurement: the "
            "classical CV lane (OpenCV + NumPy) behind frameforge-vision"
        ),
        probes=("frameforge_vision", "cv2", "numpy", "PIL"),
        tools=(
            "propose_from_image",
            "propose_from_svg",
            "compare_images",
            "measure_image",
            "mark_points",
            "overlay_images",
            "workspace",
            "construct_vectors",
            "detect_regions",
            "fit_primitives",
            "score_reconstruction",
            "map_coordinates",
            "vectorize_image",
            "refine_reconstruction",
            "match_font",
            "coach_vectorize",
        ),
    ),
    OptionalLane(
        name="vlm",
        summary=(
            "the local vision-language describer (CPU-runnable; ADVISORY output, "
            "never a measurement)"
        ),
        # `torchvision` is not decoration: transformers 5.x split image
        # processors into `pil` / `torchvision` backends, and both Idefics3
        # classes (SmolVLM, the default model) require torchvision. Without it
        # every import here resolves, the lane reports available, and
        # `AutoProcessor.from_pretrained` then raises a ValueError the caller
        # cannot act on. The probe list is the lane's contract: what it needs to
        # WORK, not what it needs to import.
        probes=("frameforge_vision", "torch", "transformers", "torchvision", "PIL"),
        tools=("describe_render",),
        post_install=(
            "the default SmolVLM-256M model (~0.5GB) downloads on first use; "
            "set FG_VLM_MODEL to override"
        ),
    ),
    OptionalLane(
        name="pdf",
        summary="PDF input for propose_from_document (PyMuPDF page rasterisation)",
        probes=("frameforge_vision", "fitz"),
        tools=("propose_from_document",),
    ),
    OptionalLane(
        name="pdfout",
        summary=(
            "PDF export: the `to='pdf'` option of the render tools and the "
            "frameforge://session/<id>/document.pdf resource (CairoSVG + pypdf)"
        ),
        probes=("cairosvg", "pypdf"),
        tools=(),
    ),
    OptionalLane(
        name="browser",
        summary=(
            "headless-Chromium raster, when the browser path is preferred over "
            "CairoSVG (highest CSS fidelity: filters, blend modes, masks)"
        ),
        probes=("playwright",),
        tools=(),
        post_install="playwright install chromium",
    ),
)

_BY_NAME = {lane.name: lane for lane in LANES}


def lane(name: str) -> OptionalLane:
    """The lane called ``name``; ``KeyError`` when there is no such extra."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"unknown optional lane {name!r}; this distribution ships "
            f"{', '.join(sorted(_BY_NAME))}"
        ) from None


def _importable(module: str) -> bool:
    """True when ``module`` can be imported, WITHOUT importing it.

    ``find_spec`` raises for a half-installed package (a namespace shadow, a
    broken ``__spec__``). That is not a crash the server should propagate: an
    unusable backend is an absent backend.
    """
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def missing_modules(name: str) -> tuple[str, ...]:
    """The lane's probe modules that cannot be imported, in declaration order."""
    return tuple(module for module in lane(name).probes if not _importable(module))


def lane_available(name: str) -> bool:
    """True when every backend the lane imports is present."""
    return not missing_modules(name)


def unavailable_error(name: str) -> str:
    """The ``error`` half of a failure envelope: what is not installed."""
    return f"the optional `{name}` extra is not installed"


def install_hint(name: str) -> str:
    """The ``hint`` half: a command the caller can actually run.

    Both forms are given because both callers exist — an agent working in this
    checkout runs ``uv sync``, a consumer of the published wheel runs ``pip``.
    """
    entry = lane(name)
    hint = (
        f"install the optional `{entry.name}` extra: `{entry.install}` "
        f"(or `{entry.pip_install}`)"
    )
    if entry.post_install:
        hint += f" — then: {entry.post_install}"
    return hint


def optional_backends() -> dict[str, Any]:
    """Which optional lanes are usable in THIS interpreter, and how to fix the rest.

    Derived live on every call (no caching), the same discipline as
    :func:`frameforge_mcp.security.security_posture`: an install performed while
    the server is running is visible to the next call.
    """
    return {
        "distribution": DISTRIBUTION,
        "packaging": "extras",
        "lanes": {
            entry.name: {
                "summary": entry.summary,
                "available": lane_available(entry.name),
                "probes": list(entry.probes),
                "missing": list(missing_modules(entry.name)),
                "install": entry.install,
                "pip_install": entry.pip_install,
                "post_install": entry.post_install,
                "tools": list(entry.tools),
            }
            for entry in LANES
        },
        "note": (
            "these are EXTRAS of the "
            f"{DISTRIBUTION} distribution, not dependency groups — "
            "`--extra <name>`, never `--group <name>`. A tool listed under an "
            "unavailable lane returns `ok: false` with this install command; it "
            "is uninstalled, not broken."
        ),
    }


def availability() -> dict[str, bool]:
    """The compact ``{lane: available}`` form carried by the capability index."""
    return {entry.name: lane_available(entry.name) for entry in LANES}


__all__ = [
    "DISTRIBUTION",
    "LANES",
    "OptionalLane",
    "availability",
    "install_hint",
    "lane",
    "lane_available",
    "missing_modules",
    "optional_backends",
    "unavailable_error",
]
