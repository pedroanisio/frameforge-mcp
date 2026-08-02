# frameforge-mcp — CHANGELOG

*Version headings mark distribution releases. The document contract this server
speaks is `frameforge_api.HEAD_VERSION`, which moves on its own schedule.*

---

## 2.0.0 — the tool surface declares itself (2026-08-02)

Five things every tool did were true and undeclared. A host could not tell
`list_fonts` from `run_sdk_code`, a caller had no machine-readable account of
what came back, and the safe filesystem posture was the one you had to opt into.

#### Added — MCP tool annotations on all 35 tools (**breaking for nothing; read it anyway**)

Every tool now publishes `readOnlyHint`, `destructiveHint`, `idempotentHint`,
`openWorldHint`, and a human-readable `title`. Hosts gate approval on these, and
this server declared none of them — so `list_fonts` (reads fontconfig) and
`run_sdk_code` (runs untrusted Python in a subprocess `security_posture()`
itself reports as `sandboxed: false`) were indistinguishable in `tools/list`.

The classification is data, in `frameforge_mcp.tool_facts`, not 35 hand-written
decorator argument lists — because a claim scattered across a 2,000-line
composition root cannot be checked. It is checked: `tests/test_tool_surface.py`
asserts every registered tool has an entry, that the live server publishes
exactly those values, and that **no tool claiming `read_only` reaches a
filesystem-writing primitive**, so the declaration cannot rot into a lie.

Notable verdicts, all of them consequences of what the code actually does:

- The whole render family is `destructive`, because a render **resets** its
  session's previous pages — only the last call's artifacts survive. The server
  already warned about this in a failure hint; now the protocol carries it.
- Only `run_sdk_code` / `run_sdk_client` are `openWorld`. Everything else
  renders locally and reaches nothing beyond the machine.
- `write_sdk_client` is not idempotent (`append=true` adds text every call);
  `cleanup_sessions` is (deleting a deleted session is the same end state).

Also served in-band as `describe_capabilities(topic="tools")`, for clients that
do not surface annotations and for agents deciding whether a retry is free.

#### Fixed — a slow render froze the entire server

FastMCP calls a *synchronous* tool function inline on the event loop. Every tool
here was synchronous, so one render holding its 20-second subprocess budget
blocked every other request **and** every notification — including the ones that
would have reported it. Tool bodies now run in a worker thread.

That is also what made progress reporting possible: every tool receives the MCP
`Context` and emits progress plus MCP log records around its work, mirroring the
JSONL audit trail that until now only existed on disk. Reporting is best-effort
and never fatal — a client that cannot receive a notification does not turn a
good render into a failure. Progress is honest about what the server can
observe: start and end, no invented intermediate milestones.

#### Added — a published, enforced result contract

