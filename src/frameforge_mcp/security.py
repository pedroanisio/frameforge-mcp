"""Path-traversal confinement for editable client files and propose inputs."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from frameforge_mcp.config import DEFAULT_CLIENT_ROOTS, DEFAULT_TIMEOUT_SECONDS, _truthy_env
from frameforge_mcp.paths import _repo_root
from frameforge_mcp.util import _is_relative_to


def _client_roots(repo_root: Path, edit_roots: str | list[str] | tuple[str, ...] | None) -> list[Path]:
    """Resolve the editable SDK-client roots.

    Relative entries resolve against the repository root (the historical
    behavior; the defaults are relative). Explicitly configured **absolute**
    entries are honored literally, including outside the repository — that is
    how a deployment points writes at persistent storage (e.g. the Docker
    image sets ``FRAMEFORGE_MCP_EDIT_ROOTS=/work/clients:/app/static/examples``
    so clients written over MCP outlive the ``--rm`` container).
    """
    configured = edit_roots
    if configured is None:
        configured = os.environ.get("FRAMEFORGE_MCP_EDIT_ROOTS")
    if configured is None:
        entries: list[str] = list(DEFAULT_CLIENT_ROOTS)
    elif isinstance(configured, str):
        entries = [entry for entry in configured.split(os.pathsep) if entry]
    else:
        entries = list(configured)

    roots: list[Path] = []
    for entry in entries:
        candidate = Path(entry).expanduser()
        resolved = candidate.resolve() if candidate.is_absolute() else (repo_root / candidate).resolve()
        roots.append(resolved)
    if not roots:
        raise ValueError("at least one editable SDK client root is required")
    return roots


def _resolve_client_path(
    path: str,
    *,
    repo_root: Path,
    edit_roots: str | list[str] | tuple[str, ...] | None,
    must_exist: bool,
) -> Path:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path must be a non-empty string")
    raw = Path(path).expanduser()
    if raw.suffix != ".py":
        raise ValueError("SDK client path must be a Python .py file")
    allowed_roots = _client_roots(repo_root, edit_roots)

    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw.resolve())
        # Legacy form: an absolute-looking path written repo-relative
        # ("/static/examples/foo.py") keeps resolving into the repository.
        candidates.append((repo_root / str(path).lstrip("/")).resolve())
    else:
        candidates.append((repo_root / raw).resolve())
        # A *bare* client name (no directory part) is searched across the
        # configured roots — that is how `write_sdk_client("poster.py")` lands
        # in the persistent root of a hardened deployment. A relative path
        # with directories stays an explicit repo-relative location claim.
        if len(raw.parts) == 1:
            for root in allowed_roots:
                candidates.append((root / raw).resolve())

    seen: set[Path] = set()
    allowed = [
        candidate
        for candidate in candidates
        if not (candidate in seen or seen.add(candidate))
        and any(_is_relative_to(candidate, root) for root in allowed_roots)
    ]
    if not allowed:
        raise ValueError("SDK client path must stay under the allowed SDK client roots")
    for candidate in allowed:
        if candidate.is_file():
            return candidate
    if must_exist:
        raise FileNotFoundError(str(allowed[0]))
    return allowed[0]


def _repo_relative_path(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root).as_posix()


def _display_path(path: Path, repo_root: Path) -> str:
    """Repo-relative when inside the repository, absolute POSIX otherwise.

    Roots outside the repository (persistent volumes) have no repo-relative
    form by construction; reporting must not raise for them.
    """
    resolved = path.resolve()
    if _is_relative_to(resolved, repo_root):
        return resolved.relative_to(repo_root).as_posix()
    return resolved.as_posix()


def _assert_input_path_allowed(path: str) -> None:
    """Confine propose inputs to ``FRAMEFORGE_MCP_INPUT_ROOTS`` when it is set.

    Unset (the default) preserves the open localhost-dev behavior: any readable
    path is accepted. Setting the env var to a ``os.pathsep``-joined list of roots
    locks the propose tools to those directories so the server cannot be used as a
    confused-deputy file reader in a hardened deployment.
    """
    configured = os.environ.get("FRAMEFORGE_MCP_INPUT_ROOTS")
    if not configured:
        return
    roots = [Path(entry).expanduser().resolve() for entry in configured.split(os.pathsep) if entry]
    if not roots:
        return
    resolved = Path(path).expanduser().resolve()
    if not any(_is_relative_to(resolved, root) for root in roots):
        raise ValueError("input path is outside the allowed FRAMEFORGE_MCP_INPUT_ROOTS")


def security_posture() -> dict[str, Any]:
    """The server's effective confinement, derived LIVE from the environment.

    Pure reporting — no side effects, no caching: every call re-reads the env
    vars, so flipping ``FRAMEFORGE_MCP_INPUT_ROOTS`` / ``FRAMEFORGE_MCP_KEEP_ENV``
    is reflected by the next call in the same process. The derivations mirror
    the enforcing code paths (:func:`_assert_input_path_allowed`,
    :func:`_client_roots`, the code-execution subprocess) so the report can
    never drift from what is actually enforced.
    """
    configured = os.environ.get("FRAMEFORGE_MCP_INPUT_ROOTS")
    input_roots = (
        [Path(entry).expanduser().resolve() for entry in configured.split(os.pathsep) if entry]
        if configured
        else []
    )
    # Empty-after-split matches _assert_input_path_allowed: no roots = open.
    input_mode = "restricted" if input_roots else "open"

    warnings: list[str] = []
    if input_mode == "open":
        warnings.append(
            "propose-input confinement is OFF (localhost-dev default): the propose_* "
            "tools accept any readable path; set FRAMEFORGE_MCP_INPUT_ROOTS to a "
            f"{os.pathsep!r}-joined list of roots to restrict them"
        )
    keep_env = _truthy_env("FRAMEFORGE_MCP_KEEP_ENV")
    if keep_env:
        warnings.append(
            "FRAMEFORGE_MCP_KEEP_ENV is set: secret-looking env vars are passed "
            "through to the code-execution subprocess"
        )

    return {
        "input_roots": {
            "mode": input_mode,
            "roots": [str(root) for root in input_roots],
            "env_var": "FRAMEFORGE_MCP_INPUT_ROOTS",
        },
        "edit_roots": [str(root) for root in _client_roots(_repo_root(None), None)],
        "code_execution": {
            "isolation": "subprocess",
            "sandboxed": False,
            "timeout_seconds_default": DEFAULT_TIMEOUT_SECONDS,
            "env_secret_stripping": not keep_env,
        },
        "warnings": warnings,
    }
