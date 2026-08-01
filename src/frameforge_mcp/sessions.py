"""Per-session scratch-directory lifecycle, listing, cleanup, and resource reads."""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import yaml

from frameforge import __version__
from frameforge_mcp.config import (
    DEFAULT_MIN_CLEANUP_AGE_SECONDS,
    SESSION_ID_RE,
    _positive_env,
    max_blob_bytes,
    max_resource_bytes,
    max_result_chars,
    max_text_chars,
)
from frameforge_mcp.config import publish_root as config_publish_root
from frameforge_mcp.paths import _session_root
from frameforge_mcp.util import (
    _is_relative_to,
    _iso_from_timestamp,
    _page_svg_name,
    _positive_int,
)


def _session_id(session_id: str | None) -> str:
    sid = session_id or "session"
    if not SESSION_ID_RE.fullmatch(sid):
        raise ValueError("session_id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
    return sid


def _prepare_session(root: Path, session_id: str) -> Path:
    session_dir = (root / session_id).resolve()
    if not _is_relative_to(session_dir, root):
        raise ValueError("session_id escapes the session root")
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _reset_session_outputs(session_dir: Path) -> None:
    """Remove a prior run's generated artifacts so a reused ``session_id`` re-renders fresh.

    The code-execution harness only (re)derives the document when ``OUTPUT_YAML_PATH``
    is absent (see :func:`_harness_source`), so a leftover ``generated.fg.yaml`` from an
    earlier run under the same ``session_id`` would be re-rendered in place of the edited
    document. Clearing the per-run outputs (the generated YAML and any page SVG/PNG
    renders) makes each invocation hermetic without forcing callers to rotate the id.
    """
    _reset_session_inputs(session_dir)
    _reset_session_renders(session_dir)


def _reset_session_inputs(session_dir: Path) -> None:
    """Clear only the hermetic BUILD inputs (generated YAML + build-error sidecar).

    Safe to run before ``produce()``: a failed build then leaves the previous
    call's rendered pages intact instead of destroying them (PALS: a failure
    must not silently eat the last good render).
    """
    for path in (session_dir / "generated.fg.yaml", session_dir / "build_error.json"):
        path.unlink(missing_ok=True)


def _reset_session_renders(session_dir: Path) -> None:
    """Clear a prior run's rendered artifacts; call only when a new render is imminent."""
    stale = [
        session_dir / "document.pdf",
        *session_dir.glob("page-*.svg"),
        *session_dir.glob("p*.png"),
    ]
    for path in stale:
        path.unlink(missing_ok=True)


def _prior_render_artifacts(session_dir: Path) -> list[str]:
    """Names of the rendered artifacts a fresh call in this session would replace.

    The per-call output reset (:func:`_reset_session_outputs`) makes each run
    hermetic but silently destroys a previous call's renders when a session id is
    shared across tools; callers snapshot this BEFORE producing so the replacement
    can be surfaced instead of discovered later (see the guide's clobber warning).
    """
    if not session_dir.is_dir():
        return []
    names = [path.name for path in session_dir.glob("p*.png")]
    names += [path.name for path in session_dir.glob("page-*.svg")]
    if (session_dir / "document.pdf").is_file():
        names.append("document.pdf")
    return sorted(names)


def _previous_session_tool(session_dir: Path) -> str | None:
    """The tool that produced this session's last diagnostics, if recorded."""
    path = session_dir / "diagnostics.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    tool = data.get("tool") if isinstance(data, dict) else None
    return tool if isinstance(tool, str) and tool else None


_BINARY_MIMES = ("image/png", "application/pdf")


def _resolve_session_artifact(
    uri: str, *, session_root: str | Path | None = None
) -> tuple[Path, str, str]:
    """Resolve a ``frameforge://session/...`` URI to ``(path, mime, session_id)``.

    Raises the shared actionable errors for malformed URIs and missing files."""
    root = _session_root(session_root)
    parsed = urlparse(uri)
    if parsed.scheme != "frameforge" or parsed.netloc != "session":
        raise ValueError("resource URI must start with frameforge://session/")
    parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ValueError("resource URI is missing a session id and artifact path")
    sid = _session_id(parts[0])
    session_dir = (root / sid).resolve()
    if not _is_relative_to(session_dir, root.resolve()):
        raise ValueError("resource URI escapes the session root")

    artifact = parts[1:]
    if artifact == ["document.yaml"]:
        path = session_dir / "generated.fg.yaml"
        mime = "application/x-yaml"
    elif artifact == ["document.pdf"]:
        path = session_dir / "document.pdf"
        mime = "application/pdf"
    elif artifact == ["diagnostics.json"]:
        path = session_dir / "diagnostics.json"
        mime = "application/json"
    elif artifact == ["workspace.json"]:
        path = session_dir / "workspace.json"
        mime = "application/json"
    elif artifact == ["audit.json"]:
        path = session_dir / "audit.json"
        mime = "application/json"
    elif artifact == ["audit.md"]:
        path = session_dir / "audit.md"
        mime = "text/markdown"
    elif len(artifact) == 2 and artifact[0] == "page" and artifact[1].endswith(".svg"):
        page_number = artifact[1][:-4]
        path = session_dir / _page_svg_name(_positive_int(page_number, "page_number"))
        mime = "image/svg+xml"
    elif len(artifact) == 2 and artifact[0] == "page" and artifact[1].endswith(".png"):
        page_number = artifact[1][:-4]
        path = session_dir / f"p{_positive_int(page_number, 'page_number'):03d}.png"
        mime = "image/png"
    else:
        raise ValueError(f"unsupported resource artifact: {'/'.join(artifact)!r}")

    if not path.exists():
        available = (
            sorted(entry.name for entry in session_dir.iterdir() if entry.is_file())
            if session_dir.is_dir()
            else []
        )
        listing = ", ".join(available) if available else "none — the session has no artifacts yet"
        raise FileNotFoundError(
            f"{path} does not exist. Artifacts currently in session {sid!r}: {listing}. "
            "Every render tool resets its session's page-*.svg/p*.png on each call, so "
            "page/N.png holds the LAST call's render — re-render, or use a distinct session_id."
        )
    return path, mime, sid


def _json_pointer(document: Any, pointer: str) -> Any:
    """Evaluate an RFC 6901 JSON pointer; errors list the keys actually available."""
    if pointer in ("", "/"):
        return document
    if not pointer.startswith("/"):
        raise ValueError(
            f"query must be an RFC 6901 JSON pointer starting with '/': {pointer!r}"
        )
    node = document
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if token not in node:
                raise ValueError(
                    f"query token {token!r} not found; available keys: "
                    f"{', '.join(sorted(map(str, node.keys()))) or 'none'}"
                )
            node = node[token]
        elif isinstance(node, list):
            try:
                index = int(token)
            except ValueError:
                raise ValueError(
                    f"query token {token!r} must be an index into a {len(node)}-item array"
                ) from None
            if not 0 <= index < len(node):
                raise ValueError(
                    f"query index {index} out of range for a {len(node)}-item array"
                )
            node = node[index]
        else:
            raise ValueError(
                f"query token {token!r} descends into a {type(node).__name__}, "
                "which has no children"
            )
    return node


def session_resource_bytes(uri: str, *, session_root: str | Path | None = None) -> bytes:
    """Raw artifact bytes for INTERNAL consumers (image loaders, pipelines).

    Never crosses the MCP transport, so it is deliberately uncapped — transport
    budgets live in :func:`read_session_resource` and the endpoint readers."""
    path, _mime, _sid = _resolve_session_artifact(uri, session_root=session_root)
    return path.read_bytes()


def session_resource_endpoint_text(
    uri: str, *, session_root: str | Path | None = None
) -> str:
    """Full text for a registered resource endpoint, capped by the result budget.

    Resources carry whole artifacts by contract, so an over-budget artifact is
    refused with the pagination remediation instead of silently truncated."""
    path, _mime, _sid = _resolve_session_artifact(uri, session_root=session_root)
    text = path.read_text(encoding="utf-8")
    budget = max_result_chars()
    if len(text) > budget:
        raise ValueError(
            f"{path} is {len(text)} chars — over the {budget}-char resource budget "
            "(FRAMEFORGE_MCP_MAX_RESULT_CHARS). Page through it with "
            "get_session_resource(uri, offset=..., max_chars=...), query JSON artifacts "
            f"with query='/pointer', or read the file directly at {path}."
        )
    return text


def session_resource_endpoint_bytes(
    uri: str, *, session_root: str | Path | None = None
) -> bytes:
    """Raw bytes for a registered binary resource endpoint, capped by byte budget."""
    path, _mime, _sid = _resolve_session_artifact(uri, session_root=session_root)
    size = path.stat().st_size
    cap = max_resource_bytes()
    if size > cap:
        raise ValueError(
            f"{path} is {size} bytes — over the {cap}-byte resource cap "
            "(FRAMEFORGE_MCP_MAX_RESOURCE_BYTES). Render tools already inline raster "
            "pages as vision content (raster_png=true); read the file directly at "
            f"{path}, or raise the cap for this deployment."
        )
    return path.read_bytes()


def read_session_resource(
    uri: str,
    *,
    session_root: str | Path | None = None,
    mode: str = "auto",
    offset: int = 0,
    max_chars: int | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    """Read a ``frameforge://session/...`` artifact as a transport-budgeted payload.

    Binary artifacts (PNG/PDF) return by REFERENCE — ``{kind, bytes, sha256,
    path, hint}`` — because a base64 blob inside a JSON text result is never
    decodable as an image by the model and routinely blows the client's token
    cap. ``mode="blob"`` opts back in for small files (capped by the result
    budget). Text artifacts paginate via ``offset``/``max_chars`` and report
    ``total_chars``/``truncated``/``next_offset``; JSON artifacts additionally
    answer targeted RFC 6901 ``query`` pointers with just the fragment."""
    if mode not in ("auto", "meta", "blob"):
        raise ValueError(f"mode must be 'auto', 'meta', or 'blob', not {mode!r}")
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if max_chars is not None and max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")

    path, mime, _sid = _resolve_session_artifact(uri, session_root=session_root)

    if mime in _BINARY_MIMES:
        if query is not None or offset or max_chars is not None:
            raise ValueError(
                "offset/max_chars/query apply to text artifacts; "
                f"{mime} is binary — use the default reference metadata, "
                "mode='blob' for a small inline copy, or read the file at its path"
            )
        payload = path.read_bytes()
        result: dict[str, Any] = {
            "uri": uri,
            "mimeType": mime,
            "kind": "binary",
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "path": str(path),
        }
        if mode == "blob":
            cap = max_blob_bytes()
            if len(payload) > cap:
                raise ValueError(
                    f"{path} is {len(payload)} bytes — too large to inline as a blob "
                    f"(cap {cap} bytes, derived from FRAMEFORGE_MCP_MAX_RESULT_CHARS). "
                    "Read the file at its path instead; raster pages are inlined as "
                    "vision content by the render tools (raster_png=true)."
                )
            result["blob"] = base64.b64encode(payload).decode("ascii")
            return result
        result["hint"] = (
            "binary artifacts ship by reference; pass mode='blob' for a small inline "
            "base64 copy, or read the file at `path`. Raster pages are inlined as "
            "vision content by the render tools (raster_png=true)."
        )
        return result

    if mode == "blob":
        raise ValueError(
            f"mode='blob' applies to binary artifacts; {mime} is a text artifact — "
            "use offset/max_chars pagination (or query for JSON)"
        )

    text = path.read_text(encoding="utf-8")

    if query is not None:
        if mime != "application/json":
            raise ValueError(
                f"query applies to JSON artifacts only; {mime} is not JSON — "
                "page through it with offset/max_chars instead"
            )
        value = _json_pointer(json.loads(text), query)
        serialized = json.dumps(value, ensure_ascii=False)
        cap = max_text_chars()
        if len(serialized) > cap:
            raise ValueError(
                f"query {query!r} selects a {len(serialized)}-char fragment — over the "
                f"{cap}-char slice budget; narrow the pointer (list keys by querying "
                "the parent object) or page the full file with offset/max_chars"
            )
        return {
            "uri": uri,
            "mimeType": mime,
            "path": str(path),
            "query": query,
            "value": value,
        }

    slice_cap = max_text_chars()
    effective = min(max_chars, slice_cap) if max_chars is not None else slice_cap
    chunk = text[offset:offset + effective]
    truncated = offset + len(chunk) < len(text)
    result = {
        "uri": uri,
        "mimeType": mime,
        "path": str(path),
        "text": chunk,
        "total_chars": len(text),
        "offset": offset,
        "returned_chars": len(chunk),
        "truncated": truncated,
    }
    if truncated:
        result["next_offset"] = offset + len(chunk)
    return result


def list_sessions(*, session_root: str | Path | None = None) -> dict[str, Any]:
    """List per-session scratch directories under the session root with their size."""
    root = _session_root(session_root)
    sessions: list[dict[str, Any]] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not SESSION_ID_RE.fullmatch(entry.name):
            continue
        files = [path for path in entry.rglob("*") if path.is_file()]
        sessions.append(
            {
                "session_id": entry.name,
                "has_document": (entry / "generated.fg.yaml").exists(),
                "svg_pages": len(list(entry.glob("page-*.svg"))),
                "png_pages": len(list(entry.glob("p*.png"))),
                "bytes": sum(path.stat().st_size for path in files),
                "modified": _iso_from_timestamp(entry.stat().st_mtime),
                "document_uri": f"frameforge://session/{entry.name}/document.yaml",
            }
        )
    return {
        "ok": True,
        "session_root": str(root),
        "session_count": len(sessions),
        "sessions": sessions,
    }


# Deliverables a publish copies (source name -> published name). Scratch —
# history/, workspace.json, the runner script — stays in the session dir.
_PUBLISH_RENAMES = {"generated.fg.yaml": "document.fg.yaml"}
_PUBLISH_KEEP = ("document.pdf", "diagnostics.json", "audit.json", "audit.md")
_PUBLISH_GLOBS = ("page-*.svg", "p[0-9][0-9][0-9].png")
RENDER_BUNDLE_FORMAT = "frameforge-render-bundle"
RENDER_BUNDLE_FORMAT_VERSION = 1


def _published_page_manifest(session_dir: Path, names: set[str]) -> list[dict[str, Any]]:
    """Describe rendered pages in stable display order for artifact consumers."""
    source_path = session_dir / "generated.fg.yaml"
    try:
        document = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        document = {}
    source_pages = document.get("pages") if isinstance(document, dict) else None
    if not isinstance(source_pages, list):
        source_pages = []

    page_numbers: set[int] = set()
    for name in names:
        try:
            if name.startswith("page-") and name.endswith(".svg"):
                page_numbers.add(int(name[5:-4]))
            elif name.startswith("p") and name.endswith(".png"):
                page_numbers.add(int(name[1:-4]))
        except ValueError:
            continue

    pages: list[dict[str, Any]] = []
    for number in sorted(page_numbers):
        source_page = source_pages[number - 1] if number <= len(source_pages) else {}
        if not isinstance(source_page, dict):
            source_page = {}
        canvas = source_page.get("canvas")
        if not isinstance(canvas, dict):
            canvas = {}
        size = canvas.get("size")
        if not isinstance(size, list) or len(size) != 2:
            size = None
        svg_name = f"page-{number:03d}.svg"
        png_name = f"p{number:03d}.png"
        pages.append(
            {
                "number": number,
                "id": source_page.get("id") or f"page-{number}",
                "size": size,
                "units": canvas.get("units") or "px",
                "svg": svg_name if svg_name in names else None,
                "png": png_name if png_name in names else None,
            }
        )
    return pages


def publish_session(
    session_id: str,
    *,
    session_root: str | Path | None = None,
    publish_root: str | Path | None = None,
    revision: int | None = None,
) -> dict[str, Any]:
    """Copy a session's DELIVERABLES to ``<publish_root>/<session_id>/``.

    The publish path (``FRAMEFORGE_MCP_PUBLISH_ROOT``) is the durable
    counterpart of the ephemeral session scratchpad: the built document
    (renamed ``document.fg.yaml``), the rendered pages, the PDF when present,
    and ``diagnostics.json`` (the caveats travel with the claim — PALS), plus
    a ``manifest.json`` carrying sha256/bytes per file, the source session id,
    the render revision, and a UTC timestamp. Re-publishing a session REPLACES
    its published directory (no accretion); ``cleanup_sessions`` never touches
    the publish root. A publish root inside the session root is refused —
    publishing into the scratchpad is a configuration error, not a request.
    """
    if publish_root is None:
        publish_root = config_publish_root()
    if publish_root is None:
        return {
            "ok": False,
            "error": "publishing is disabled: FRAMEFORGE_MCP_PUBLISH_ROOT is not set",
            "hint": "set FRAMEFORGE_MCP_PUBLISH_ROOT to a durable directory, "
                    "or drop publish=true",
        }
    root = _session_root(session_root)
    pub_root = Path(publish_root).expanduser().resolve()
    if pub_root == root.resolve() or pub_root.is_relative_to(root.resolve()):
        return {
            "ok": False,
            "error": f"publish root {pub_root} is inside the session root {root} — "
                     "publishing into the scratchpad is a configuration error",
            "hint": "point FRAMEFORGE_MCP_PUBLISH_ROOT outside the session root",
        }
    session_dir = root / _session_id(session_id)
    if not session_dir.is_dir():
        return {"ok": False, "error": f"session {session_id!r} has no scratch directory",
                "hint": "render into the session before publishing it"}

    sources: list[tuple[Path, str]] = []
    for src_name, dest_name in _PUBLISH_RENAMES.items():
        p = session_dir / src_name
        if p.is_file():
            sources.append((p, dest_name))
    for name in _PUBLISH_KEEP:
        p = session_dir / name
        if p.is_file():
            sources.append((p, name))
    for pattern in _PUBLISH_GLOBS:
        for p in sorted(session_dir.glob(pattern)):
            if p.is_file():
                sources.append((p, p.name))
    if not sources:
        return {"ok": False, "error": f"session {session_id!r} has no deliverables to publish",
                "hint": "render (and optionally export to='pdf') before publishing"}

    dest = pub_root / session_id
    if dest.exists():
        shutil.rmtree(dest)                      # replace, never accrete
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    for src, name in sources:
        data = src.read_bytes()
        (dest / name).write_bytes(data)
        files.append({"name": name, "bytes": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})
    copied_names = {entry["name"] for entry in files}
    manifest = {
        "format": RENDER_BUNDLE_FORMAT,
        "format_version": RENDER_BUNDLE_FORMAT_VERSION,
        "frameforge_version": __version__,
        "session_id": session_id,
        "revision": revision,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "document": "document.fg.yaml" if "document.fg.yaml" in copied_names else None,
        "diagnostics": "diagnostics.json" if "diagnostics.json" in copied_names else None,
        "pdf": "document.pdf" if "document.pdf" in copied_names else None,
        "pages": _published_page_manifest(session_dir, copied_names),
        "fonts": [],
        "files": files,
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"ok": True, "root": str(pub_root), "dir": str(dest),
            "files": files, "manifest": str(dest / "manifest.json")}


def cleanup_sessions(
    *,
    session_root: str | Path | None = None,
    session_ids: list[str] | None = None,
    older_than_seconds: float | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove session scratch dirs by id or age. No criteria removes nothing (safe by default).

    Exactly one selector applies: ``session_ids`` removes those ids; otherwise
    ``older_than_seconds`` removes sessions whose directory mtime is older than the
    cutoff. A hard delete (``dry_run=False``) with ``older_than_seconds`` below the
    minimum-age floor (``DEFAULT_MIN_CLEANUP_AGE_SECONDS``, per-call override via
    ``FRAMEFORGE_MCP_MIN_CLEANUP_AGE``) is refused with ``{"ok": False, "error",
    "hint"}`` and deletes nothing — ``older_than_seconds=0`` would otherwise wipe
    every session. ``dry_run`` reports the selection without deleting and is exempt
    from the floor, as is the explicit ``session_ids`` selector. The structured log
    lives as a file at the root and is never a deletion target.
    """
    root = _session_root(session_root)
    if session_ids is None and older_than_seconds is not None and not dry_run:
        floor = _positive_env("FRAMEFORGE_MCP_MIN_CLEANUP_AGE", DEFAULT_MIN_CLEANUP_AGE_SECONDS)
        if float(older_than_seconds) < floor:
            return {
                "ok": False,
                "session_root": str(root),
                "error": (
                    f"older_than_seconds={older_than_seconds} is below the minimum cleanup age "
                    f"of {floor}s — a hard delete this broad would wipe recent sessions."
                ),
                "hint": (
                    "Preview the selection with dry_run=true, remove specific sessions with "
                    "session_ids, or adjust the floor via FRAMEFORGE_MCP_MIN_CLEANUP_AGE."
                ),
            }
    cutoff = None
    if session_ids is None and older_than_seconds is not None:
        cutoff = datetime.now(timezone.utc).timestamp() - float(older_than_seconds)

    selected: list[Path] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not SESSION_ID_RE.fullmatch(entry.name):
            continue
        if session_ids is not None:
            if entry.name in session_ids:
                selected.append(entry)
        elif cutoff is not None and entry.stat().st_mtime < cutoff:
            selected.append(entry)

    removed: list[str] = []
    for entry in selected:
        target = entry.resolve()
        if not _is_relative_to(target, root):  # defense in depth — never escape the root
            continue
        if not dry_run:
            shutil.rmtree(target, ignore_errors=True)
        removed.append(entry.name)
    return {
        "ok": True,
        "session_root": str(root),
        "dry_run": dry_run,
        "removed_count": len(removed),
        "removed": removed,
    }


def _archive_renders(session_dir: Path, renders: list[dict[str, Any]], *,
                     keep: int = 5) -> dict[str, Any]:
    """Archive this render's page artifacts into ``history/rev-NNN``.

    A ring of the last ``keep`` revisions: enough to answer "did that nudge
    help?" across an iteration loop without growing a session unboundedly.
    Only page artifacts are archived (SVG always; PNG when rasterized) — the
    ``diff_renders`` usecase diffs the rasters of any two revisions.
    """
    hist = session_dir / "history"
    hist.mkdir(parents=True, exist_ok=True)
    existing = sorted(
        int(p.name.split("-", 1)[1]) for p in hist.glob("rev-*")
        if p.is_dir() and p.name.split("-", 1)[1].isdigit())
    rev = (existing[-1] + 1) if existing else 1
    rev_dir = hist / f"rev-{rev:03d}"
    rev_dir.mkdir(parents=True, exist_ok=True)
    for entry in renders:
        if "page" not in entry or not entry.get("path"):
            continue
        src = Path(str(entry["path"]))
        if src.is_file():
            shutil.copy2(src, rev_dir / src.name)
    existing.append(rev)
    for old in existing[:-keep]:
        shutil.rmtree(hist / f"rev-{old:03d}", ignore_errors=True)
    return {
        "revision": rev,
        "history": {
            "dir": str(hist),
            "revisions": existing[-keep:],
            "note": f"last {keep} render revisions kept; diff any two with diff_renders",
        },
    }