`frameforge_mcp.envelope.ToolEnvelope` states the shape every tool result
satisfies. It is published as each tool's `outputSchema` and **validated by
FastMCP on every call** before the result leaves the server. `ok` is the only
required key (strictly typed — pydantic's lax mode reads `"yes"` as `True`);
tool-specific keys pass through untouched. Readable as
`describe_capabilities(topic="envelope")`.

Writing the contract down immediately found a defect: `list_deprecated_forms`
and `migrate_deprecated_forms` **returned no `ok` key at all**, so a client
branching on it got `undefined` from exactly the two tools the README tells an
agent to call *first*. Both now report `ok`.

#### Changed — the connection preamble is 65% smaller

The `instructions` string had grown to 7,019 characters of SDK tour, sent to
every client on every connection before the agent asked for anything — a fixed
context tax duplicating `get_guide`, and the largest block of text this server
injects verbatim into a model's context. Now 2,425 characters carrying only what
an agent cannot recover on its own: the loop, the rules whose violation is
silent (font substitution, the two removed forms, the typed diagnostics), the
contracts, and where the real reference lives. Nothing was deleted — the SDK
tour is served on demand by `get_guide`, and `tests/test_server_instructions.py`
asserts both the budget and that each moved topic is present in the guide.

#### Added — tests for the tool layer itself

The suite covered use cases, extras, deprecations, and closures — everything
*below* the tools. Registration, argument validation, the error envelope, the
transport budget, and result shaping had never been executed by a test.
`tests/test_tool_dispatch.py` now drives `FastMCP.call_tool`, the same entry
point a host uses.

`tests/test_docs_match_the_server.py` closes the other direction: the tool count
in the README, the version in the migration frontmatter, the documented
environment-variable semantics, and the payloads in `examples/` are all now
asserted against the running server. The README had been claiming "~33
registered tools" while 35 were registered.

160 tests → 243.

### Changed — **BREAKING**: file inputs are confined by default

`FRAMEFORGE_MCP_INPUT_ROOTS` unset used to mean *any readable path is accepted*.
An agent that could be steered — by a poisoned document, a crafted filename, or
an over-eager plan — could ask `propose_from_image` for `~/.ssh/id_rsa` or
`~/.aws/credentials`, and the contents would flow into the model's context using
the user's own filesystem privileges. That is the confused-deputy shape, and the
open posture was the default.

Inputs are now confined to the **session root, working directory, and
repository**. To restore the old behaviour, set `FRAMEFORGE_MCP_INPUT_ROOTS=*`
— openness is now something a deployment asks for, visibly, and
`security_posture()` warns while it is on. Named roots work exactly as before.

Applies to the propose tools, the measure/CV inputs, and `font_closure` paths.
See MIGRATION.md. The refusal carries a remediation hint through *both* envelope
builders — the propose tools construct their own, and a hint wired into only one
of the two left the likeliest new failure with no route forward.

### Fixed — optional extras that installed nothing usable

`frameforge-mcp[vision]` declared the `frameforge-vision` distribution but not
its `cv` extra. Every import in that package is lazy, so the extra resolved,
installed clean, and then answered every CV call with
`No module named 'cv2'` — `detect_regions`, `vectorize_image`,
`measure_image`'s detectors, `propose_from_image`, `workspace`, all of it. A
full `uv sync --all-extras` did not fix it, because the under-declaration was
in the declaration itself. Three siblings had the same shape:

- `[vlm]` pinned torch/transformers but never pulled `frameforge-vision`, whose
  `vlm` module `describe_render` imports — so the tool raised `ImportError` out
  of the server instead of returning an install hint.
- `[pdf]` pulled PyMuPDF but not `frameforge-vision`, which is what actually
  opens the PDF and runs the detectors over the rasterised page.
- PDF **output** (`to='pdf'`, and the advertised
  `frameforge://session/<id>/document.pdf` resource) needs `pypdf`, which **no
  extra declared at all**. The lane could not be installed by any command.

Each extra now names the distribution *and the extra of it* that carries the
backend its tools import: `vision`/`pdf` → `frameforge-vision[cv]`, `vlm` →
`frameforge-vision[vlm]`, plus a new `pdfout` extra for `pypdf`.

Every install hint was wrong in the same direction. This distribution ships
**extras**; the hints, inherited from the monorepo it was extracted from, told
callers to run `uv sync --group vision` (and `--group pdfout`, `--group mcp`) —
commands that error, because no such group exists here. A caller who followed
the hint got a second error and reasonably concluded the tool was broken rather
than uninstalled.

Same defect, one layer down: the `vlm` lane probed torch, transformers and
Pillow — every one of which imports fine without `torchvision`. transformers 5.x
split image processors into `pil` and `torchvision` backends, and BOTH Idefics3
classes (SmolVLM-256M, the default model) require torchvision, so the lane
reported itself available and `describe_render` then died inside
`AutoProcessor.from_pretrained` with a `ValueError` the caller could not act on.
The lane now probes `torchvision`, so an environment without it gets `ok: false`
with the install command instead. The declaration was fixed at its source in the
same pass: `frameforge-vision[vlm]` carries `torchvision>=0.17`, and that
package's own `vlm.available()` was taught the same lesson (it now answers
*usable*, not *importable*, via `missing_backends()` / `install_hint()`), so the
gate cannot lie to any other consumer either. `pip install
'frameforge-mcp[vlm]'` now produces a `describe_render` that answers.

### Added

- `frameforge_mcp.extras` — one table of the optional lanes: what each extra is
  for, the exact modules its code imports, the tools it gates, and the commands
  that install it. Every failure hint is now generated from that table, so the
  command a tool prints is the command that installs it. Presence is probed with
  `importlib.util.find_spec`, so asking whether the VLM lane exists never pays
  torch's import cost.
- `describe_capabilities(topic="backends")` — which lanes the running
  interpreter actually has, which modules are missing from the rest, which tools
  each gates, and the fix. Probed live on every call (same discipline as
  `security_posture`), so an install performed while the server runs is visible
  to the next call. The compact capability index carries the same availability
  map under `optional_backends`.
- `tests/test_optional_extras.py` — the drift guard. Pins the lane table against
  `pyproject.toml` in both directions, asserts the *installed* metadata (not just
  the source declaration), fails on any source string naming a dependency group
  this distribution does not declare, and requires every probe module to be
  reachable from something the project declares — which is what catches the
  `pypdf` class of gap, where the backend had no installer at all.

### Changed

- `describe_render` checks the lane before importing, so a torch-only
  environment gets an `ok: false` envelope with the install command instead of
  an `ImportError` — or, with torch present but torchvision absent, instead of a
  `ValueError` raised from inside transformers.
