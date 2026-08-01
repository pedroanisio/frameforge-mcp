"""Runtime discovery: generated-YAML diffing, model capabilities, and fonts.

Three discovery axes live here:

- :func:`_new_generated_yaml` — content-hash diffing of the FrameForge YAML a
  client run produced (the run tools' fixture-discovery fallback).
- :func:`describe_capabilities` — LIVE introspection of the authoritative
  document model (``frameforge.model`` (src/frameforge/model.py), loaded through the same
  ``frameforge_sdk.model`` mechanism the pipeline uses), so an agent can look
  up object types, flowables, inlines, style fields, and canvas presets
  instead of guessing and iterating on validation errors.
- :func:`list_fonts` — fontconfig font-family enumeration + resolution, so a
  family can be verified BEFORE a render silently substitutes a default face.
"""
from __future__ import annotations

import functools
import hashlib
import shutil
import subprocess
import typing
from pathlib import Path
from typing import Any

from frameforge_mcp.config import FRAMEFORGE_YAML_PATTERNS
from frameforge_mcp.security import security_posture


def _frameforge_yaml_snapshot(repo_root: Path) -> dict[Path, str]:
    """Content-hash snapshot of candidate fixtures before a client run.

    Hashes (not mtimes) so the post-run diff only fires on *content* change — a
    fixture merely ``touch``-ed by an unrelated process is no longer mistaken for
    this client's output, which the mtime heuristic could do.
    """
    return {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in _frameforge_yaml_candidates(repo_root)
        if path.is_file()
    }


def _new_generated_yaml(repo_root: Path, before: dict[Path, str]) -> Path | None:
    changed: list[Path] = []
    for path in _frameforge_yaml_candidates(repo_root):
        if not path.is_file():
            continue
        previous = before.get(path)
        current = hashlib.sha256(path.read_bytes()).hexdigest()
        if previous is None or current != previous:
            changed.append(path)
    if not changed:
        return None
    # Tie-break by mtime when several fixtures changed in the same run.
    return max(changed, key=lambda candidate: candidate.stat().st_mtime_ns)


def _frameforge_yaml_candidates(repo_root: Path) -> list[Path]:
    candidates: list[Path] = []
    for root in (repo_root / "static" / "examples", repo_root / "tests" / "fixtures"):
        if not root.exists():
            continue
        for pattern in FRAMEFORGE_YAML_PATTERNS:
            candidates.extend(root.rglob(pattern))
    return candidates


# --------------------------------------------------------------------------- #
#  Model capability introspection (describe_capabilities)                     #
# --------------------------------------------------------------------------- #

_CAPABILITY_TOPICS = (
    "flowables", "inlines", "style", "presets", "tools", "sdk", "security",
    "or a type/model name like 'rect', 'paragraph', 'document', 'page', 'canvas'",
)


@functools.lru_cache(maxsize=1)
def _sdk_surface() -> tuple[dict[str, Any], ...]:
    """The public SDK surface, introspected LIVE from ``frameforge_sdk.__all__``.

    One entry per export — name, kind, signature (callables), and a one-line
    explanation from the object's own docstring — so the whole SDK is
    enumerable and explained from inside the MCP with nothing hand-maintained.
    Typing aliases and third-party re-exports (which cannot carry our
    docstrings) get generated explanations instead; the companion CI gate
    (tests/test_sdk_surface_mcp.py) fails on any frameforge-defined export
    without a docstring, so this listing cannot silently go blank.
    """
    import inspect

    import frameforge_sdk as sdk

    entries: list[dict[str, Any]] = []
    for name in sdk.__all__:
        obj = getattr(sdk, name)
        module = getattr(obj, "__module__", "") or ""
        doc = (inspect.getdoc(obj) or "").strip()
        first = doc.splitlines()[0].strip() if doc else ""
        ours = module.startswith("frameforge") or module == "frameforge.model"
        if module == "typing" or type(obj).__name__.endswith("GenericAlias"):
            kind, first = "type_alias", f"type alias: {obj}"
        elif inspect.ismodule(obj):
            kind = "module"
            first = first or f"submodule {obj.__name__}"
        elif inspect.isclass(obj):
            if ours:
                kind = "class"
            else:
                kind = "re-export"
                first = f"re-export of {module}.{name}" + (f" — {first}" if first else "")
        elif callable(obj):
            if ours:
                kind = "function"
            else:
                kind = "re-export"
                first = f"re-export of {module}.{name}" + (f" — {first}" if first else "")
        else:
            # instances inherit their TYPE's docstring via getdoc (str constructor
            # prose for a str constant) — always generate the explanation instead
            kind = "constant"
            first = f"constant {type(obj).__name__}: {obj!r:.60}"
        entry: dict[str, Any] = {"name": name, "kind": kind, "module": module or None,
                                 "doc": first}
        if kind in ("function", "re-export") and callable(obj):
            try:
                sig = str(inspect.signature(obj))
                entry["signature"] = sig if len(sig) <= 160 else sig[:157] + "..."
            except (TypeError, ValueError):
                entry["signature"] = "(...)"
        entries.append(entry)
    return tuple(entries)


