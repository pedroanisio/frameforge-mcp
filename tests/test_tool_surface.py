"""Every registered tool declares what it does to the caller's environment.

The gap this file pins: all 35 tools were registered with a bare
``@server.tool()``. From a host's point of view ``list_fonts`` (which reads
fontconfig) and ``run_sdk_code`` (which executes arbitrary Python in an
explicitly un-sandboxed subprocess) were indistinguishable — the protocol
carries ``readOnlyHint`` / ``destructiveHint`` / ``idempotentHint`` /
``openWorldHint`` precisely so a client can gate approval on that difference,
and this server declared none of them.

Three surfaces are asserted together, because a declaration that drifts from
the code is worse than no declaration — it tells the host a destructive tool is
safe:

* the REGISTRY (:mod:`frameforge_mcp.tool_facts`) — one table, the source of truth;
* the LIVE SERVER — what FastMCP actually publishes in ``tools/list``;
* the ENFORCING CODE — a tool claiming ``readOnlyHint`` whose use case calls a
  filesystem-writing primitive fails here, so the claim cannot rot.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from frameforge_mcp import tool_facts as tool_annotations
from frameforge_mcp.server import create_server

REPO = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("surface-sessions")
    return create_server(session_root=root, structured_log_path=root / "log.jsonl")


@pytest.fixture(scope="module")
def registered(server):
    """name -> the live FastMCP Tool object."""
    return {tool.name: tool for tool in server._tool_manager.list_tools()}


# --------------------------------------------------------------------------- #
#  The registry covers the surface exactly                                     #
# --------------------------------------------------------------------------- #


def test_every_registered_tool_has_a_facts_entry(registered):
    missing = sorted(set(registered) - set(tool_annotations.TOOL_FACTS))
    assert not missing, f"tools registered with no annotation entry: {missing}"


def test_every_facts_entry_names_a_registered_tool(registered):
    """A stale entry is a lie the registry tells about a tool that is gone."""
    orphans = sorted(set(tool_annotations.TOOL_FACTS) - set(registered))
    assert not orphans, f"annotation entries for tools that do not exist: {orphans}"


def test_the_server_still_publishes_the_whole_documented_surface(registered):
    """Regression guard: the annotation work must not drop or rename a tool."""
    assert len(registered) == 35, sorted(registered)


def test_no_package_export_shadows_a_submodule():
    """Regression: `from frameforge_mcp import X` must not hand back a function.

    Bitten twice while building this surface. ``from __future__ import
    annotations`` already binds the name ``annotations`` in the package
    namespace, and re-exporting the ``tool_facts`` *function* from
    ``__init__`` shadowed the ``tool_facts`` *module* — so an importer asking
    for the module silently received a callable and failed far from the cause.
    """
    import pkgutil

    import frameforge_mcp

    submodules = {name for _, name, _ in pkgutil.iter_modules(frameforge_mcp.__path__)}
    shadowed = sorted(
        name
        for name in submodules
        if not inspect.ismodule(getattr(frameforge_mcp, name, None))
        and getattr(frameforge_mcp, name, None) is not None
    )
    assert not shadowed, f"package exports shadow these submodules: {shadowed}"


# --------------------------------------------------------------------------- #
#  The live server publishes them                                              #
# --------------------------------------------------------------------------- #


def test_every_tool_publishes_annotations(registered):
    bare = sorted(name for name, tool in registered.items() if tool.annotations is None)
    assert not bare, f"tools published with no ToolAnnotations: {bare}"


def test_every_tool_publishes_a_human_readable_title(registered):
    untitled = sorted(name for name, tool in registered.items() if not tool.title)
    assert not untitled, f"tools published with no title: {untitled}"


def test_published_annotations_match_the_registry(registered):
    for name, tool in registered.items():
        facts = tool_annotations.TOOL_FACTS[name]
        assert tool.annotations.readOnlyHint is facts.read_only, name
        assert tool.annotations.destructiveHint is facts.destructive, name
        assert tool.annotations.idempotentHint is facts.idempotent, name
        assert tool.annotations.openWorldHint is facts.open_world, name
        assert tool.title == facts.title, name


def test_every_tool_still_publishes_a_description(registered):
    """Annotations are additive — the docstring stays the model-facing contract."""
    undocumented = sorted(
        name for name, tool in registered.items() if not (tool.description or "").strip()
    )
    assert not undocumented, f"tools published with no description: {undocumented}"


# --------------------------------------------------------------------------- #
#  Internal consistency of the hints                                           #
# --------------------------------------------------------------------------- #


def test_a_read_only_tool_is_never_destructive():
    """``destructiveHint``/``idempotentHint`` are only meaningful when not read-only."""
    for name, facts in tool_annotations.TOOL_FACTS.items():
        if facts.read_only:
            assert facts.destructive is False, f"{name} claims read-only AND destructive"


def test_a_read_only_tool_is_idempotent_by_construction():
    for name, facts in tool_annotations.TOOL_FACTS.items():
        if facts.read_only:
            assert facts.idempotent is True, f"{name} is read-only but not idempotent"


def test_every_tool_declares_what_it_writes():
    """The registry records the *reason* for each classification, not just the verdict."""
    for name, facts in tool_annotations.TOOL_FACTS.items():
        if facts.read_only:
            assert facts.writes == (), f"{name} is read-only but claims writes {facts.writes}"
        else:
            assert facts.writes, f"{name} is not read-only but names nothing it writes"


# --------------------------------------------------------------------------- #
#  The classification matches the code that enforces it                        #
# --------------------------------------------------------------------------- #

#: Primitives that mutate the filesystem. A use case reachable from a tool that
#: claims ``readOnlyHint`` must call none of them.
WRITE_PRIMITIVES = re.compile(
    r"\b(write_text|write_bytes|mkdir|unlink|rmtree|copytree|copyfile|makedirs)\b"
    r"|_reset_session_(outputs|inputs|renders)|_prepare_session|_run_source"
)

#: tool name -> the use-case callable that does its work.
USE_CASE_MODULES = ("usecases", "clients", "sessions", "discovery")


def _use_case_source(name: str) -> str | None:
    """Source of the use case backing *name*, searched across the use-case modules."""
    import importlib

    for module_name in USE_CASE_MODULES:
        module = importlib.import_module(f"frameforge_mcp.{module_name}")
        fn = getattr(module, name, None)
        if fn is not None and inspect.isfunction(fn):
            return inspect.getsource(fn)
    return None


@pytest.mark.parametrize(
    "name",
    sorted(n for n, f in tool_annotations.TOOL_FACTS.items() if f.read_only),
)
def test_a_read_only_tool_calls_no_write_primitive(name):
    """The drift guard: a read-only claim is checked against the enforcing code.

    If someone later teaches ``list_fonts`` to cache to disk, this fails rather
    than letting the server keep telling hosts the call is free of side effects.
    """
    source = _use_case_source(name)
    if source is None:
        pytest.skip(f"{name} has no single-function use case to inspect")
    found = sorted(set(match.group(0) for match in WRITE_PRIMITIVES.finditer(source)))
    assert not found, f"{name} claims readOnlyHint but calls {found}"


# --------------------------------------------------------------------------- #
#  The classifications that matter most, named explicitly                      #
# --------------------------------------------------------------------------- #


def test_arbitrary_code_execution_is_destructive_and_open_world():
    """`run_sdk_code`/`run_sdk_client` run untrusted Python in an un-sandboxed subprocess.

    ``security_posture()`` reports ``sandboxed: false`` for that subprocess, so
    the tool can do anything the server process can — including reaching the
    network. Both hints must say so.
    """
    for name in ("run_sdk_code", "run_sdk_client"):
        facts = tool_annotations.TOOL_FACTS[name]
        assert facts.read_only is False, name
        assert facts.destructive is True, name
        assert facts.idempotent is False, name
        assert facts.open_world is True, name


def test_session_deletion_is_destructive_but_idempotent():
    facts = tool_annotations.TOOL_FACTS["cleanup_sessions"]
    assert facts.read_only is False
    assert facts.destructive is True
    assert facts.idempotent is True


def test_writing_a_client_file_is_destructive_and_not_idempotent():
    """`append=True` makes a repeat call add more text — it is not idempotent."""
    facts = tool_annotations.TOOL_FACTS["write_sdk_client"]
    assert facts.destructive is True
    assert facts.idempotent is False


def test_the_migration_tools_are_read_only():
    """README: 'Neither tool renders, and neither touches a session.'"""
    for name in ("list_deprecated_forms", "migrate_deprecated_forms"):
        assert tool_annotations.TOOL_FACTS[name].read_only is True, name


def test_the_render_family_is_destructive_because_it_resets_the_session():
    """A render resets `page-*.svg` / `p*.png`, so only the LAST call's artifacts remain.

    The server's own failure hint says exactly this; a host that reads
    ``destructiveHint: false`` would be told the previous render survives.
    """
    for name in ("render_frameforge_yaml", "compare_images", "measure_image", "workspace"):
        assert tool_annotations.TOOL_FACTS[name].destructive is True, name


def test_nothing_but_code_execution_claims_an_open_world():
    """FrameForge renders locally — no tool but arbitrary code execution reaches out."""
    open_world = sorted(n for n, f in tool_annotations.TOOL_FACTS.items() if f.open_world)
    assert open_world == ["run_sdk_client", "run_sdk_code"]


def test_read_only_tools_cover_the_discovery_surface():
    """Discovery must be free to call — that is what makes it the cheap first step."""
    for name in (
        "describe_capabilities",
        "get_guide",
        "list_fonts",
        "list_sessions",
        "list_sdk_clients",
        "read_sdk_client",
        "get_session_resource",
        "fit_text",
        "diff_renders",
    ):
        assert tool_annotations.TOOL_FACTS[name].read_only is True, name
