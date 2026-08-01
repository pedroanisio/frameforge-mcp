"""Document sources — the one varying step of the feedback loop.

Every entry point (run SDK code, run an editable client, render raw YAML, render a
vision proposal) shares the same tail: open a session, **produce a FrameForge YAML
document**, then validate + render it. Only the production step differs. Each
:class:`DocumentSource` owns one way to produce that YAML; the uniform runner in
:mod:`frameforge_mcp.usecases` drives any of them. Adding a new way to obtain a
document is a new ``DocumentSource`` subclass — the runner does not change
(open/closed).

⚠ ARCHITECTURAL CONTRACT (PALS's LAW) — LLM OUTPUT IS UNVERIFIED BY DEFAULT
The SDK code, client files, and vision proposals these sources lower into YAML are
untrusted, possibly-incomplete model output. Producing the YAML is never the end of
the contract: the runner re-validates and re-renders every document so the caller
verifies against artifacts, not against the model's claim that it worked.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from frameforge_mcp.config import DEFAULT_TIMEOUT_SECONDS
from frameforge_mcp.discovery import _frameforge_yaml_snapshot, _new_generated_yaml
from frameforge_mcp.execution import (
    _apply_build_error,
    _harness_source,
    _subprocess_env,
    _subprocess_timeout_result,
)
from frameforge_mcp.paths import _repo_root, _session_root, get_default_repo_root
from frameforge_mcp.results import _base_result
from frameforge_mcp.security import (
    _display_path,
    _resolve_client_path,
)
from frameforge_mcp.sessions import _prepare_session, _reset_session_inputs, _session_id
from frameforge_sdk.provenance import PROVENANCE_ENV

_VISION_GROUP_HINT = (
    "The vision proposal lane needs the optional `vision` dependency group. "
    "Install it with `uv sync --group vision` (or launch the MCP server with "
    "`--group vision`)."
)

# The install instruction split out of the message, matching the shared envelope
# shape (`error` = what failed, `hint` = the actionable next step).
_VISION_INSTALL_HINT = (
    "install the optional `vision` dependency group: `uv sync --group vision` "
    "(or launch the MCP server with `--group vision`)"
)


def _vision_error(message: str, *, hint: str | None = None) -> dict[str, Any]:
    """The vision tools' structured failure envelope (`ok:false` + error [+ hint]).

    When the message is the combined :data:`_VISION_GROUP_HINT`, the install
    instruction is split into the envelope's separate ``hint`` field so the shape
    matches the server's `_error_envelope` (error = what failed, hint = the fix).
    """
    envelope: dict[str, Any] = {
        "ok": False, "error": message, "proposal": None, "renders": [], "resources": [],
    }
    if hint is None and message == _VISION_GROUP_HINT:
        envelope["error"] = "the optional `vision` dependency group is not installed"
        hint = _VISION_INSTALL_HINT
    if hint:
        envelope["hint"] = hint
    return envelope


def _proposal_summary(proposal: Any) -> dict[str, Any]:
    return {
        "object_count": len(proposal.observations),
        "detectors_run": list(proposal.detectors_run),
        "detectors_skipped": [{"name": s.name, "reason": s.reason} for s in proposal.detectors_skipped],
        "observations": [
            {
                "kind": o.kind,
                "bbox": [round(float(v), 2) for v in o.bbox] if o.bbox else None,
                "confidence": o.confidence,
                "detector": o.detector,
            }
            for o in proposal.observations
        ],
    }


@dataclass
class Produced:
    """The outcome of a source's ``produce`` step.

    ``proceed`` is ``True`` when the YAML was produced and the runner should
    validate + render it; ``False`` for a terminal result (a non-zero exit, a
    timeout, or a missing document) that the runner only finalizes. ``result`` is
    the partially-built result dict (already carrying stdout/stderr/returncode and,
    for terminal cases, ``ok``/``error``/``timed_out``); the runner merges the
    render outcome into it. ``base_dir`` is where the renderer resolves relative
    asset references.
    """

    sid: str
    session_dir: Path
    yaml_path: Path
    result: dict[str, Any]
    proceed: bool
    base_dir: Path | None = None


class DocumentSource:
    """Base for the four ways to obtain a FrameForge document for a session."""

    def __init__(self, *, session_id: str | None = None, session_root: str | Path | None = None) -> None:
        self.session_id = session_id
        self.session_root = session_root

    def _open(self) -> tuple[Path, str, Path, Path]:
        """Resolve the session root, validate the id, and prepare the scratch dir."""
        root = _session_root(self.session_root)
        sid = _session_id(self.session_id)
        session_dir = _prepare_session(root, sid)
        yaml_path = session_dir / "generated.fg.yaml"
        return root, sid, session_dir, yaml_path

    def produce(self) -> Produced:  # pragma: no cover - abstract
        raise NotImplementedError


class SdkCodeSource(DocumentSource):
    """Run caller-supplied Python SDK code in the sandboxed subprocess.

    The executed code receives two globals:

    - ``SESSION_DIR``: path to the per-session scratch directory.
    - ``OUTPUT_YAML_PATH``: path where generated FrameForge YAML should be written.

    If ``OUTPUT_YAML_PATH`` is not written, the harness derives YAML from a global
    named ``doc``, ``document``, or ``builder`` when it can.
    """

    def __init__(
        self,
        *,
        code: str,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        session_id: str | None = None,
        session_root: str | Path | None = None,
    ) -> None:
        super().__init__(session_id=session_id, session_root=session_root)
        self.code = code
        self.timeout_seconds = timeout_seconds

    def produce(self) -> Produced:
        _, sid, session_dir, yaml_path = self._open()
        _reset_session_inputs(session_dir)
        script_path = session_dir / "script.py"
        harness_path = session_dir / "_run_sdk.py"
        script_path.write_text(self.code, encoding="utf-8")
        harness_path.write_text(
            _harness_source(script_path, yaml_path, session_dir), encoding="utf-8"
        )

        env = _subprocess_env(get_default_repo_root())
        env.setdefault(PROVENANCE_ENV, "1")
        try:
            proc = subprocess.run(
                [sys.executable, str(harness_path)],
                cwd=str(session_dir),
                env=env,
                text=True,
                capture_output=True,
                timeout=max(1, int(self.timeout_seconds)),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            result = _subprocess_timeout_result(
                "SDK code", session_id=sid, session_dir=session_dir, yaml_path=yaml_path,
                exc=exc, timeout_seconds=self.timeout_seconds,
            )
            return Produced(sid, session_dir, yaml_path, result, proceed=False)

        result = _base_result(sid, session_dir, yaml_path, proc.stdout, proc.stderr, proc.returncode)
        if proc.returncode != 0:
            result["ok"] = False
            result["error"] = "sdk code exited with a non-zero status"
            _apply_build_error(result, session_dir)
            return Produced(sid, session_dir, yaml_path, result, proceed=False)
        if not yaml_path.exists():
            result["ok"] = False
            result["error"] = "sdk code did not generate FrameForge YAML"
            return Produced(sid, session_dir, yaml_path, result, proceed=False)
        return Produced(sid, session_dir, yaml_path, result, proceed=True, base_dir=session_dir)


class SdkClientSource(DocumentSource):
    """Run an editable Python SDK client file from the repository's safe roots."""

    def __init__(
        self,
        *,
        path: str,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        invoke_main: bool = False,
        repo_root: str | Path | None = None,
        edit_roots: str | list[str] | tuple[str, ...] | None = None,
        session_id: str | None = None,
        session_root: str | Path | None = None,
    ) -> None:
        super().__init__(session_id=session_id, session_root=session_root)
        self.path = path
        self.timeout_seconds = timeout_seconds
        self.invoke_main = invoke_main
        self.repo_root = repo_root
        self.edit_roots = edit_roots

    def produce(self) -> Produced:
        root = _repo_root(self.repo_root)
        client_path = _resolve_client_path(
            self.path, repo_root=root, edit_roots=self.edit_roots, must_exist=True
        )
        _, sid, session_dir, yaml_path = self._open()
        _reset_session_inputs(session_dir)
        harness_path = session_dir / "_run_sdk_client.py"
        snapshot = _frameforge_yaml_snapshot(root)

        harness_path.write_text(
            _harness_source(client_path, yaml_path, session_dir, invoke_main=self.invoke_main),
            encoding="utf-8",
        )
        env = _subprocess_env(root)
        env.setdefault(PROVENANCE_ENV, "1")
        client_fields = {
            "client_path": str(client_path),
            "client_uri": _display_path(client_path, root),
        }
        try:
            proc = subprocess.run(
                [sys.executable, str(harness_path)],
                cwd=str(root),
                env=env,
                text=True,
                capture_output=True,
                timeout=max(1, int(self.timeout_seconds)),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            result = _subprocess_timeout_result(
                "SDK client", session_id=sid, session_dir=session_dir, yaml_path=yaml_path,
                exc=exc, timeout_seconds=self.timeout_seconds,
            )
            result.update(client_fields)
            return Produced(sid, session_dir, yaml_path, result, proceed=False)

        result = _base_result(sid, session_dir, yaml_path, proc.stdout, proc.stderr, proc.returncode)
        result.update(client_fields)
        if proc.returncode != 0:
            result["ok"] = False
            result["error"] = "SDK client exited with a non-zero status"
            _apply_build_error(result, session_dir)
            return Produced(sid, session_dir, yaml_path, result, proceed=False)
        if not yaml_path.exists():
            generated = _new_generated_yaml(root, snapshot)
            if generated is not None:
                shutil.copyfile(generated, yaml_path)
                result["generated_yaml_source"] = str(generated)
        if not yaml_path.exists():
            result["ok"] = False
            result["error"] = "SDK client did not generate FrameForge YAML"
            return Produced(sid, session_dir, yaml_path, result, proceed=False)
        return Produced(sid, session_dir, yaml_path, result, proceed=True, base_dir=root)


class RawYamlSource(DocumentSource):
    """Render caller-provided FrameForge YAML directly, executing no Python."""

    def __init__(
        self,
        *,
        yaml_text: str,
        session_id: str | None = None,
        session_root: str | Path | None = None,
    ) -> None:
        super().__init__(session_id=session_id, session_root=session_root)
        self.yaml_text = yaml_text

    def produce(self) -> Produced:
        _, sid, session_dir, yaml_path = self._open()
        yaml_path.write_text(self.yaml_text, encoding="utf-8")
        result = _base_result(sid, session_dir, yaml_path, "", "", 0)
        return Produced(sid, session_dir, yaml_path, result, proceed=True, base_dir=session_dir)


class ProposalSource(DocumentSource):
    """Lower an (unverified) vision proposal into YAML for the verifying render."""

    def __init__(
        self,
        *,
        proposal: Any,
        session_id: str | None = None,
        session_root: str | Path | None = None,
    ) -> None:
        super().__init__(session_id=session_id, session_root=session_root)
        self.proposal = proposal

    def produce(self) -> Produced:
        import yaml as _yaml

        _, sid, session_dir, yaml_path = self._open()
        yaml_text = _yaml.safe_dump(dict(self.proposal.document), sort_keys=False, allow_unicode=True)
        yaml_path.write_text(yaml_text, encoding="utf-8")
        result = _base_result(sid, session_dir, yaml_path, "", "", 0)
        result["proposal"] = _proposal_summary(self.proposal)
        return Produced(sid, session_dir, yaml_path, result, proceed=True, base_dir=session_dir)
