"""Fresh-process discovery for long-running MCP servers.

The server process can outlive the checkout it imported.  Capability and guide
queries therefore run in a short-lived interpreter whose ``PYTHONPATH`` points
at the configured repository.  Results are cached by a cheap token covering the
Python source tree, so an unchanged checkout pays only file-stat and cache lookup
cost while an edit is visible on the next call.
"""
from __future__ import annotations

import functools
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from frameforge_mcp.execution import _subprocess_env
from frameforge_mcp.paths import _repo_root

_DISCOVERY_TIMEOUT_SECONDS = 15
_INTROSPECTION_SCRIPT = r"""
import json
import sys

from frameforge_mcp.util import _utc_now

request = json.load(sys.stdin)
action = request["action"]
if action == "describe_capabilities":
    from frameforge_mcp.discovery import describe_capabilities

    value = describe_capabilities(
        request.get("topic"),
        tool_names=request.get("tool_names"),
    )
elif action == "get_guide":
    from frameforge_mcp.guide import FRAMEFORGE_GUIDE

    value = FRAMEFORGE_GUIDE
else:
    raise ValueError(f"unknown live-discovery action: {action!r}")

json.dump({"value": value, "introspected_at": _utc_now()}, sys.stdout)
"""


def _source_roots(repo_root: Path) -> list[Path]:
    """Every source tree whose change must invalidate the discovery cache.

    The family is several distributions now. Hashing only the engine checkout
    would make a long-running server blind to a new SDK export or a changed
    tool in this very package — which is exactly the staleness issue #78
    closed, reopened by the split. Each sibling is resolved through the import
    system, so it follows an editable checkout, a git pin or a wheel, and is
    skipped when absent. A `<repo>/src/<pkg>` directory wins when present, so a
    vendored or fake-repo layout (the live-discovery test builds one) is
    honoured over the installed copy.
    """
    roots = [repo_root / "src" / "frameforge"]
    for mod in ("frameforge_sdk", "frameforge_mcp", "frameforge_coach"):
        vendored = repo_root / "src" / mod
        if vendored.is_dir():
            roots.append(vendored)
            continue
        try:
            pkg = __import__(mod)
        except ImportError:
            continue
        roots.append(Path(pkg.__file__).resolve().parent)
    return [r for r in roots if r.is_dir()]


def _source_token(repo_root: Path) -> str:
    """Return a cheap, deterministic freshness token for Python source metadata."""
    roots = _source_roots(repo_root)
    paths = [(root, p) for root in roots for p in sorted(root.rglob("*.py"))]
    if not paths:
        raise FileNotFoundError(
            f"no FrameForge Python sources found under {[str(r) for r in roots]}")
    digest = hashlib.sha256()
    for source_root, path in paths:
        stat = path.stat()
        digest.update(path.relative_to(source_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        digest.update(b":")
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\n")
    return f"py-stat-sha256:{digest.hexdigest()}"


def _run_request(
    repo_root: str,
    *,
    action: str,
    topic: str | None,
    tool_names: tuple[str, ...],
) -> str:
    """Execute one introspection request and return its JSON envelope."""
    root = Path(repo_root)
    request = {
        "action": action,
        "topic": topic,
        "tool_names": list(tool_names),
    }
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _INTROSPECTION_SCRIPT],
            cwd=str(root),
            env=_subprocess_env(root),
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=_DISCOVERY_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError(
            f"live discovery timed out after {_DISCOVERY_TIMEOUT_SECONDS} seconds"
        ) from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip()[-2_000:] or f"exit status {proc.returncode}"
        raise OSError(f"live discovery subprocess failed: {detail}")
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise OSError("live discovery subprocess returned invalid JSON") from exc
    if not isinstance(envelope, dict) or "value" not in envelope:
        raise OSError("live discovery subprocess returned an invalid envelope")
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))


@functools.lru_cache(maxsize=256)
def _cached_request(
    repo_root: str,
    source_token: str,
    action: str,
    topic: str | None,
    tool_names: tuple[str, ...],
) -> str:
    """Cache an immutable JSON response under the source-tree freshness token."""
    del source_token  # consumed by the cache key; the child needs only the request
    return _run_request(
        repo_root,
        action=action,
        topic=topic,
        tool_names=tool_names,
    )


def live_describe_capabilities(
    topic: str | None = None,
    *,
    tool_names: list[str] | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Describe the checkout visible on disk, not the server's import snapshot."""
    root = _repo_root(repo_root)
    source_token = _source_token(root)
    raw = _cached_request(
        str(root),
        source_token,
        "describe_capabilities",
        topic,
        tuple(sorted(tool_names or [])),
    )
    envelope = json.loads(raw)
    value = envelope["value"]
    if not isinstance(value, dict):
        raise OSError("live capability discovery returned a non-object payload")
    result = dict(value)
    result["introspected_at"] = str(envelope["introspected_at"])
    result["source_token"] = source_token
    return result


def live_guide(*, repo_root: str | Path | None = None) -> str:
    """Return guide text imported from the current checkout in a fresh process."""
    root = _repo_root(repo_root)
    source_token = _source_token(root)
    raw = _cached_request(str(root), source_token, "get_guide", None, ())
    value = json.loads(raw)["value"]
    if not isinstance(value, str):
        raise OSError("live guide discovery returned a non-string payload")
    return value
