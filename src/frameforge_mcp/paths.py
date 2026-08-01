"""Session-root and repository-root resolution for the MCP server."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def get_default_session_root() -> Path:
    """Return the default location for MCP session artifacts."""
    configured = os.environ.get("FRAMEFORGE_MCP_SESSION_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path(tempfile.gettempdir()) / "frameforge-mcp-sessions"


def get_default_repo_root() -> Path:
    """Return the FrameForge engine checkout this server introspects.

    This used to be a fixed number of directories above this file, which was
    true while the server lived inside the monorepo at
    ``<root>/src/frameforge/mcp/paths.py`` and stopped being true the moment it
    became its own distribution — silently, resolving to the directory that
    merely *contains* the checkouts. Nothing failed loudly; live discovery just
    found no sources.

    Resolve it through the installed engine instead, with an explicit override
    for a checkout that is not pip-installed. Falls back to the old relative
    walk so a vendored/in-tree layout still works.
    """
    configured = os.environ.get("FRAMEFORGE_REPO")
    if configured:
        return Path(configured).expanduser().resolve()
    try:
        import frameforge
    except ImportError:
        return Path(__file__).resolve().parents[3]
    # `<root>/src/frameforge/__init__.py` -> `<root>`
    return Path(frameforge.__file__).resolve().parents[2]


def _session_root(session_root: str | Path | None) -> Path:
    root = Path(session_root) if session_root is not None else get_default_session_root()
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _repo_root(repo_root: str | Path | None) -> Path:
    return (Path(repo_root) if repo_root is not None else get_default_repo_root()).expanduser().resolve()