def _union_members(alias: Any) -> tuple[type, ...]:
    """Member classes of a union alias — Annotated-wrapped or plain ``Union[...]``."""
    if typing.get_origin(alias) is typing.Annotated:
        alias = typing.get_args(alias)[0]
    members = typing.get_args(alias) or (alias,)
    return tuple(member for member in members if isinstance(member, type))


def _literal_value(cls: type, field: str) -> str | None:
    """The single Literal value of a discriminator field (``type``/``kind``), or None."""
    info = getattr(cls, "model_fields", {}).get(field)
    if info is None:
        return None
    values = typing.get_args(info.annotation)
    return str(values[0]) if values else None


def _literal_strings(annotation: Any) -> list[str]:
    """Every string a (possibly Optional/nested) Literal annotation admits."""
    values: list[str] = []
    for arg in typing.get_args(annotation):
        if isinstance(arg, str):
            values.append(arg)
        elif arg is type(None):
            continue
        else:
            values.extend(_literal_strings(arg))
    return values


def _class_schema(cls: type) -> dict[str, Any]:
    """A model's JSON schema with the top level inlined.

    Recursive models (e.g. flowables that nest inline footnotes) emit a bare
    top-level ``$ref`` into ``$defs``; inline that target so ``properties`` is
    always at the top while keeping ``$defs`` for the nested references.
    """
    schema = cls.model_json_schema()
    ref = schema.get("$ref")
    if "properties" not in schema and isinstance(ref, str):
        defs = schema.get("$defs", {})
        target = defs.get(ref.rsplit("/", 1)[-1])
        if isinstance(target, dict):
            merged = dict(target)
            if defs:
                merged["$defs"] = defs
            return merged
    return schema


def _field_summary(cls: type) -> dict[str, list[str]]:
    """Required/optional field names (serialization aliases) of a model class."""
    required: list[str] = []
    optional: list[str] = []
    for name, info in cls.model_fields.items():
        key = info.alias or name
        (required if info.is_required() else optional).append(key)
    return {"required": sorted(required), "optional": sorted(optional)}


def _schema_topic(key: str, cls: type, kind: str) -> dict[str, Any]:
    """A schema topic as PROGRESSIVE DISCLOSURE, not a full dump.

    Returning ``cls.model_json_schema()`` inlines the entire recursive ``$defs``
    graph — 70KB for a leaf ``rect``, 250KB+ for a container — which blows the
    MCP result token ceiling (the whole reason a caller cannot read it). Instead
    return the type's OWN ``properties`` plus a ``references`` list of the nested
    type names; the caller drills into any of them with another call (pass the
    lower-cased name as the topic). Full machine schema lives in the committed
    ``docs/schema/frameforge-v2.schema.json``.
    """
    schema = _class_schema(cls)
    references = sorted((schema.get("$defs") or {}).keys())
    return {
        "ok": True,
        "topic": key,
        "kind": kind,
        "fields": _field_summary(cls),
        "properties": schema.get("properties", {}),
        "references": references,
        "note": "compact view: `properties` are this type's own fields; "
                "`references` lists nested types — pass one (lower-cased) as the "
                "topic to drill in. Full JSON schema: docs/schema/frameforge-v2.schema.json.",
    }


