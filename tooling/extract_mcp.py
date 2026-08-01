#!/usr/bin/env python3
"""extract_mcp.py — re-derive the MCP distribution from the monorepo.

Same discipline as `frameforge-sdk/tooling/extract_sdk.py`: the package is a
*function of upstream*, not a fork that happened to start there, so re-syncing
is one command and `--check` fails when the committed tree has drifted.

WHAT MOVES, AND WHY IT IS SHAPED THIS WAY
-----------------------------------------
Two packages, one distribution:

    src/frameforge/mcp/     -> frameforge_mcp/          the server + tool layer
    src/frameforge/live/    -> frameforge_mcp/live/     NESTED (see below)
    src/frameforge/coach/   -> frameforge_coach/        construction coach

`live` is nested inside the server package because it genuinely is one of its
surfaces: it imports `frameforge.mcp.server` directly, its own docstring calls
it "a local web UI for FrameForge MCP live sessions ... deliberately reuses the
MCP feedback functions instead of creating a second render path", and exactly
one test and zero examples reference it.

`coach` is deliberately NOT nested. It does not import the MCP at all — its
module docstring states its boundary as "imports only `frameforge_sdk` +
stdlib" — and it has direct consumers (6 tests, 10 examples) that would be
forced through a server package to reach it. Nesting it would assert a
dependency that does not exist.

`vision` is NOT here at all: it is its own distribution, `frameforge-vision`,
already published with the SDK import made lazy so that measuring an image
needs no authoring package. This distribution depends on it rather than
shipping a second copy of the same module name.

`library` and `patterns` stay in the engine: the MCP is their only importer
today, but they are authoring *content* (a 375-pattern catalogue, seven themes,
symbol packs), not agent infrastructure. They belong with the SDK whenever
someone moves them, not here.

Usage:
    python tooling/extract_mcp.py [--repo PATH] [--check]
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DEST = HERE / "src"
DEFAULT_REPO = Path(os.environ.get("FRAMEFORGE_REPO", HERE.parent / "frameforge"))

#: source package -> destination package path within `src/`
LAYOUT = {
    "mcp": "frameforge_mcp",
    "live": "frameforge_mcp/live",
    "coach": "frameforge_coach",
}

#: Dotted-module rewrites, longest first so `frameforge.vision.x` is rewritten
#: before `frameforge.vision`. Order matters: dict insertion order is honoured.
REWRITES = (
    ("frameforge.mcp", "frameforge_mcp"),
    ("frameforge.live", "frameforge_mcp.live"),
    ("frameforge.vision", "frameforge_vision"),
    ("frameforge.coach", "frameforge_coach"),
)


def rewrite(text: str) -> str:
    """Repoint intra-distribution module references; leave engine/SDK alone.

    `frameforge.conform`, `frameforge.model`, `frameforge_render.*` and
    `frameforge_sdk.*` are dependencies of this distribution and keep their
    names — they resolve through the installed engine and SDK.
    """
    for old, new in REWRITES:
        # word-boundary on both sides so `frameforge.mcp_extra` is untouched
        text = re.sub(rf"\b{re.escape(old)}\b", new, text)
    return text


def build(repo: Path) -> dict[str, str]:
    """The extracted tree as {path relative to src/: content}."""
    src = repo / "src" / "frameforge"
    if not src.is_dir():
        raise SystemExit(f"no frameforge package at {src} — pass --repo")
    out: dict[str, str] = {}
    for pkg, dest in LAYOUT.items():
        base = src / pkg
        if not base.is_dir():
            raise SystemExit(
                f"{base} is missing — upstream moved it; update LAYOUT deliberately")
        for path in sorted(base.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            rel = f"{dest}/{path.relative_to(base).as_posix()}"
            if path.suffix == ".py":
                out[rel] = rewrite(path.read_text(encoding="utf-8"))
            elif path.suffix in (".md", ".json", ".txt", ".typed", ""):
                # READMEs and py.typed ride along; prose gets the same rewrite
                # so it never names a module path the reader cannot import.
                try:
                    out[rel] = rewrite(path.read_text(encoding="utf-8"))
                except UnicodeDecodeError:
                    continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    ap.add_argument("--check", action="store_true",
                    help="write nothing; fail if the committed tree has drifted")
    args = ap.parse_args()

    tree = build(args.repo)

    if args.check:
        drift = []
        for rel, want in tree.items():
            have_path = DEST / rel
            have = have_path.read_text(encoding="utf-8") if have_path.is_file() else ""
            if have != want:
                drift.append(rel)
                if have:
                    diff = list(difflib.unified_diff(
                        have.splitlines(), want.splitlines(),
                        f"committed/{rel}", f"extracted/{rel}", lineterm="", n=1))
                    print("\n".join(diff[:12]))
        extra = [str(p.relative_to(DEST)) for p in DEST.rglob("*.py")
                 if str(p.relative_to(DEST)) not in tree]
        if drift or extra:
            print(f"\nDRIFT: {len(drift)} differ, {len(extra)} unexpected: "
                  f"{(drift + extra)[:6]}")
            return 1
        print(f"in sync with {args.repo} — {len(tree)} files")
        return 0

    for pkg in set(LAYOUT.values()):
        top = DEST / pkg.split("/")[0]
        if top.exists():
            shutil.rmtree(top)
    for rel, text in tree.items():
        target = DEST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    by_pkg: dict[str, int] = {}
    for rel in tree:
        by_pkg[rel.split("/")[0]] = by_pkg.get(rel.split("/")[0], 0) + 1
    print(f"extracted {len(tree)} files from {args.repo}")
    for pkg, n in sorted(by_pkg.items()):
        print(f"  {pkg:20} {n} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
