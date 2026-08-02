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


#: The explicit opt-out. Set ``FRAMEFORGE_MCP_INPUT_ROOTS`` to this to accept any
#: readable path — the pre-2.0 behaviour, now something a deployment has to ask for.
INPUT_ROOTS_UNRESTRICTED = "*"

#: The remediation for a confinement refusal. Shared, because the propose tools
#: build their own envelope (``sources._vision_error``) rather than going through
#: ``server._error_envelope`` — so a hint written in only one of the two places
#: leaves the most likely post-2.0 failure with no route forward.
INPUT_ROOTS_HINT = (
    "file inputs are confined by default (session root, working directory, repository) "
    "so the server cannot be steered into reading arbitrary files; call "
    "describe_capabilities(topic='security') to see the roots in force, move the file "
    "under one of them, or set FRAMEFORGE_MCP_INPUT_ROOTS for this deployment"
)


def default_input_roots() -> list[Path]:
    """Where the propose/measure tools may read from when nothing is configured.

    Three roots, each earning its place from how the tools are actually used:

    * the **session root**, because chaining tools means reading back the PNG a
      previous render just wrote;
    * the **working directory**, because an agent driving a project refers to
      that project's own reference images, usually by relative path;
    * the **repository root**, because the SDK clients and example assets the
      server is pointed at live there.

    What this deliberately excludes is everything else on the machine — the
    dotfiles, key material, and credential stores that a confused deputy with
    the user's privileges would otherwise happily read into a model's context.
    """
    # Imported here: paths.py reads the environment on every call, and importing
    # it at module scope would freeze the session root at import time.
    from frameforge_mcp.paths import get_default_repo_root, get_default_session_root

    roots: list[Path] = []
    for candidate in (get_default_session_root(), Path.cwd(), get_default_repo_root()):
        try:
            resolved = Path(candidate).expanduser().resolve()
        except OSError:  # pragma: no cover - unresolvable cwd on a deleted dir
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _configured_input_roots() -> tuple[str, list[Path]]:
    """``(source, roots)`` for the current environment.

    ``source`` is ``"environment"``, ``"default"``, or ``"unrestricted"`` — the
    posture report needs to say not just *what* is enforced but *why*.
    """
    configured = os.environ.get("FRAMEFORGE_MCP_INPUT_ROOTS")
    if configured is None or not configured.strip():
        return "default", default_input_roots()
    entries = [entry for entry in configured.split(os.pathsep) if entry]
    if any(entry.strip() == INPUT_ROOTS_UNRESTRICTED for entry in entries):
        return "unrestricted", []
    roots = [Path(entry).expanduser().resolve() for entry in entries]
    if not roots:
        return "default", default_input_roots()
    return "environment", roots


def _assert_input_path_allowed(path: str) -> None:
    """Confine a tool's file input to the allowed roots.

    **Confined by default.** Before 2.0 an unset ``FRAMEFORGE_MCP_INPUT_ROOTS``
    accepted any readable path, which made the propose tools a confused-deputy
    file reader: an agent that could be steered into naming ``~/.ssh/id_rsa``
    would pull it into the model's context, using the user's own privileges to
    do it. Openness is now something a deployment asks for by setting the
    variable to ``*``; the default is the safe posture.
    """
    source, roots = _configured_input_roots()
    if source == "unrestricted":
        return
    resolved = Path(path).expanduser().resolve()
    if any(_is_relative_to(resolved, root) for root in roots):
        return
    allowed = ", ".join(str(root) for root in roots) or "(none)"
    raise ValueError(
        f"input path is outside the allowed input roots ({allowed}). Move the file "
        "under one of them, add its directory to FRAMEFORGE_MCP_INPUT_ROOTS "
        f"({os.pathsep!r}-joined), or set FRAMEFORGE_MCP_INPUT_ROOTS="
        f"{INPUT_ROOTS_UNRESTRICTED!r} to accept any readable path"
    )


def security_posture() -> dict[str, Any]:
    """The server's effective confinement, derived LIVE from the environment.

    Pure reporting — no side effects, no caching: every call re-reads the env
    vars, so flipping ``FRAMEFORGE_MCP_INPUT_ROOTS`` / ``FRAMEFORGE_MCP_KEEP_ENV``
    is reflected by the next call in the same process. The derivations mirror
    the enforcing code paths (:func:`_assert_input_path_allowed`,
    :func:`_client_roots`, the code-execution subprocess) so the report can
    never drift from what is actually enforced.
    """
    source, input_roots = _configured_input_roots()
    input_mode = "open" if source == "unrestricted" else "restricted"

    warnings: list[str] = []
    if input_mode == "open":
        warnings.append(
            "propose-input confinement is OFF: FRAMEFORGE_MCP_INPUT_ROOTS is set to "
            f"{INPUT_ROOTS_UNRESTRICTED!r}, so the propose_* tools accept ANY readable "
            "path — anything the server process can read can reach the model's "
            "context. Unset the variable to restore the confined default, or name "
            f"the roots explicitly as a {os.pathsep!r}-joined list"
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
            "source": source,
            "roots": [str(root) for root in input_roots],
            "env_var": "FRAMEFORGE_MCP_INPUT_ROOTS",
            "unrestricted_value": INPUT_ROOTS_UNRESTRICTED,
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
