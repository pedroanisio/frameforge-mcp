"""Tools for listing, reading, and writing editable SDK client files."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from frameforge_mcp.config import MAX_CLIENT_BYTES
from frameforge_mcp.paths import _repo_root
from frameforge_mcp.security import (
    _client_roots,
    _display_path,
    _resolve_client_path,
)
from frameforge_mcp.util import _is_relative_to, _sha256_text


def list_sdk_clients(
    *,
    repo_root: str | Path | None = None,
    edit_roots: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """List editable Python SDK client files under the configured safe roots."""
    root = _repo_root(repo_root)
    roots = _client_roots(root, edit_roots)
    clients: list[dict[str, Any]] = []
    for allowed_root in roots:
        if not allowed_root.exists():
            continue
        for path in sorted(allowed_root.rglob("*.py")):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if not any(_is_relative_to(resolved, candidate) for candidate in roots):
                continue
            data = resolved.read_bytes()
            clients.append(
                {
                    "path": _display_path(resolved, root),
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    return {
        "ok": True,
        "repo_root": str(root),
        "allowed_roots": [_display_path(path, root) for path in roots],
        "clients": clients,
    }


def read_sdk_client(
    path: str,
    *,
    repo_root: str | Path | None = None,
    edit_roots: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Read a whitelisted Python SDK client file for MCP-assisted editing."""
    root = _repo_root(repo_root)
    client_path = _resolve_client_path(path, repo_root=root, edit_roots=edit_roots, must_exist=True)
    code = client_path.read_text(encoding="utf-8")
    return {
        "ok": True,
        "path": _display_path(client_path, root),
        "absolute_path": str(client_path),
        "bytes": len(code.encode("utf-8")),
        "sha256": _sha256_text(code),
        "code": code,
    }


def write_sdk_client(
    path: str,
    code: str,
    *,
    create: bool = False,
    append: bool = False,
    allow_partial: bool = False,
    repo_root: str | Path | None = None,
    edit_roots: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Replace, create, or append to a whitelisted Python SDK client file.

    ``append`` concatenates ``code`` onto the existing file (creating it if
    absent), so a client larger than the caller's per-argument transport limit
    can be written in chunks. ``allow_partial`` skips the compile check for a
    chunk that is not yet syntactically complete — set it on every chunk except
    the last, then finish with a normal (compiled) write/append. The byte cap is
    applied to the *resulting* file, not the individual chunk.
    """
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code must be a non-empty string")

    root = _repo_root(repo_root)
    client_path = _resolve_client_path(
        path, repo_root=root, edit_roots=edit_roots, must_exist=not (create or append))
    if client_path.exists() and not client_path.is_file():
        raise ValueError("SDK client path must resolve to a file")
    if not client_path.exists() and not (create or append):
        raise FileNotFoundError(str(client_path))

    existed = client_path.exists()
    base = client_path.read_text(encoding="utf-8") if (append and existed) else ""
    content = base + code if append else code
    if len(content.encode("utf-8")) > MAX_CLIENT_BYTES:
        raise ValueError(f"content exceeds {MAX_CLIENT_BYTES} bytes")
    if not allow_partial:
        compile(content, _display_path(client_path, root), "exec")

    previous_sha = hashlib.sha256(client_path.read_bytes()).hexdigest() if existed else None
    client_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = client_path.with_name(f".{client_path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(client_path)

    data = client_path.read_bytes()
    return {
        "ok": True,
        "path": _display_path(client_path, root),
        "absolute_path": str(client_path),
        "created": previous_sha is None,
        "appended": bool(append and existed),
        "partial": bool(allow_partial),
        "previous_sha256": previous_sha,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }
