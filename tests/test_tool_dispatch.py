"""End-to-end: a real ``tools/call`` through FastMCP, with everything wired.

The gap this file pins: nothing exercised the server's own dispatch path. Four
test files covered use cases, extras, deprecations, and font closures — all
*below* the tool layer — so registration, argument validation, the error
envelope, the transport budget, and result shaping were only ever run by hand.

That layer now carries three additions that can each fail silently: the async
offload (a broken signature rebuild degrades to "no context" with no error), the
published output schema (which FastMCP *enforces*, so a malformed envelope
becomes a runtime failure rather than a quiet one), and the annotations. These
tests drive the same entry point a host does — ``FastMCP.call_tool`` — so a
break in any of them surfaces here rather than in a client.
"""
from __future__ import annotations

import json

import anyio
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from frameforge_mcp.server import create_server


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("dispatch-sessions")
    return create_server(session_root=root, structured_log_path=root / "dispatch.jsonl")


def call(server, name, **arguments):
    """Drive a tool the way a host does, returning the structured payload."""
    result = anyio.run(lambda: server.call_tool(name, arguments))
    # FastMCP returns either a CallToolResult (our shaped tools) or an
    # (unstructured, structured) pair; normalise to the structured dict.
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured
    if isinstance(result, tuple):
        return result[1]
    return result


# --------------------------------------------------------------------------- #
#  A read-only tool round-trips                                                #
# --------------------------------------------------------------------------- #


def test_a_read_only_tool_returns_a_validated_envelope(server):
    payload = call(server, "list_sessions")
    assert payload["ok"] is True
    assert "sessions" in payload


def test_the_deprecation_registry_round_trips(server):
    """The tool that used to return no `ok` — now validated by the output schema."""
    payload = call(server, "list_deprecated_forms")
    assert payload["ok"] is True
    assert payload["deprecations"]


def test_a_tool_with_arguments_validates_and_runs(server):
    payload = call(server, "migrate_deprecated_forms", yaml_text="pages: []")
    assert payload["ok"] is True
    assert "findings" in payload


def test_the_prose_tool_returns_text_not_an_envelope(server):
    """`get_guide` declares no output schema, so it must still come back as content."""
    result = anyio.run(lambda: server.call_tool("get_guide", {}))
    text = json.dumps(result, default=str)
    assert "FrameForge" in text


# --------------------------------------------------------------------------- #
#  Failures stay structured                                                    #
# --------------------------------------------------------------------------- #


def test_an_expected_failure_is_an_ok_false_envelope_not_an_exception(server):
    payload = call(server, "read_sdk_client", path="static/examples/nope.py")
    assert payload["ok"] is False
    assert payload["error_type"] == "FileNotFoundError"
    assert "list_sdk_clients" in payload["hint"]


def test_a_path_outside_the_client_roots_is_refused_with_its_own_hint(server):
    payload = call(server, "read_sdk_client", path="does/not/exist.py")
    assert payload["ok"] is False
    assert payload["error_type"] == "ValueError"
    assert "allowed_roots" in payload["hint"]


def test_a_confined_input_path_is_refused_with_an_actionable_hint(server, monkeypatch, tmp_path):
    """The 2.0 confinement, seen from the wire."""
    monkeypatch.setenv("FRAMEFORGE_MCP_INPUT_ROOTS", str(tmp_path))
    payload = call(server, "propose_from_image", image_path="/etc/passwd")
    assert payload["ok"] is False
    assert "input roots" in payload["error"]
    assert "describe_capabilities" in payload["hint"]


def test_a_missing_required_argument_is_rejected_by_the_input_schema(server):
    """Argument validation must survive the async signature rebuild."""
    with pytest.raises(ToolError):
        anyio.run(lambda: server.call_tool("migrate_deprecated_forms", {}))


def test_an_unknown_tool_is_an_error(server):
    with pytest.raises(ToolError):
        anyio.run(lambda: server.call_tool("no_such_tool", {}))


# --------------------------------------------------------------------------- #
#  The declarations reach the wire                                             #
# --------------------------------------------------------------------------- #


def test_list_tools_publishes_annotations_titles_and_output_schemas(server):
    tools = {tool.name: tool for tool in anyio.run(server.list_tools)}

    assert len(tools) == 35
    listed = tools["run_sdk_code"]
    assert listed.annotations.readOnlyHint is False
    assert listed.annotations.destructiveHint is True
    assert listed.annotations.openWorldHint is True
    assert listed.title == "Run SDK code"
    assert listed.outputSchema["required"] == ["ok"]

    read_only = tools["list_fonts"]
    assert read_only.annotations.readOnlyHint is True
    assert read_only.annotations.destructiveHint is False


def test_the_injected_context_is_absent_from_every_published_input_schema(server):
    for tool in anyio.run(server.list_tools):
        assert "ctx" not in tool.inputSchema.get("properties", {}), tool.name


def test_parameter_descriptions_survive_the_async_wrapper(server):
    """Regression: the wrapper resolves annotations itself, so `Annotated` metadata
    is exactly what a rebuild can silently drop — taking every parameter
    description with it."""
    tools = {tool.name: tool for tool in anyio.run(server.list_tools)}
    properties = tools["render_frameforge_yaml"].inputSchema["properties"]
    assert properties["yaml_text"]["description"]
    assert "session" in properties["session_id"]["description"].lower()


# --------------------------------------------------------------------------- #
#  The audit trail still records what the tool layer did                       #
# --------------------------------------------------------------------------- #


def test_every_dispatched_call_lands_in_the_structured_log(server, tmp_path_factory):
    call(server, "list_sessions")
    log = next(
        path
        for path in tmp_path_factory.getbasetemp().rglob("dispatch.jsonl")
    )
    events = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert any(event["tool"] == "list_sessions" for event in events)
    assert all("schema" in event for event in events)


def test_discovery_serves_the_declarations_in_band(server):
    """A client that does not surface annotations can still read them as data."""
    payload = call(server, "describe_capabilities", topic="tools")
    declarations = payload["declarations"]["tools"]
    assert declarations["run_sdk_code"]["destructive"] is True
    assert declarations["list_fonts"]["read_only"] is True
    assert declarations["cleanup_sessions"]["writes"]


def test_discovery_serves_the_result_contract(server):
    payload = call(server, "describe_capabilities", topic="envelope")
    assert payload["envelope"]["json_schema"]["required"] == ["ok"]
