#!/usr/bin/env python3
"""test_deprecations.py — the MCP server exposes the contract's deprecation lint.

The tools here are the step *before* `render_frameforge_yaml`. Two of the
contract's deprecated forms are rejected outright, so a document carrying them
never reaches a render at all — an agent holding one gets "does not validate"
and no route forward. `migrate_deprecated_forms` is that route, and
`list_deprecated_forms` is the reference it reads first.

Both are adapters over `frameforge_api.deprecations`. These tests assert the
adaptation — the envelope shape an agent actually receives, and that the tools
stay session-free and side-effect-free — not the codemod's rules, which are the
contract package's to test.
"""
from __future__ import annotations

import pytest

yaml = pytest.importorskip("yaml")

from frameforge_api import DEPRECATIONS
from frameforge_mcp.usecases import list_deprecated_forms, migrate_deprecated_forms

LEGACY = """
dsl: FrameForge
version: 2.2.0
title: legacy
pages:
  - mode: page
    id: p1
    canvas: {size: [400, 200], units: px}
    layers:
      - id: main
        objects:
          - {type: circle, id: c, center: [50, 50], r: 20, fill: '#d4145a'}
          - {type: line, id: l, from: [0, 0], to: [9, 9],
             stroke: {color: '#000', width: 2}}
"""

CLEAN = """
dsl: FrameForge
version: 2.11.0
title: clean
pages:
  - mode: page
    id: p1
    canvas: {size: [400, 200], units: px}
    layers:
      - id: main
        objects:
          - {type: text, box: [20, 20, 360, 40], text: Hello}
"""


# --------------------------------------------------------------------------- #
#  list_deprecated_forms                                                      #
# --------------------------------------------------------------------------- #
def test_the_registry_tool_returns_the_whole_registry():
    result = list_deprecated_forms()
    assert {d["id"] for d in result["deprecations"]} == {d.id for d in DEPRECATIONS}
    assert result["contract_version"].startswith("2.")


def test_the_registry_tool_states_the_compatibility_rule():
    """An agent deciding whether to rewrite a document needs to know the forms
    are still ACCEPTED — otherwise it reads "deprecated" as "broken" and
    rewrites documents nobody asked it to touch."""
    result = list_deprecated_forms()
    assert result["compatibility"] == "backward"
    assert any(d["valid_at_head"] for d in result["deprecations"])
    assert any(not d["valid_at_head"] for d in result["deprecations"])


def test_every_registry_entry_carries_a_replacement_and_a_reason():
    for entry in list_deprecated_forms()["deprecations"]:
        assert entry["replacement"] and entry["note"]
        assert entry["fix"] in ("automatic", "manual")
        assert entry["severity"] in ("info", "warning", "error")


def test_the_registry_result_is_json_serialisable():
    """It crosses the MCP transport, so anything exotic in it is a runtime error
    at the worst possible moment."""
    import json

    assert json.loads(json.dumps(list_deprecated_forms()))


# --------------------------------------------------------------------------- #
#  migrate_deprecated_forms                                                   #
# --------------------------------------------------------------------------- #
def test_reporting_is_the_default_and_returns_no_document():
    result = migrate_deprecated_forms(LEGACY)
    assert result["changed"] is True
    assert "migrated_yaml" not in result, "reporting must not hand back a rewrite"
    assert {f["id"] for f in result["findings"]} == {
        "deprecated-alias-circle", "stroke-single-form"}


def test_apply_returns_a_document_that_validates():
    """The whole point. An agent gets back YAML it can send straight to
    `render_frameforge_yaml`, which the input could never have reached."""
    from frameforge_api import Document

    result = migrate_deprecated_forms(LEGACY, apply=True)
    migrated = yaml.safe_load(result["migrated_yaml"])
    Document.model_validate(migrated)
    assert result["clean"] is True


def test_the_input_document_is_rejected_before_migration():
    """States the premise the tool exists for, so it cannot quietly stop being
    true: this document cannot reach a render on its own."""
    from frameforge_api import Document

    with pytest.raises(Exception):
        Document.model_validate(yaml.safe_load(LEGACY))


