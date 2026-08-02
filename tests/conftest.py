"""Suite-wide configuration.

The one thing that needs saying here is the input-root declaration below. It is
not a workaround: it is the same configuration step a real deployment now has to
perform, made explicit in one place instead of scattered through the tests that
happen to feed a fixture from a temporary directory.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _declare_test_input_roots(tmp_path_factory):
    """Let the suite read the fixtures it writes under pytest's temp directory.

    Since 2.0 the propose/measure/font-closure tools are confined to the input
    roots (``security.default_input_roots``: the session root, the working
    directory, and the repository) unless ``FRAMEFORGE_MCP_INPUT_ROOTS`` says
    otherwise. Test fixtures live under pytest's ``tmp_path`` base, which is
    none of those — so the suite declares it, exactly as a deployment declares
    the directory its source images live in.

    Kept deliberately narrow: the temp base plus the repository, never ``*``.
    A suite that opted out of confinement entirely could not notice if the
    confinement broke, and ``tests/test_input_confinement.py`` overrides this
    with its own fixture so the default posture is still exercised for real.
    """
    roots = [str(tmp_path_factory.getbasetemp()), os.getcwd()]
    previous = os.environ.get("FRAMEFORGE_MCP_INPUT_ROOTS")
    os.environ["FRAMEFORGE_MCP_INPUT_ROOTS"] = os.pathsep.join(roots)
    yield
    if previous is None:
        os.environ.pop("FRAMEFORGE_MCP_INPUT_ROOTS", None)
    else:
        os.environ["FRAMEFORGE_MCP_INPUT_ROOTS"] = previous
