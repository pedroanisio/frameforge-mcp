"""Tool output is a declared, validated contract — not an untyped dict.

The gap this file pins: input validation was thorough (every parameter carries
``Annotated[..., Field(description=...)]``), and output validation did not
exist. Tools returned bare ``dict[str, Any]``; ``_plain_tool_result`` hand-built
the ``structuredContent`` and nothing checked its shape, and no ``outputSchema``
was published, so a client had no machine-readable account of what came back.

Writing the contract down immediately found a real inconsistency: two tools —
``list_deprecated_forms`` and ``migrate_deprecated_forms`` — returned no ``ok``
key at all, while every error path and every other tool set one. A client
branching on ``result.ok`` got ``undefined`` from exactly the two tools the
README tells it to call *first*.
"""
from __future__ import annotations

import pytest

from frameforge_mcp import usecases
from frameforge_mcp.envelope import ENVELOPE_SCHEMA, ToolEnvelope, validate_envelope
from frameforge_mcp.server import _budget_result, _error_envelope, create_server


@pytest.fixture(scope="module")
def registered(tmp_path_factory):
    root = tmp_path_factory.mktemp("envelope-sessions")
    server = create_server(session_root=root, structured_log_path=root / "log.jsonl")
    return {tool.name: tool for tool in server._tool_manager.list_tools()}


# --------------------------------------------------------------------------- #
#  The contract itself                                                         #
# --------------------------------------------------------------------------- #


def test_ok_is_required_because_every_caller_branches_on_it():
    with pytest.raises(ValueError):
        ToolEnvelope.model_validate({"families": []})


def test_the_envelope_keeps_every_tool_specific_key():
    """The contract pins the SHARED keys; it must not truncate a tool's payload."""
    validated = ToolEnvelope.model_validate(
        {"ok": True, "families": ["Inter"], "family_count": 1}
    )
    assert validated.model_dump()["families"] == ["Inter"]
    assert validated.model_dump()["family_count"] == 1


def test_the_error_shape_is_part_of_the_contract():
    envelope = ToolEnvelope.model_validate(
        {"ok": False, "error": "boom", "error_type": "ValueError", "hint": "try harder"}
    )
    assert envelope.ok is False
    assert envelope.error == "boom"
    assert envelope.error_type == "ValueError"
    assert envelope.hint == "try harder"


def test_a_wrong_type_on_a_shared_key_is_rejected():
    with pytest.raises(ValueError):
        ToolEnvelope.model_validate({"ok": "yes"})
    with pytest.raises(ValueError):
        ToolEnvelope.model_validate({"ok": True, "renders": "none"})


def test_the_published_schema_documents_the_shared_keys():
    properties = ENVELOPE_SCHEMA["properties"]
    assert set(properties) >= {"ok", "error", "error_type", "hint", "renders", "resources"}
    assert ENVELOPE_SCHEMA["required"] == ["ok"]
    assert properties["ok"]["description"]


# --------------------------------------------------------------------------- #
#  The existing shapes all satisfy it                                          #
# --------------------------------------------------------------------------- #


def test_the_shared_error_envelope_validates():
    validate_envelope("read_sdk_client", _error_envelope("read_sdk_client", FileNotFoundError("x")))


def test_the_over_budget_summary_validates():
    """The budget refusal is itself a tool result — it has to satisfy the contract."""
    oversized = {"ok": True, "blob": "x" * 2_000_000}
    refused = _budget_result("run_sdk_code", oversized)
    assert refused["ok"] is False
    validate_envelope("run_sdk_code", refused)


def test_validate_envelope_names_the_tool_when_a_result_is_malformed():
    """A server bug must be identifiable, not a generic pydantic traceback."""
    with pytest.raises(ValueError) as caught:
        validate_envelope("list_fonts", {"families": []})
    assert "list_fonts" in str(caught.value)


# --------------------------------------------------------------------------- #
#  The defect the contract exposed                                             #
# --------------------------------------------------------------------------- #


def test_list_deprecated_forms_reports_ok():
    """Regression: this returned no `ok` key, so `result.ok` was undefined."""
    result = usecases.list_deprecated_forms()
    assert result["ok"] is True
    validate_envelope("list_deprecated_forms", result)


def test_migrate_deprecated_forms_reports_ok():
    result = usecases.migrate_deprecated_forms("pages: []")
    assert result["ok"] is True
    validate_envelope("migrate_deprecated_forms", result)


def test_migrate_deprecated_forms_keeps_reporting_its_findings():
    """Adding `ok` must not disturb the payload the tool already returned."""
    result = usecases.migrate_deprecated_forms("pages: []")
    assert "findings" in result
    assert "registry_size" in result


# --------------------------------------------------------------------------- #
#  The server publishes and enforces it                                        #
# --------------------------------------------------------------------------- #


def test_every_structured_tool_publishes_an_output_schema(registered):
    missing = sorted(
        name
        for name, tool in registered.items()
        if name != "get_guide" and tool.output_schema is None
    )
    assert not missing, f"tools publishing no outputSchema: {missing}"


def test_the_published_output_schema_is_the_envelope(registered):
    schema = registered["render_frameforge_yaml"].output_schema
    assert schema["required"] == ["ok"]
    assert set(schema["properties"]) >= {"ok", "error", "renders", "resources"}


def test_the_text_returning_tool_declares_no_structured_output(registered):
    """`get_guide` returns prose, not an envelope — claiming one would be a lie."""
    assert registered["get_guide"].output_schema is None


def test_the_output_model_is_wired_so_fastmcp_actually_validates(registered):
    """An outputSchema without an output_model is published but never enforced."""
    for name, tool in registered.items():
        if name == "get_guide":
            continue
        assert tool.fn_metadata.output_model is not None, name
