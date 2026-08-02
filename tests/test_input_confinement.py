"""The propose/measure tools read files under confinement by default.

The gap this file pins: ``FRAMEFORGE_MCP_INPUT_ROOTS`` unset meant *any readable
path* was accepted. An agent that could be steered — by a poisoned document, a
crafted filename, or an over-eager plan — could ask ``propose_from_image`` for
``~/.ssh/id_rsa`` or ``~/.aws/credentials``, and the file's content would flow
straight into the model's context. That is the confused-deputy shape: the
server has the user's filesystem privileges and no reason of its own to refuse.

The posture is now inverted. Confinement is the default and openness is a
deliberate, visible choice (``FRAMEFORGE_MCP_INPUT_ROOTS=*``), so the safe
configuration is the one you get by not thinking about it.

This is a BEHAVIOUR CHANGE, which is why it lands with a major version bump —
a deployment that reads images from outside the project must now say so.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from frameforge_mcp.security import (
    _assert_input_path_allowed,
    default_input_roots,
    security_posture,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("FRAMEFORGE_MCP_INPUT_ROOTS", raising=False)
    monkeypatch.delenv("FRAMEFORGE_MCP_KEEP_ENV", raising=False)


# --------------------------------------------------------------------------- #
#  The default posture is confined                                             #
# --------------------------------------------------------------------------- #


def test_an_arbitrary_absolute_path_is_refused_by_default():
    """The reported gap, stated as an acceptance criterion."""
    with pytest.raises(ValueError, match="outside the allowed"):
        _assert_input_path_allowed("/etc/passwd")


def test_a_home_directory_secret_is_refused_by_default():
    with pytest.raises(ValueError, match="outside the allowed"):
        _assert_input_path_allowed(str(Path.home() / ".ssh" / "id_rsa"))


def test_the_refusal_names_the_variable_that_relaxes_it():
    """A refusal a caller cannot act on is a dead end, not a guardrail."""
    with pytest.raises(ValueError) as caught:
        _assert_input_path_allowed("/etc/passwd")
    assert "FRAMEFORGE_MCP_INPUT_ROOTS" in str(caught.value)


def test_the_session_root_is_readable_by_default(monkeypatch, tmp_path):
    """Chaining tools requires reading back what a previous render wrote."""
    monkeypatch.setenv("FRAMEFORGE_MCP_SESSION_ROOT", str(tmp_path / "sessions"))
    probe = tmp_path / "sessions" / "s1" / "page-1.png"
    probe.parent.mkdir(parents=True)
    probe.write_bytes(b"x")
    _assert_input_path_allowed(str(probe))


def test_the_working_directory_is_readable_by_default(tmp_path, monkeypatch):
    """An agent working in a project reaches its own files by relative path."""
    monkeypatch.chdir(tmp_path)
    probe = tmp_path / "reference.png"
    probe.write_bytes(b"x")
    _assert_input_path_allowed("reference.png")
    _assert_input_path_allowed(str(probe))


def test_default_roots_are_reported_not_guessed():
    roots = default_input_roots()
    assert roots, "the confined default must name at least one readable root"
    assert all(isinstance(root, Path) and root.is_absolute() for root in roots)


# --------------------------------------------------------------------------- #
#  Opting out is explicit and visible                                          #
# --------------------------------------------------------------------------- #


def test_a_star_opens_the_server_back_up(monkeypatch):
    monkeypatch.setenv("FRAMEFORGE_MCP_INPUT_ROOTS", "*")
    _assert_input_path_allowed("/etc/passwd")


def test_opting_out_is_reported_as_a_warning(monkeypatch):
    """An operator must be able to see that the guard is off."""
    monkeypatch.setenv("FRAMEFORGE_MCP_INPUT_ROOTS", "*")
    posture = security_posture()
    assert posture["input_roots"]["mode"] == "open"
    assert any("confinement is OFF" in warning for warning in posture["warnings"])


def test_the_confined_default_reports_no_warning():
    """Regression: the old default warned because it was unsafe. It no longer is."""
    posture = security_posture()
    assert posture["input_roots"]["mode"] == "restricted"
    assert not any("confinement is OFF" in warning for warning in posture["warnings"])


def test_the_posture_names_the_default_roots_it_is_enforcing():
    posture = security_posture()
    assert posture["input_roots"]["roots"], "restricted mode reported no roots"
    assert posture["input_roots"]["source"] == "default"


# --------------------------------------------------------------------------- #
#  Explicit roots still work exactly as before                                 #
# --------------------------------------------------------------------------- #


def test_explicit_roots_replace_the_defaults(monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    probe = allowed / "in.png"
    probe.write_bytes(b"x")
    monkeypatch.setenv("FRAMEFORGE_MCP_INPUT_ROOTS", str(allowed))

    _assert_input_path_allowed(str(probe))
    with pytest.raises(ValueError, match="outside the allowed"):
        _assert_input_path_allowed(str(tmp_path / "elsewhere.png"))

    posture = security_posture()
    assert posture["input_roots"]["mode"] == "restricted"
    assert posture["input_roots"]["source"] == "environment"


def test_several_roots_are_separated_by_the_platform_path_separator(monkeypatch, tmp_path):
    import os

    first, second = tmp_path / "a", tmp_path / "b"
    for root in (first, second):
        root.mkdir()
        (root / "in.png").write_bytes(b"x")
    monkeypatch.setenv("FRAMEFORGE_MCP_INPUT_ROOTS", os.pathsep.join([str(first), str(second)]))

    _assert_input_path_allowed(str(first / "in.png"))
    _assert_input_path_allowed(str(second / "in.png"))


def test_traversal_out_of_an_allowed_root_is_refused(monkeypatch, tmp_path):
    """`..` must not walk out of a configured root."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (tmp_path / "secret.png").write_bytes(b"x")
    monkeypatch.setenv("FRAMEFORGE_MCP_INPUT_ROOTS", str(allowed))

    with pytest.raises(ValueError, match="outside the allowed"):
        _assert_input_path_allowed(str(allowed / ".." / "secret.png"))