def test_a_clean_document_reports_nothing_and_is_unchanged():
    result = migrate_deprecated_forms(CLEAN, apply=True)
    assert result["changed"] is False and result["findings"] == []
    assert yaml.safe_load(result["migrated_yaml"]) == yaml.safe_load(CLEAN)


def test_migration_is_idempotent_across_the_tool_boundary():
    once = migrate_deprecated_forms(LEGACY, apply=True)["migrated_yaml"]
    twice = migrate_deprecated_forms(once, apply=True)
    assert twice["changed"] is False
    assert yaml.safe_load(twice["migrated_yaml"]) == yaml.safe_load(once)


def test_what_the_codemod_refuses_is_reported_and_marks_the_result_unclean():
    """`clean` answers "is the migration finished", not "was anything found" —
    an agent that treats `changed` as success would stop half way."""
    doc = yaml.safe_load(LEGACY)
    doc["pages"][0]["layers"][0]["objects"][1]["stroke_style"] = "hairline"
    result = migrate_deprecated_forms(yaml.safe_dump(doc), apply=True)
    assert result["clean"] is False
    assert [f["id"] for f in result["manual"]] == ["stroke-single-form"]
    assert "restyle" in result["manual"][0]["detail"]


def test_findings_carry_a_json_pointer_a_replacement_and_a_severity():
    (first, *_) = migrate_deprecated_forms(LEGACY)["findings"]
    assert first["path"].startswith("/")
    assert first["replacement"]
    assert first["severity"] in ("info", "warning", "error")
    assert first["code"], "the engine validator's code, so the two reports join"


@pytest.mark.parametrize("bad", ["", "   ", None, 42])
def test_junk_input_raises_a_value_error_for_the_envelope(bad):
    """`_enveloped` lowers ValueError into an error envelope; anything else
    escapes as a server-side crash the agent cannot act on."""
    with pytest.raises(ValueError):
        migrate_deprecated_forms(bad)


def test_unparseable_yaml_is_a_value_error_not_a_traceback():
    with pytest.raises(ValueError, match="parseable"):
        migrate_deprecated_forms("key: [unclosed\n  - {")


def test_a_yaml_scalar_is_not_a_document():
    with pytest.raises(ValueError, match="mapping"):
        migrate_deprecated_forms("just a string")


def test_json_is_accepted_too_because_json_is_yaml():
    import json

    result = migrate_deprecated_forms(json.dumps(yaml.safe_load(LEGACY)))
    assert result["changed"] is True


# --------------------------------------------------------------------------- #
#  Wiring                                                                     #
# --------------------------------------------------------------------------- #
def test_both_tools_are_registered_on_the_live_server():
    """A use case nothing exposes is a use case no agent can reach.

    Asserted against a real `create_server()` rather than by grepping the
    source, because the decorator is what actually registers a tool and a
    module-level function that never reached `@server.tool()` would read the
    same either way.
    """
    import asyncio

    from frameforge_mcp.server import create_server

    names = {t.name for t in asyncio.run(create_server().list_tools())}
    assert {"list_deprecated_forms", "migrate_deprecated_forms"} <= names


def test_the_tools_are_importable_from_the_server_facade():
    """`from frameforge_mcp.server import ...` is the documented way in, and the
    module keeps that surface deliberately."""
    from frameforge_mcp import server as server_module

    assert callable(server_module.list_deprecated_forms)
    assert callable(server_module.migrate_deprecated_forms)


def test_the_migrate_tool_declares_its_parameters_to_the_agent():
    """An agent picks a tool from its schema. An undescribed `apply` flag is a
    flag nothing will ever set."""
    import asyncio

    from frameforge_mcp.server import create_server

    tool = next(t for t in asyncio.run(create_server().list_tools())
                if t.name == "migrate_deprecated_forms")
    props = tool.inputSchema["properties"]
    assert set(props) == {"yaml_text", "apply"}
    assert "does NOT have to be valid" in props["yaml_text"]["description"]
    assert "migrated_yaml" in props["apply"]["description"]
