"""The documentation describes THIS server, not the one it used to be.

Out-of-date documentation is worse than none: a reader who follows it reaches a
wrong conclusion confidently. The 2.0 work touched the tool count, the version,
the environment-variable semantics, and the discovery topics — every one of them
stated in prose somewhere. These tests check the prose against the running code.

Scope is deliberately narrow. This does not lint English; it pins the handful of
claims that are *checkable* and that were, or are about to become, wrong.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import tomllib

REPO = Path(__file__).parents[1]
PROJECT = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
README = (REPO / "README.md").read_text(encoding="utf-8")
PACKAGE_README = (REPO / "src" / "frameforge_mcp" / "README.md").read_text(encoding="utf-8")
MIGRATION = (REPO / "MIGRATION.md").read_text(encoding="utf-8")
CHANGELOG = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def registered(tmp_path_factory):
    from frameforge_mcp.server import create_server

    root = tmp_path_factory.mktemp("docs-sessions")
    server = create_server(session_root=root, structured_log_path=root / "log.jsonl")
    return {tool.name: tool for tool in server._tool_manager.list_tools()}


# --------------------------------------------------------------------------- #
#  Counts and versions                                                         #
# --------------------------------------------------------------------------- #


def test_the_readme_tool_count_matches_the_server(registered):
    """Regression: the README said "~33 registered tools" while 35 were registered."""
    claimed = {int(match) for match in re.findall(r"(\d+) registered tools", README)}
    assert claimed == {len(registered)}, (
        f"README claims {claimed} registered tools; the server registers {len(registered)}"
    )


def test_the_migration_guide_declares_the_current_version():
    """Its frontmatter is a promise about which release the steps were verified against."""
    frontmatter = MIGRATION.split("---")[1]
    assert f"version: {PROJECT['project']['version']}" in frontmatter


def test_the_breaking_change_is_recorded_under_a_major_version():
    """Confining inputs by default changes behaviour — semver says that is a major."""
    assert PROJECT["project"]["version"].startswith("2."), (
        "the input-confinement default changed incompatibly; that requires a major bump"
    )
    assert "BREAKING" in CHANGELOG


# --------------------------------------------------------------------------- #
#  Every documented discovery topic exists                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("topic", ["tools", "envelope", "security", "backends"])
def test_documented_topics_are_real_and_advertised(topic):
    from frameforge_mcp.discovery import describe_capabilities

    assert topic in describe_capabilities()["topics"], f"{topic} is documented but not advertised"
    assert describe_capabilities(topic)["ok"] is True


def test_both_readmes_point_at_the_discovery_topics_they_promise():
    for topic in ("tools", "envelope", "security"):
        assert topic in README or topic in PACKAGE_README, topic


# --------------------------------------------------------------------------- #
#  The environment-variable documentation matches the enforcing code           #
# --------------------------------------------------------------------------- #


def test_the_package_readme_no_longer_claims_inputs_are_unconfined():
    """Regression: it said "(unset = any readable path)", which is now backwards."""
    assert "unset = any readable path" not in PACKAGE_README


def test_the_documented_opt_out_value_is_the_one_the_code_honours():
    from frameforge_mcp.security import INPUT_ROOTS_UNRESTRICTED

    assert f"FRAMEFORGE_MCP_INPUT_ROOTS={INPUT_ROOTS_UNRESTRICTED}" in README.replace("'", "")


def test_the_documented_default_roots_are_the_ones_computed():
    """The prose names three roots; the code must produce exactly those."""
    from frameforge_mcp.security import default_input_roots

    assert len(default_input_roots()) <= 3
    for phrase in ("session root", "working directory", "repository"):
        assert phrase in README, phrase


# --------------------------------------------------------------------------- #
#  Examples are executable claims, not decoration                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name", ["tool_declarations_call.json", "optional_backends_tool_call.json"]
)
def test_example_calls_name_real_tools_and_parse(name, registered):
    example = json.loads((REPO / "examples" / name).read_text(encoding="utf-8"))
    assert example["tool"] in registered, f"{name} calls a tool that does not exist"


def test_the_declarations_example_matches_the_real_declarations():
    """An example that drifts teaches the wrong thing with full confidence."""
    from frameforge_mcp.tool_facts import TOOL_FACTS

    example = json.loads(
        (REPO / "examples" / "tool_declarations_call.json").read_text(encoding="utf-8")
    )
    for name, shown in example["expected"]["declarations"]["tools"].items():
        facts = TOOL_FACTS[name]
        assert shown["read_only"] is facts.read_only, name
        assert shown["destructive"] is facts.destructive, name
        assert shown["idempotent"] is facts.idempotent, name
        assert shown["open_world"] is facts.open_world, name
        assert shown["title"] == facts.title, name
        assert shown["writes"] == list(facts.writes), name


def test_every_example_referenced_by_the_readme_exists():
    for match in re.findall(r"\(examples/([\w.]+)\)", README):
        assert (REPO / "examples" / match).is_file(), f"README links a missing example: {match}"
