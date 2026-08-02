"""MCP integration for FrameForge SDK authoring feedback loops."""
from __future__ import annotations

from frameforge_mcp.envelope import ENVELOPE_SCHEMA, ToolEnvelope
from frameforge_mcp.extras import install_hint, lane_available, optional_backends
from frameforge_mcp.security import (
    INPUT_ROOTS_UNRESTRICTED,
    default_input_roots,
    security_posture,
)
from frameforge_mcp.server import (
    cleanup_sessions,
    create_server,
    fit_text,
    get_default_session_root,
    list_sessions,
    mcp_content_blocks,
    read_session_resource,
    render_frameforge_yaml,
    run,
    run_sdk_code,
)
# NOT `tool_facts` (the lookup function): binding it here would shadow the
# `frameforge_mcp.tool_facts` MODULE in the package namespace, so
# `from frameforge_mcp import tool_facts` would hand back a function. Reach the
# lookup as `frameforge_mcp.tool_facts.tool_facts` instead.
from frameforge_mcp.tool_facts import TOOL_FACTS, tool_facts_report

__all__ = [
    "ENVELOPE_SCHEMA",
    "INPUT_ROOTS_UNRESTRICTED",
    "TOOL_FACTS",
    "ToolEnvelope",
    "cleanup_sessions",
    "create_server",
    "default_input_roots",
    "fit_text",
    "get_default_session_root",
    "install_hint",
    "lane_available",
    "list_sessions",
    "mcp_content_blocks",
    "optional_backends",
    "read_session_resource",
    "render_frameforge_yaml",
    "run",
    "run_sdk_code",
    "security_posture",
    "tool_facts_report",
]
