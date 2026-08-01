"""Structured JSONL logging of every tool instruction and response."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from frameforge_mcp.config import (
    SECRET_LITERAL_RE,
    STRUCTURED_LOG_MAX_BYTES,
    STRUCTURED_LOG_MAX_FIELD_CHARS,
    STRUCTURED_LOG_SCHEMA,
)
from frameforge_mcp.util import _utc_now


def _structured_log_path(session_root: Path, configured: str | Path | None) -> Path:
    path = configured
    if path is None:
        path = os.environ.get("FRAMEFORGE_MCP_STRUCT_LOG_PATH")
    if path is None:
        path = session_root / "mcp-structured-log.jsonl"
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _logged_call(log_path: Path, tool: str, instruction: dict[str, Any], call):
    started_at = _utc_now()
    try:
        response = call()
    except Exception as exc:
        _append_structured_log(
            log_path,
            {
                "schema": STRUCTURED_LOG_SCHEMA,
                "timestamp": started_at,
                "tool": tool,
                "instruction": _json_safe(instruction),
                "response": {
                    "ok": False,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                },
            },
        )
        raise
    _append_structured_log(
        log_path,
        {
            "schema": STRUCTURED_LOG_SCHEMA,
            "timestamp": started_at,
            "tool": tool,
            "instruction": _json_safe(instruction),
            "response": _json_safe(response),
        },
    )
    return response


def _append_structured_log(path: Path, event: dict[str, Any]) -> None:
    # Redact BEFORE truncating: both the success and exception paths funnel here,
    # and both operate on rebuilt copies so the caller's response is never mutated.
    line = json.dumps(
        _truncate_log_strings(_redact_secrets(event)), ensure_ascii=False, sort_keys=True
    ) + "\n"
    try:
        if path.exists() and path.stat().st_size + len(line.encode("utf-8")) > STRUCTURED_LOG_MAX_BYTES:
            path.replace(path.with_name(path.name + ".1"))
    except OSError:
        pass
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def _redact_secrets(value: Any) -> Any:
    """Mask secret-looking key-value literals in a COPY destined for the log.

    The value becomes ``[REDACTED]`` while the key name stays visible for
    debugging (see ``SECRET_LITERAL_RE``). Containers are rebuilt, never
    mutated, so the response object returned to the caller keeps the raw text.
    """
    if isinstance(value, dict):
        return {key: _redact_secrets(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    if isinstance(value, str):
        return SECRET_LITERAL_RE.sub(
            lambda match: f"{match.group('key')}{match.group('sep')}[REDACTED]", value
        )
    return value


def _truncate_log_strings(value: Any) -> Any:
    """Clamp oversized strings so one giant payload cannot bloat (or leak) the log."""
    if isinstance(value, dict):
        return {key: _truncate_log_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate_log_strings(item) for item in value]
    if isinstance(value, str) and len(value) > STRUCTURED_LOG_MAX_FIELD_CHARS:
        kept = value[:STRUCTURED_LOG_MAX_FIELD_CHARS]
        return f"{kept}…[truncated {len(value) - STRUCTURED_LOG_MAX_FIELD_CHARS} chars]"
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        json.dumps(value)
    except TypeError:
        return repr(value)
    return value
