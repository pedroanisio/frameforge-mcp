"""MCP exposes byte-pinned closure metrics across author, render, and fit paths."""
from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import frameforge_sdk
import tomllib
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from frameforge_fonts import (
    FontAsset,
    FontFace,
    FontStatus,
    FontStore,
    export_closure,
)

from frameforge_mcp import usecases
from frameforge_mcp.server import create_server

DOCUMENT = """
dsl: FrameForge
version: 2.2.0
title: closure probe
pages:
  - mode: page
    id: p1
    canvas: {size: [240, 120], units: px}
    layers:
      - id: content
        objects:
          - type: text
            id: copy
            box: [10, 10, 160, 60]
            text: portable metrics
            style: {font_family: Pinned Sans, font_size: 12}
"""


class _Metrics:
    def width(self, text: str, font_size: float) -> float:
        return len(text) * font_size * 2.0


def _real_closure(tmp_path: Path) -> Path:
    font_path = tmp_path / "pinned.ttf"
    builder = FontBuilder(1000, isTTF=True)
    glyph_order = [".notdef", "space", "A", "B"]
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap({32: "space", 65: "A", 66: "B"})
    builder.setupGlyf({name: TTGlyphPen(None).glyph() for name in glyph_order})
    builder.setupHorizontalMetrics(
        {".notdef": (500, 0), "space": (300, 0), "A": (600, 0), "B": (620, 0)}
    )
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable(
        {
            "familyName": "Pinned Sans",
            "styleName": "Regular",
            "uniqueFontIdentifier": "Pinned Sans Regular test",
            "fullName": "Pinned Sans Regular",
            "psName": "PinnedSans-Regular",
        }
    )
    builder.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        usWinAscent=800,
        usWinDescent=200,
        usWeightClass=400,
    )
    builder.setupPost()
    builder.setupMaxp()
    builder.save(font_path)
    store = FontStore(tmp_path / "source-store")
    handle = store.put(
        FontFace(
            family="Pinned Sans",
            style="normal",
            weight=400,
            stretch=100,
            provider="fixture",
            source="fixture:pinned",
            locator=font_path.name,
            status=FontStatus.READY,
        ),
        FontAsset(data=font_path.read_bytes(), filename=font_path.name, source="fixture"),
    )
    return export_closure([handle], tmp_path / "pinned.fp")


def _install_closure_double(monkeypatch, calls):
    def load(path, **kwargs):
        calls.append((str(path), kwargs))
        return lambda _family, _bold: _Metrics()

    monkeypatch.setattr(frameforge_sdk, "closure_metrics", load)


def test_render_yaml_uses_closure_for_svg_html_and_reports_evidence(tmp_path, monkeypatch):
    closure = tmp_path / "corpus.fp"
    closure.write_bytes(b"portable closure fixture")
    calls: list[tuple[str, dict]] = []
    _install_closure_double(monkeypatch, calls)

    result = usecases.render_frameforge_yaml(
        DOCUMENT,
        session_id="closure-html",
        session_root=tmp_path / "sessions",
        raster_png=False,
        to="html",
        real_metrics=False,
        font_closure=str(closure),
    )

    assert result["ok"] is True
    assert result["metrics_mode"] == "closure"
    assert result["diagnostics"]["metrics_mode"] == "closure"
    assert result["font_closure"]["sha256"]
    assert result["html"]["ok"] is True
    assert calls == [(str(closure.resolve()), {"store_root": tmp_path / "sessions" / "closure-html" / "font-store", "strict": True, "generics": None})]


def test_closure_path_obeys_mcp_input_confinement(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    closure = tmp_path / "outside.fp"
    closure.write_bytes(b"outside")
    monkeypatch.setenv("FRAMEFORGE_MCP_INPUT_ROOTS", str(allowed))

    result = usecases.render_frameforge_yaml(
        DOCUMENT,
        session_id="confined",
        session_root=tmp_path / "sessions",
        raster_png=False,
        font_closure=str(closure),
    )

    assert result["ok"] is False
    assert "FRAMEFORGE_MCP_INPUT_ROOTS" in result["error"]


def test_fit_text_uses_the_same_closure_provider(tmp_path, monkeypatch):
    closure = tmp_path / "corpus.fp"
    closure.write_bytes(b"portable closure fixture")
    calls: list[tuple[str, dict]] = []
    _install_closure_double(monkeypatch, calls)

    result = usecases.fit_text(
        "abcd", "Pinned Sans", 10, real_metrics=False,
        font_closure=str(closure),
    )

    assert result["metrics_mode"] == "closure"
    assert result["measured_width"] == 80.0
    assert result["fit_width"] > result["measured_width"]


def test_real_closure_reaches_mcp_fit_and_render_end_to_end(tmp_path):
    closure = _real_closure(tmp_path)

    fitted = usecases.fit_text(
        "AB",
        "sans-serif",
        20,
        real_metrics=False,
        font_closure=str(closure),
        font_generics={"sans-serif": "Pinned Sans"},
    )
    rendered = usecases.render_frameforge_yaml(
        DOCUMENT.replace("portable metrics", "AB"),
        session_id="real-closure",
        session_root=tmp_path / "sessions",
        raster_png=False,
        to="html",
        real_metrics=False,
        font_closure=str(closure),
    )

    assert fitted["measured_width"] == 24.4
    assert fitted["font_closure"]["sha256"] == hashlib.sha256(closure.read_bytes()).hexdigest()
    assert rendered["ok"] is True
    assert rendered["metrics_mode"] == "closure"
    assert rendered["html"]["ok"] is True


def test_every_render_usecase_exposes_the_closure_option():
    for function in (
        usecases.run_sdk_client,
        usecases.run_sdk_code,
        usecases.render_frameforge_yaml,
    ):
        parameters = inspect.signature(function).parameters
        assert "font_closure" in parameters
        assert "font_generics" in parameters


class _FakeFastMCP:
    def __init__(self, _name: str, **_kwargs):
        self.tools = {}
        self.resources = {}
        self.prompts = {}

    def tool(self, **_kwargs):
        def decorate(function):
            self.tools[function.__name__] = function
            return function
        return decorate

    def resource(self, uri: str, **_kwargs):
        def decorate(function):
            self.resources[uri] = function
            return function
        return decorate

    def prompt(self, **_kwargs):
        def decorate(function):
            self.prompts[function.__name__] = function
            return function
        return decorate


def test_mcp_tool_schemas_expose_closure_configuration(tmp_path):
    server = create_server(session_root=tmp_path, fastmcp_cls=_FakeFastMCP)

    for name in ("run_sdk_client", "run_sdk_code", "render_frameforge_yaml", "fit_text"):
        parameters = inspect.signature(server.tools[name]).parameters
        assert "font_closure" in parameters
        assert "font_generics" in parameters


def test_default_mcp_install_includes_the_sdk_metrics_extra():
    project = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert "frameforge-sdk[metrics]" in project["project"]["dependencies"]