- `tests/test_deprecations.py` asserts `pydantic.ValidationError` with the
  rejecting message rather than a blind `Exception` (which would also pass if
  the fixture stopped loading), and imports PyYAML outright: it is a base
  dependency, so `importorskip` was hiding a broken install behind a skip.
  `make check`'s lint leg is green again.

Upgrading: no tool argument, tool name, or result field changed — but the
*contents* of `[vision]`, `[vlm]`, and `[pdf]` did, so an existing environment
must be re-installed to pick up the backends
(`uv sync --extra vision`, or `pip install --upgrade 'frameforge-mcp[vision]'`).
See [MIGRATION.md](MIGRATION.md) § *How to repair an optional lane installed
before 2026-08-01*.

### Guide — the SDK's v1.1 graphics surface

The capability guide is where an agent learns which SDK calls exist, so it is
updated in lockstep with `frameforge-sdk` v1.1:

- **Viewing pipeline.** `ViewingPipeline` is documented as the SDK's ONE
  pipeline, with its stages named (`clip_polyline`, `clip_polygon`,
  `project_polygon`, `depth_key`, `is_back_face`, `fit`) and the `pipeline=`
  argument to `Scene3D.render`/`.wireframe`. Notes that `project()` now CLIPS
  segments crossing the near plane, and that `mode="points"` is the legacy
  drop-the-vertex behaviour.
- **Shading.** All six `shading=` modes, with the specific claim that `gouraud`
  is the only one that interpolates — and that the pre-v1.1 `gouraud` algorithm
  is now `smooth`.
- **Depth ordering.** `depth_sort="average" | "newell" | "none"`, including why
  `average` cannot order penetrating or cyclically overlapping faces.
- **Hidden-line removal.** `Scene3D.wireframe(hidden=...)` and
  `multiview(..., wireframe=True)`.
- **Rational curves.** Concrete names for `frameforge_sdk.curves`.
- **Spatial acceleration.** `Quadtree` and `bounds_of` alongside `AABBTree`, and
  where the broad phase is wired in.

### Added

- `tests/test_guide_matches_the_sdk.py` — a drift guard. Every SDK name, stage,
  keyword and mode the guide promises is asserted to exist and to work, in both
  directions (the guide must not name a missing export; the list must not rot
  into things the guide no longer mentions). It also checks the two quantitative
  claims the guide makes: that `gouraud` is the only interpolating mode, and
  that a rational quadratic arc is exact where the kappa cubic carries ~2.7e-4
  radial error. A guide that lies to an agent is worse than a missing feature.

### Added

- Added `font_closure` and `font_generics` to all three render tools and
  `fit_text`. Paths obey `FRAMEFORGE_MCP_INPUT_ROOTS`; relative render paths
  resolve from the document/client base directory.
- Validation, SVG, HTML, diagnostics, and author-time fitting share one strict
  closure provider. Results report `metrics_mode`, closure SHA-256, path,
  generic aliases, and strictness.
- The default install now depends on `frameforge-sdk[metrics]`, so the advertised
  capability does not require an undisclosed extra.
- Added a migration guide and complete JSON tool-call example.

### Changed

- Renderer imports follow the standalone `frameforge_render` boundary after
  the monorepo engine cutover.

## 1.0.0 — extraction from the monorepo (2026-08-01)

The agent-facing surface of FrameForge as its own distribution. `src/frameforge/{mcp,coach,live}`
are deleted from the monorepo, which now depends on this package in its **dev**
group only — this package depends on the engine, so the edge back must never be
a runtime dependency.

- **Two packages, one distribution.** `frameforge_mcp` (the server, ~33 tools,
  and `live` nested inside it) and `frameforge_coach`.
  - `live` is nested because it *is* an MCP surface: it imports the server
    directly, and one test and zero examples reference it.
  - `coach` is not nested. It never imports the MCP — its docstring states its
    boundary as "imports only `frameforge_sdk` + stdlib" — and 6 tests plus 10
    examples reach it directly.
- **`frameforge_vision` is a dependency, not a package here.** It already
  exists as its own 1.0.0 distribution, with the SDK import made lazy so that
  measuring an image needs no authoring package. Shipping a second copy would
  have given one module name two homes.
- **Fixed: the repo root was computed by walking up from the package file.**
  `paths.get_default_repo_root()` returned `parents[3]`, correct while the
  server lived at `<root>/src/frameforge/mcp/` and silently wrong the moment it
  became a distribution — it resolved to the directory *containing* the
  checkouts, and live discovery simply found no sources. It now resolves
  through the installed engine, with a `FRAMEFORGE_REPO` override.
- **Fixed: the live-discovery freshness token only hashed the engine.** A
  long-running server would not notice a new SDK export or a changed tool in
  this package — the staleness issue #78 closed, reopened by the split.
  `_source_roots()` now spans the engine, the SDK, this server and the coach,
  preferring a vendored `<repo>/src/<pkg>` when one exists.
