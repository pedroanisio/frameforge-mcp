"""Builders for the structured result dict and the on-disk diagnostics file."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from frameforge_sdk.validate import ValidationReport

from frameforge_mcp.transport import mcp_content_blocks


def _base_result(
    session_id: str,
    session_dir: Path,
    yaml_path: Path,
    stdout: str,
    stderr: str,
    returncode: int,
) -> dict[str, Any]:
    return {
        "ok": True,
        "session_id": session_id,
        "session_dir": str(session_dir),
        "yaml_path": str(yaml_path),
        "yaml_uri": f"frameforge://session/{session_id}/document.yaml",
        "diagnostics_path": str(session_dir / "diagnostics.json"),
        "diagnostics_uri": f"frameforge://session/{session_id}/diagnostics.json",
        "stdout": stdout,
        "stderr": stderr,
        "returncode": returncode,
        "validation": {"ok": False, "issues": []},
        "renders": [],
        "resources": [],
    }


def _validation_payload(report: ValidationReport) -> dict[str, Any]:
    return {
        "ok": report.ok,
        "issues": [
            {
                "rule_id": issue.rule_id,
                "severity": issue.severity,
                "path": issue.path,
                "message": issue.message,
            }
            for issue in report.issues
        ],
    }


def _resource_links(session_id: str, *, renders: list[dict[str, Any]]) -> list[dict[str, str]]:
    links = [
        {
            "type": "resource_link",
            "uri": f"frameforge://session/{session_id}/document.yaml",
            "name": "generated.fg.yaml",
            "mimeType": "application/x-yaml",
        },
        {
            "type": "resource_link",
            "uri": f"frameforge://session/{session_id}/diagnostics.json",
            "name": "diagnostics.json",
            "mimeType": "application/json",
        },
    ]
    for render in renders:
        path = Path(str(render.get("path", "")))
        links.append(
            {
                "type": "resource_link",
                "uri": str(render["uri"]),
                "name": path.name or f"page-{int(render['page']):03d}",
                "mimeType": str(render["mimeType"]),
            }
        )
    return links


def _render_failure(
    session_id: str, report: ValidationReport, error: str, *, warning: str | None = None
) -> dict[str, Any]:
    """Structured result for a render that crashed or timed out (validation passed)."""
    result: dict[str, Any] = {
        "ok": False,
        "error": error,
        "validation": _validation_payload(report),
        "renders": [],
        "resources": _resource_links(session_id, renders=[]),
    }
    if warning:
        result["render_warning"] = warning
    return result


def _write_diagnostics(session_dir: Path, result: dict[str, Any]) -> None:
    safe = dict(result)
    safe["content"] = mcp_content_blocks(result)[:1]
    (session_dir / "diagnostics.json").write_text(
        json.dumps(safe, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