@functools.lru_cache(maxsize=1)
def _model_catalog() -> dict[str, Any]:
    """The live model surface, introspected from ``frameforge.model`` (src/frameforge/model.py).

    Loaded through :func:`frameforge_sdk.model.model_module` — the same
    mechanism the render pipeline uses — so the catalog can never drift from
    what validation actually enforces. Cached for the process lifetime: the
    model module is import-stable, and describe_capabilities sits on the hot
    MCP tool path (full typing introspection per call otherwise).
    """
    from frameforge_sdk.model import model_module

    model = model_module()
    objects = {
        value: cls
        for cls in _union_members(model.VisualObject)
        if (value := _literal_value(cls, "type"))
    }
    flowables = {
        value: cls
        for cls in _union_members(model.Flowable)
        if (value := _literal_value(cls, "type"))
    }
    inlines = {
        value: cls
        for cls in _union_members(model.Inline)
        if (value := _literal_value(cls, "kind"))
    }
    inlines["span"] = model.Span  # a styled text run; plain strings are also inline
    return {
        "objects": objects,
        "flowables": flowables,
        "inlines": inlines,
        "presets": _literal_strings(model.PagePreset),
        "profiles": _literal_strings(model.Document.model_fields["profile"].annotation),
        "named": {
            "document": model.Document,
            "page": model.Page,
            "canvas": model.CanvasObject,
            "style": model.Style,
            "defs": model.Defs,
            "tokens": model.Tokens,
        },
    }


def describe_capabilities(
    topic: str | None = None, *, tool_names: list[str] | None = None
) -> dict[str, Any]:
    """Runtime discovery of the FrameForge document model (read-only introspection).

    No ``topic`` returns a compact capability index (object types, flowable
    types, inline kinds, canvas presets, profiles, tool names, the live
    security posture). A ``topic`` of
    ``flowables``/``inlines``/``style``/``presets``/``tools``/``security``
    returns that catalog; any object/flowable type name (``rect``,
    ``paragraph``, ...) or model name (``document``, ``page``, ``canvas``)
    returns its JSON schema.
    """
    from frameforge_sdk.model import HEAD_VERSION

    catalog = _model_catalog()
    key = (topic or "").strip().lower()
    if not key:
        return {
            "ok": True,
            "version": HEAD_VERSION,
            "object_types": sorted(catalog["objects"]),
            "flowable_types": sorted(catalog["flowables"]),
            "inline_kinds": sorted(catalog["inlines"]),
            "canvas_presets": list(catalog["presets"]),
            "profiles": list(catalog["profiles"]),
            "tools": sorted(tool_names or []),
            "sdk_exports": len(_sdk_surface()),
            "topics": list(_CAPABILITY_TOPICS),
            "security_posture": security_posture(),
            "source": "src/frameforge/model.py (live introspection via frameforge_sdk.model)",
        }
    if key == "tools":
        return {"ok": True, "topic": "tools", "tools": sorted(tool_names or [])}
    if key == "sdk":
        # Compact: name + module + the first sentence of the docstring. The full
        # signatures (239 exports) are 60KB — over the result ceiling; they live
        # in docs/sdk-api.md and every name is importable inside run_sdk_code.
        exports = [
            {
                "name": e.get("name"),
                "kind": e.get("kind"),
                "summary": (str(e.get("doc") or "").strip().split(". ")[0])[:100],
            }
            for e in _sdk_surface()
        ]
        return {
            "ok": True,
            "topic": "sdk",
            "exports": exports,
            "note": "introspected live from frameforge_sdk.__all__ — every export is "
                    "importable inside run_sdk_code; full signatures: docs/sdk-api.md",
        }
    if key == "security":
        return {
            "ok": True,
            "topic": "security",
            "security_posture": security_posture(),
            "note": "derived live from the environment on every call — never cached",
        }
    if key == "flowables":
        return {
            "ok": True,
            "topic": "flowables",
            "flowables": {name: _field_summary(cls) for name, cls in catalog["flowables"].items()},
            "note": "pass a flowable type name (e.g. 'paragraph') as the topic for its full JSON schema",
        }
    if key == "inlines":
        return {
            "ok": True,
            "topic": "inlines",
            "inlines": {name: _field_summary(cls) for name, cls in catalog["inlines"].items()},
            "note": "plain strings are also valid inline content; 'span' carries a per-run style",
        }
    if key == "presets":
        return {
            "ok": True,
            "topic": "presets",
            "canvas_presets": list(catalog["presets"]),
            "note": "a canvas object needs exactly one of `preset` or `size`",
        }
    if key in catalog["objects"]:
        return _schema_topic(key, catalog["objects"][key], "object")
    if key in catalog["flowables"]:
        return _schema_topic(key, catalog["flowables"][key], "flowable")
    if key in catalog["inlines"]:
        return _schema_topic(key, catalog["inlines"][key], "inline")
    if key in catalog["named"]:
        cls = catalog["named"][key]
        result = _schema_topic(key, cls, "model")
        if key == "style":
            # The flow renderer resolves its defaults from the document and injects
            # no undefined style (ADR-0006). The reserved token-style names that
            # carry those defaults come from the engine's single constant — never
            # restate them here (drift-map CRITICAL #2: this literal once named
            # two of the five).
            from frameforge_render.domain.services.text_style_resolver import (
                RESERVED_STYLES,
            )
            result["reserved_styles"] = {
                **RESERVED_STYLES,
                "note": "headings/lists resolve their own `style`; a table carries "
                        "its chrome via `style` (header_fill/header_text/cell_text/"
                        "zebra_fill/grid_color/cell_size — header_text/cell_text are "
                        "colour-or-style-ref, identical in both table renderers); "
                        "chrome it does not define is not drawn. See ADR-0006.",
            }
        return result
    return {
        "ok": False,
        "error": f"unknown topic {topic!r}",
        "hint": "valid topics: " + ", ".join(_CAPABILITY_TOPICS) + " — omit the topic for the capability index",
    }