# --------------------------------------------------------------------------- #
#  Discoverability: an agent can ask before it is refused                      #
# --------------------------------------------------------------------------- #


def test_the_posture_is_reachable_through_discovery():
    from frameforge_mcp.discovery import describe_capabilities

    detail = describe_capabilities("security")
    assert detail["ok"] is True
    assert detail["security_posture"]["input_roots"]["mode"] == "restricted"


def test_the_security_topic_is_advertised_in_the_index():
    from frameforge_mcp.discovery import describe_capabilities

    assert "security" in describe_capabilities()["topics"]


# --------------------------------------------------------------------------- #
#  The refusal is actionable wherever it is raised                             #
# --------------------------------------------------------------------------- #


def test_a_confined_propose_call_carries_the_remediation_hint(monkeypatch, tmp_path):
    """The propose tools build their own envelope, bypassing `_error_envelope`.

    Regression: wiring the hint into the server's failure-hint table alone left
    the propose tools — the ones most likely to hit confinement — returning
    ``ok: false`` with no route forward at all.
    """
    from frameforge_mcp import usecases

    monkeypatch.setenv("FRAMEFORGE_MCP_INPUT_ROOTS", str(tmp_path))
    result = usecases.propose_from_image(image_path="/etc/passwd")

    assert result["ok"] is False
    assert "describe_capabilities" in result["hint"]
    assert "FRAMEFORGE_MCP_INPUT_ROOTS" in result["hint"]


def test_an_unrelated_vision_failure_does_not_claim_a_confinement_problem(monkeypatch):
    """Regression: a blanket hint on every `_vision_error` misdiagnosed missing lanes.

    A caller told to check its input roots when the real problem is an
    uninstalled extra will chase the wrong fix — which is precisely the failure
    mode the hint field exists to prevent.
    """
    from frameforge_mcp import extras, usecases

    monkeypatch.setattr(extras, "lane_available", lambda name: False)
    result = usecases.describe_render("/nonexistent/page.png")

    assert result["ok"] is False
    assert "FRAMEFORGE_MCP_INPUT_ROOTS" not in (result.get("hint") or "")
