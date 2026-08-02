"""The connection preamble is a budget, and it buys steering — not a manual.

The gap this file pins: the server's ``instructions`` string had grown to ~7,000
characters of SDK tour — every module, every catalog, every helper — and it is
sent on every connection, to every client, before the agent has asked anything.
That is a fixed context tax paid whether or not the session ever authors a
document, and it duplicates ``get_guide`` / the ``frameforge_guide`` prompt,
which exist precisely to serve that reference on demand.

It was also the largest attack surface in the server: instructions and tool
descriptions are injected into the model's context verbatim, which is the shape
the literature calls tool poisoning. Less text is less surface.

The trim is only safe if the *steering* survives — the handful of rules that
prevent expensive, silent mistakes. So this file asserts both directions: the
preamble is small, AND it still carries every rule an agent cannot recover on
its own.
"""
from __future__ import annotations

import pytest

from frameforge_mcp.guide import FRAMEFORGE_GUIDE
from frameforge_mcp.server import create_server

#: Ceiling for the connection preamble. Generous enough for the steering rules
#: below, tight enough that the SDK tour cannot creep back in.
INSTRUCTION_BUDGET = 2600


@pytest.fixture(scope="module")
def instructions(tmp_path_factory):
    root = tmp_path_factory.mktemp("instructions-sessions")
    server = create_server(session_root=root, structured_log_path=root / "log.jsonl")
    return server.instructions or ""


def test_the_preamble_fits_its_budget(instructions):
    assert len(instructions) <= INSTRUCTION_BUDGET, (
        f"instructions are {len(instructions)} chars, over the {INSTRUCTION_BUDGET} "
        "budget — move reference material into the guide, which is served on demand"
    )


def test_the_preamble_is_not_empty(instructions):
    """Trimming to nothing would be its own failure."""
    assert len(instructions) > 600


# --------------------------------------------------------------------------- #
#  What must survive: rules an agent cannot infer                              #
# --------------------------------------------------------------------------- #


def test_it_points_at_the_on_demand_reference(instructions):
    """The trim is a redirection, so the redirect has to be in the text."""
    assert "describe_capabilities" in instructions
    assert "get_guide" in instructions or "frameforge_guide" in instructions


def test_it_states_the_verification_contract(instructions):
    """PALS's Law is the architectural premise of the whole server."""
    assert "PALS" in instructions
    assert "unverified" in instructions.lower()


def test_it_warns_that_fonts_substitute_silently(instructions):
    """An unresolved family collapses the type with no error anywhere."""
    assert "list_fonts" in instructions


def test_it_names_the_deprecation_tools_as_the_first_step(instructions):
    """Two removed forms make a document unrenderable; the fix is mechanical."""
    assert "migrate_deprecated_forms" in instructions


def test_it_explains_that_a_missing_lane_is_uninstalled_not_broken(instructions):
    assert "uninstalled" in instructions.lower()


def test_it_names_the_typed_verification_signals(instructions):
    """The signals a screenshot cannot show — the reason the loop is worth running."""
    lowered = instructions.lower()
    assert "legibility" in lowered
    assert "paint" in lowered
    assert "overflow" in lowered


def test_it_documents_the_new_declarations(instructions):
    """Annotations, the result contract, and confinement are all new in 2.0."""
    lowered = instructions.lower()
    assert "read-only" in lowered or "destructive" in lowered
    assert "ok" in lowered


def test_it_names_the_session_uri_scheme(instructions):
    assert "frameforge://session/" in instructions


# --------------------------------------------------------------------------- #
#  Nothing was lost, only moved                                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "topic",
    ["planar", "outline", "separate", "patterns", "library", "svg_to_objects", "chevreul"],
)
def test_reference_material_removed_from_the_preamble_lives_in_the_guide(topic):
    assert topic in FRAMEFORGE_GUIDE, (
        f"{topic} was trimmed out of the instructions but is not in the guide — "
        "that is deletion, not redirection"
    )


def test_the_diagnostics_signals_are_all_documented_in_the_guide():
    for signal in ("diagnostics.overflow", "diagnostics.legibility", "diagnostics.paint"):
        assert signal in FRAMEFORGE_GUIDE, signal


def test_the_guide_names_the_standalone_report_entry_points():
    for entry in ("overflow_report", "legibility_report", "paint_report"):
        assert entry in FRAMEFORGE_GUIDE, entry