# --------------------------------------------------------------------------- #
#  Font discovery (list_fonts)                                                #
# --------------------------------------------------------------------------- #


def _fc_available() -> bool:
    return shutil.which("fc-list") is not None


def _run_fc(args: list[str]) -> str:
    """Run an fc-* binary, returning stdout; failures raise RuntimeError."""
    proc = subprocess.run(args, capture_output=True, text=True, timeout=15, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {proc.stderr.strip() or proc.returncode}")
    return proc.stdout


_FONTCONFIG_HINT = (
    "install fontconfig (e.g. `apt-get install fontconfig`), or run the server in the "
    "frameforge docker image (`make docker-build`), which ships the full font set"
)


def _resolve_family(family: str) -> dict[str, Any]:
    """What fontconfig actually resolves ``family`` to (the silent-substitution check)."""
    try:
        out = _run_fc(["fc-match", "--format", "%{family}\t%{file}", family]).strip()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        return {"requested": family, "error": f"fc-match failed: {exc}"}
    resolved_part, sep, file_part = out.partition("\t")
    resolved = resolved_part.split(",")[0].strip()
    requested = family.split(":")[0].strip()
    exact = resolved.lower() == requested.lower()
    result: dict[str, Any] = {"requested": family, "resolved_family": resolved, "exact": exact}
    font_file = file_part.strip() if sep else ""
    if font_file:
        result["file"] = font_file
        axes = _font_axes_from_file(font_file)
        if axes:
            result["axes"] = axes
    if not exact:
        result["note"] = (
            f"fontconfig substitutes {resolved!r} for {family!r} — a render requesting this "
            "family will not use the requested face"
        )
    return result


def _font_axes_from_file(font_file: str) -> list[dict[str, Any]]:
    """Return variable-font axis metadata for ``font_file`` if fontTools can read it."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return []
    try:
        font = TTFont(font_file, fontNumber=0, lazy=True)
        fvar = font["fvar"] if "fvar" in font else None
        if fvar is None:
            return []
        axes = []
        for axis in fvar.axes:
            axes.append({
                "tag": axis.axisTag,
                "min": float(axis.minValue),
                "default": float(axis.defaultValue),
                "max": float(axis.maxValue),
            })
        return axes
    except Exception:  # noqa: BLE001 — corrupt/unreadable font metadata degrades to no axes
        return []


def _pinned_session_fonts(
    session_id: str | None, session_root: str | Path | None
) -> list[dict[str, str]]:
    """Font families pinned in a session document's ``defs.tokens.fonts``, if any."""
    from frameforge_mcp.paths import _session_root
    from frameforge_mcp.sessions import _session_id

    try:
        sid = _session_id(session_id)
    except ValueError:
        return []
    doc_path = _session_root(session_root) / sid / "generated.fg.yaml"
    if not doc_path.is_file():
        return []
    import yaml

    try:
        data = yaml.safe_load(doc_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(data, dict):
        return []
    fonts = ((data.get("defs") or {}).get("tokens") or {}).get("fonts") or {}
    if not isinstance(fonts, dict):
        return []
    pinned: list[dict[str, str]] = []
    for name, spec in fonts.items():
        if isinstance(spec, str):
            family = spec
        elif isinstance(spec, dict):
            family = str(spec.get("family") or "")
        else:
            continue
        if family:
            pinned.append({"name": str(name), "family": family})
    return pinned


_FC_FAMILIES_CACHE: dict[str, Any] = {"fn": None, "families": None}


def _fc_families() -> list[str]:
    """Sorted unique fontconfig families, cached per process.

    The installed font set is stable for a server's lifetime, and fc-list over
    ~5k families is a subprocess spawn on the hot MCP tool path. The cache is
    keyed on the identity of ``_run_fc`` so tests that monkeypatch the runner
    (deterministic fixtures) bypass a previously cached real enumeration.
    """
    if _FC_FAMILIES_CACHE["fn"] is _run_fc and _FC_FAMILIES_CACHE["families"] is not None:
        return list(_FC_FAMILIES_CACHE["families"])
    raw = _run_fc(["fc-list", "--format", "%{family}\n"])
    names: set[str] = set()
    for line in raw.splitlines():
        for part in line.split(","):
            part = part.strip()
            if part:
                names.add(part)
    families = sorted(names)
    _FC_FAMILIES_CACHE["fn"] = _run_fc
    _FC_FAMILIES_CACHE["families"] = families
    return list(families)


def list_fonts(
    family: str | None = None,
    *,
    contains: str | None = None,
    limit: int = 500,
    session_id: str | None = None,
    session_root: str | Path | None = None,
) -> dict[str, Any]:
    """Enumerate the font families fontconfig can resolve (+ an optional resolution check).

    The rasterizers resolve families via fontconfig, and an unresolved family
    silently substitutes a default face — check here BEFORE rendering. Passing
    ``family`` adds a ``resolves`` block reporting what fontconfig actually
    returns for that name. When the session already holds a rendered document,
    its ``defs.tokens.fonts`` pins are reported as ``pinned_fonts``. Degrades to
    a structured error (with an install hint) when fontconfig is absent.
    """
    pinned = _pinned_session_fonts(session_id, session_root)
    if not _fc_available():
        return {
            "ok": False,
            "error": "fontconfig (fc-list) is not on PATH; cannot enumerate or resolve font families",
            "hint": _FONTCONFIG_HINT,
            "families": [],
            "family_count": 0,
            "pinned_fonts": pinned,
        }
    try:
        families = _fc_families()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "error": f"fc-list failed: {exc}",
            "hint": _FONTCONFIG_HINT,
            "families": [],
            "family_count": 0,
            "pinned_fonts": pinned,
        }
    if contains:
        needle = contains.lower()
        families = [name for name in families if needle in name.lower()]
    total = len(families)
    cap = int(limit) if limit and int(limit) > 0 else 0
    shown = families[:cap] if cap else families
    result: dict[str, Any] = {
        "ok": True,
        "family_count": total,
        "families": shown,
        "truncated": bool(cap) and total > cap,
        "pinned_fonts": pinned,
    }
    if family:
        result["resolves"] = _resolve_family(family)
    return result
