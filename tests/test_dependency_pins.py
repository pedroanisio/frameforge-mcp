"""Family dependency pins must be bounded, self-consistent, and actually locked.

The FrameForge packages resolve each other by path in development and by
version once published, which hides pin defects: everything works locally
because the sibling checkout is whatever is on disk, and the declared range is
only exercised by someone installing from an index. An audit across the eight
family repositories found three kinds of defect that a local test run would
never surface —

* a runtime dependency with **no version constraint at all**, which accepts a
  future major;
* an **uncapped** dependency on a pre-1.0 package, where the next minor is
  allowed to break by convention;
* a **lockfile recording a version the sibling no longer has** — the worst kind,
  because `uv sync` reproduces a resolution nobody has tested.

These tests read `pyproject.toml` and `uv.lock` directly. They need no network
and no build, so the invariant is checked on every run rather than at release.

CONVENTION, stated once. A family requirement declares both bounds. The upper
bound caps the next MAJOR (`<2` for a 1.x package, `<1` for a 0.x one). Capping
a 0.x dependency at the next *minor* would be stricter and is what SemVer
suggests for pre-1.0, but the family controls both sides of every one of these
edges, and a cap that has to move on every sibling release stops being read.
What matters is that a 1.0 restructuring cannot arrive silently.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# Read pyproject via the guarded idiom the family enforces: stdlib `tomllib` is
# 3.11+, and requires-python is >=3.10, so an unguarded import crashes the 3.10 leg.
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 has no stdlib tomllib
    import tomli as tomllib  # type: ignore[no-redefine]
import tomllib

ROOT = Path(__file__).resolve().parents[1]
SIBLINGS = ROOT.parent

#: Distributions in this family. `frameforge` (the engine) has no suffix, so it
#: is matched exactly rather than by prefix.
FAMILY = re.compile(r"^(?:frameforge|frameforge-[a-z]+)(?=\[|>|<|=|!|~|;|\s|$)")

#: `name[extra1,extra2] >=1.9,<2` -> ("name", "[extra1,extra2]", ">=1.9,<2")
REQUIREMENT = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9._-]+)\s*(?P<extras>\[[^\]]*\])?\s*(?P<spec>.*)$")


def _pyproject(root: Path = ROOT) -> dict:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))


def _family_requirements(root: Path = ROOT) -> list[tuple[str, str, str]]:
    """Every family requirement as (section, distribution, version spec)."""
    data = _pyproject(root)
    found: list[tuple[str, str, str]] = []

    def scan(section: str, requirements: list) -> None:
        for raw in requirements:
            if not isinstance(raw, str) or not FAMILY.match(raw):
                continue
            match = REQUIREMENT.match(raw)
            assert match, raw
            name = match.group("name")
            # A self-referential extra (`frameforge-example[coach]`) is not a
            # cross-package edge; it cannot drift from a sibling.
            if name == data.get("project", {}).get("name"):
                continue
            found.append((section, name, match.group("spec").strip()))

    scan("project.dependencies", data.get("project", {}).get("dependencies", []))
    for extra, requirements in data.get("project", {}).get(
            "optional-dependencies", {}).items():
        scan(f"project.optional-dependencies.{extra}", requirements)
    for group, requirements in data.get("dependency-groups", {}).items():
        scan(f"dependency-groups.{group}", requirements)
    return found


def _bounds(spec: str) -> tuple[str | None, str | None]:
    lower = re.search(r">=?\s*([0-9][^,\s]*)", spec)
    upper = re.search(r"<=?\s*([0-9][^,\s]*)", spec)
    return (lower.group(1) if lower else None, upper.group(1) if upper else None)


def _requirement_ids() -> list[str]:
    return [f"{section}:{name}" for section, name, _ in _family_requirements()]


# --------------------------------------------------------------------------- #
#  Bounds                                                                      #
# --------------------------------------------------------------------------- #
def test_there_are_family_requirements_to_check():
    """Guards the guard: a regex that silently matches nothing would make every
    test below vacuously green."""
    assert _family_requirements(), "no family requirements found — check FAMILY"


@pytest.mark.parametrize(("section", "name", "spec"), _family_requirements(),
                         ids=_requirement_ids())
def test_every_family_requirement_declares_a_lower_bound(section, name, spec):
    lower, _ = _bounds(spec)
    assert lower is not None, (
        f"{section}: '{name} {spec}'.strip() has no floor — it accepts any "
        f"version, including ones predating the feature it is here for")


@pytest.mark.parametrize(("section", "name", "spec"), _family_requirements(),
                         ids=_requirement_ids())
def test_every_family_requirement_declares_an_upper_bound(section, name, spec):
    _, upper = _bounds(spec)
    assert upper is not None, (
        f"{section}: '{name} {spec}'.strip() has no cap — a future major "
        f"release of {name} would be accepted without review")


@pytest.mark.parametrize(("section", "name", "spec"), _family_requirements(),
                         ids=_requirement_ids())
def test_the_cap_is_the_next_major(section, name, spec):
    """`>=1.2` caps at `<2`; a 0.x floor caps at `<1`. See the module docstring
    for why 0.x is capped at the next major rather than the next minor."""
    lower, upper = _bounds(spec)
    if lower is None or upper is None:
        pytest.skip("covered by the bound tests above")
    expected = "1" if lower.startswith("0.") else f"{int(lower.split('.')[0]) + 1}"
    assert upper.split(".")[0] == expected, (
        f"{section}: '{name} {spec}' caps at {upper}; the convention for a "
        f"floor of {lower} is <{expected}")


# --------------------------------------------------------------------------- #
#  Self-consistency between base requirements and extras                       #
# --------------------------------------------------------------------------- #
def test_no_extra_floors_a_family_package_below_the_base_requirement():
    """An extra that repeats a base dependency must not restate a lower floor.

    Harmless while both are present — the resolver intersects them — but the
    stale one documents a requirement the package does not actually accept, and
    becomes real the moment the base pin is edited. `frameforge` carried
    `frameforge-render>=1.9,<2` in its base requirements and
    `frameforge-render[fonts,metrics]>=1.0,<2` in its `metrics` extra, with a
    comment in the same file explaining that an older renderer "raises
    TypeError on every render call".
    """
    base = {}
    for section, name, spec in _family_requirements():
        if section == "project.dependencies":
            base[name] = _bounds(spec)[0]

    offenders = []
    for section, name, spec in _family_requirements():
        if section == "project.dependencies" or name not in base:
            continue
        floor = _bounds(spec)[0]
        if floor and base[name] and _version_key(floor) < _version_key(base[name]):
            offenders.append(f"{section}: {name}>={floor} is below the base >={base[name]}")
    assert not offenders, "; ".join(offenders)


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


# --------------------------------------------------------------------------- #
#  The lockfile agrees with the checkouts it was resolved from                  #
# --------------------------------------------------------------------------- #
def _locked_family_versions() -> dict[str, str]:
    lock = ROOT / "uv.lock"
    if not lock.is_file():
        return {}
    text = lock.read_text(encoding="utf-8")
    return {name: version for name, version in re.findall(
        r'name = "(frameforge[a-z-]*)"\nversion = "([^"]+)"', text)}


def _sibling_version(distribution: str) -> str | None:
    path = SIBLINGS / distribution / "pyproject.toml"
    if not path.is_file():
        return None
    return tomllib.loads(path.read_text(encoding="utf-8")).get("project", {}).get("version")


def test_the_lockfile_pins_family_versions_that_still_exist():
    """The defect this was written for: `frameforge-vision/uv.lock` recorded
    `frameforge-api` 1.0.0 and `frameforge-render` 1.0.0 while the checkouts
    were 1.3.1 and 1.9.0 — a resolution three contract revisions behind, which
    `uv sync` would faithfully reproduce."""
    stale = []
    for distribution, locked in _locked_family_versions().items():
        actual = _sibling_version(distribution)
        if actual is None:
            continue  # sibling not checked out here; nothing to compare against
        if actual != locked:
            stale.append(f"{distribution}: lock has {locked}, checkout has {actual}")
    assert not stale, (
        "run `uv lock` — " + "; ".join(stale))


def test_every_locked_family_package_is_a_real_sibling_or_absent():
    """A locked family name that matches no checkout and no known distribution
    is a typo or a package that was renamed out from under the lock."""
    unknown = [name for name in _locked_family_versions()
               if not (SIBLINGS / name).exists()]
    assert not unknown, f"locked but no such sibling checkout: {unknown}"


# --------------------------------------------------------------------------- #
#  The declared range admits the version that is actually on disk              #
# --------------------------------------------------------------------------- #
def _admits(spec: str, version: str) -> bool:
    """Whether `version` satisfies every clause of `spec`.

    A deliberately small comparator rather than `packaging`: this gate must run
    in every family repository, and none of them declares `packaging` as a test
    dependency. It understands the three operators the family actually uses.
    """
    target = _version_key(version)
    for clause in (c.strip() for c in spec.split(",") if c.strip()):
        match = re.match(r"(>=|<=|==|>|<|!=)\s*([0-9][^\s]*)", clause)
        if not match:
            continue
        op, bound = match.group(1), _version_key(match.group(2))
        width = max(len(target), len(bound))
        left = target + (0,) * (width - len(target))
        right = bound + (0,) * (width - len(bound))
        if not {">=": left >= right, "<=": left <= right, "==": left == right,
                ">": left > right, "<": left < right, "!=": left != right}[op]:
            return False
    return True


def test_declared_ranges_admit_the_sibling_checkout_versions():
    """A range that excludes the version on disk is a defect path sources hide.

    `uv` resolves an editable path source to the checkout regardless of the
    declared specifier, so a stale cap fails nothing locally and fails every
    install from an index. This caught `frameforge-mcp>=1.0,<2` in the engine
    on the day `frameforge-mcp` released 2.0.0 — a cap written hours earlier,
    already wrong, and invisible to `uv lock --check`.
    """
    excluded = []
    for section, name, spec in _family_requirements():
        actual = _sibling_version(name)
        if actual is None or not spec:
            continue
        if not _admits(spec, actual):
            excluded.append(f"{section}: '{name} {spec}' excludes the checkout at {actual}")
    assert not excluded, "; ".join(excluded)


def test_the_range_comparator_understands_the_operators_in_use():
    """Guards the guard: a comparator that silently admits everything would
    make the test above vacuous."""
    assert _admits(">=1.0,<2", "1.5.0")
    assert not _admits(">=1.0,<2", "2.0.0")
    assert not _admits(">=1.1,<2", "1.0.0")
    assert _admits(">=2.9,<3", "2.11.0"), "2.11 must not compare as 2.1"
    assert _admits(">=0.1,<1", "0.1.0")
    assert not _admits(">=0.1,<1", "1.0.0")


# --------------------------------------------------------------------------- #
#  NOT propagated: the version/CHANGELOG pairing test                          #
# --------------------------------------------------------------------------- #
# `frameforge-sdk` also asserts that the newest CHANGELOG heading equals the
# declared version. It is not copied here because this repository does not
# currently satisfy it, for a reason that predates this suite and cannot be
# fixed by editing a pin: the release it declares has no CHANGELOG section, and
# writing one now would mean inventing notes for work already shipped. Recorded
# rather than silenced.
