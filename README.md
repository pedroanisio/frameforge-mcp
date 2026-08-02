# frameforge-mcp

The **FrameForge MCP server**: the agent-facing surface of the FrameForge
family. An AI agent authors a document with the SDK, this server renders it,
and the agent verifies against the pixels that came back.

```bash
pip install frameforge-mcp
frameforge-mcp                      # stdio MCP server
frameforge-live                     # local web UI over the same loop
```

Unlike [`frameforge-api`](https://github.com/pedroanisio/frameforge-api) (the
contract) and [`frameforge-sdk`](https://github.com/pedroanisio/frameforge-sdk)
(authoring), this package is **not a leaf and does not pretend to be one**. It
sits at the top of the stack and depends on the engine, because verification
needs something that can actually render.

## Two packages, one distribution

| package | what it is | imports MCP? |
|---|---|---|
| `frameforge_mcp` | the server, its 35 registered tools, and (nested) `live`, the local feedback-session web UI | — |
| `frameforge_coach` | the Vector Construction Coach — style-as-grammar, layer-order discipline, the silhouette gate | no |

The raster→vector lane is **not** here: `frameforge_vision` is its own
distribution, usable without a server or an authoring SDK. This package depends
on it (`pip install 'frameforge-mcp[vision]'`) rather than shipping a second
copy of the same module name.

`live` is nested inside `frameforge_mcp` because it genuinely is one of the
server's surfaces: it imports `frameforge_mcp.server` directly and exists to
put a browser in front of the same validate/render loop.

`coach` is deliberately *not* nested. It does not import the MCP, and 6 tests
plus 10 examples reach it directly — routing them through a server package
would assert a dependency that does not exist.

## What it does

- **Author → render**: run SDK code or FrameForge YAML, get validation issues
  plus a PNG back in one call.
- **Verification signals**: every render result carries the engine's typed
  diagnostics — text fit, layout overflow, ink collisions, legibility (type
  below the legible floor, WCAG contrast), paint intent, design-token census.
  A render that succeeded but produced something unreadable says so.
- **Portable font evidence**: `run_sdk_code`, `run_sdk_client`,
  `render_frameforge_yaml`, and `fit_text` accept a `.fp` `font_closure` plus
  optional `font_generics`. Validation and rendering share the same strict
  provider and report `metrics_mode: closure` with the closure SHA-256.
- **Visual QA**: real NCC/RMSE/MAE metrics between a reference and a candidate.
- **Raster → vector**: a coordinate-aware reconstruction workspace — measure,
  mark, overlay, fit primitives, vectorize, score.
- **Image → draft**: propose documents from images, PDFs, or SVGs. Every
  proposal is unverified CV/VLM output and is round-tripped through a render
  before it is shown.
- **Deprecated forms**: `list_deprecated_forms` returns the contract's
  registry — what each retired spelling became, and whether it still validates —
  and `migrate_deprecated_forms` rewrites them, returning the migrated YAML with
  `apply: true`.

  These run *before* a render, and that ordering is the point. Two of the
  deprecated forms (the pre-P3 inline `stroke` bundle, the pre-P4 `size` object)
  are **rejected** by the contract, so a document carrying one can never reach
  `render_frameforge_yaml` at all — an agent holding it gets "does not validate"
  and no route forward. The rewrite is mechanical, so this is that route.
  Neither tool renders, and neither touches a session; the migration does not
  mutate its input and is idempotent.

## What every tool declares

A host has to decide whether a call needs approval, and an agent has to decide
whether a failed call is safe to retry. Both questions are answered in the
protocol rather than guessed from the tool name:

| Hint | Means | Example |
|---|---|---|
| `readOnlyHint` | does not modify its environment | `list_fonts`, `describe_capabilities`, `read_sdk_client` |
| `destructiveHint` | may overwrite or remove existing state | every render tool — a render **resets** its session's previous pages |
| `idempotentHint` | a repeat call changes nothing further | `cleanup_sessions` yes; `write_sdk_client` no (`append=true`) |
| `openWorldHint` | may reach beyond this machine | only `run_sdk_code` / `run_sdk_client`, which execute untrusted Python |

The table lives in `frameforge_mcp.tool_facts` and is checked against the code:
a tool claiming `readOnlyHint` whose use case touches a filesystem-writing
primitive fails the test suite, so the declaration cannot rot into a lie.

Clients that do not surface annotations can read the same data in-band:

```json
{"tool": "describe_capabilities", "arguments": {"topic": "tools"}}
```

See [`examples/tool_declarations_call.json`](examples/tool_declarations_call.json).

## The result contract

Every tool but `get_guide` (which returns prose) resolves to one shape, published
as that tool's `outputSchema` and validated by the server before the result is
sent:

```jsonc
{
  "ok": true,          // the only guaranteed key — branch on it first
  "error": null,       // present when ok is false
  "error_type": null,  // the exception class behind the failure
  "hint": null,        // the actionable next step
  "renders": [],       // rendered pages: page, uri, mimeType, sha256
  "resources": []      // MCP resource links to what this call wrote
  // ...plus whatever this tool actually returns
}
```

Expected failures — an uninstalled lane, a bad path, a document that will not
validate — are `ok: false` envelopes with a `hint`, never exceptions. Read the
schema with `describe_capabilities(topic="envelope")`.

## Progress and logging

Long calls report. Every tool receives the MCP `Context` and emits progress
notifications plus MCP log records around its work, so a render bounded by a
20-second subprocess budget shows as a live operation instead of a stall. The
same events are written to the structured JSONL audit log on disk.

Tool bodies run in a worker thread. Before 2.0 they ran inline on the event
loop, so one slow render blocked every other request — and every notification
that would have reported it.

## Where tools may read from

File inputs (the `propose_*` tools, the measure/CV image arguments, and
`font_closure` paths) are confined to the **session root, working directory, and
repository**. The server holds your filesystem privileges; without confinement a
steered agent could ask it for `~/.ssh/id_rsa` and get the contents into a model's
context.

```bash
export FRAMEFORGE_MCP_INPUT_ROOTS=/mnt/assets:/workspace/fonts   # name your roots
export FRAMEFORGE_MCP_INPUT_ROOTS='*'                            # accept any readable path
```

`describe_capabilities(topic="security")` reports the roots in force, live from
the environment, and warns for as long as `*` is set. This default changed in
2.0 — see [MIGRATION.md](MIGRATION.md).

## PALS's Law

Every tool in this server treats model output as untrusted. Proposals are
labelled unverified, estimate-mode measurements name themselves as estimates,
and a signal the server cannot resolve is reported as unresolved rather than
scored as a pass. That is the point of the render loop: an agent that cannot
see its own output cannot correct it.

The same standard applies to the server's own reporting. Progress covers what it
can observe — that a call started and how it ended — and does not invent
intermediate milestones it cannot see.

## Optional extras

```bash
pip install 'frameforge-mcp[vision]'   # the frameforge-vision lane: measure, vectorize, propose
pip install 'frameforge-mcp[vlm]'      # local CPU vision-language describer (incl. torchvision)
pip install 'frameforge-mcp[pdf]'      # PDF input for propose_from_document
pip install 'frameforge-mcp[pdfout]'   # PDF output: to='pdf' + the document.pdf resource
pip install 'frameforge-mcp[browser]'  # headless Chromium raster
```

In a checkout the same lanes are `uv sync --extra <name>` (and `--all-extras` for
all of them). These are **extras, not dependency groups** — `--group vision`
is not a thing here.

Each extra installs the backend its tools actually import, not just the
distribution that wraps it: `[vision]` pulls `frameforge-vision[cv]`, so OpenCV
and Pillow come with it. An extra that resolved but left the lane dead was
[the bug fixed on 2026-08-01](CHANGELOG.md); `tests/test_optional_extras.py`
now pins every extra against the modules its lane imports.

Two things no resolver can do for you: `[browser]` needs
`playwright install chromium` afterwards, and `vectorize_image(method="trace")`
needs the `potrace` binary from your OS package manager.

**Ask the server which lanes it has.** `describe_capabilities(topic="backends")`
reports, live from the running interpreter, which extras are installed, which
modules are missing from the rest, the tools each lane gates, and the exact
install command. The compact capability index carries the same map under
`optional_backends`. Any tool whose lane is absent returns `ok: false` with that
command in `hint` — it is uninstalled, not broken.

The base install includes `frameforge-sdk[metrics]` and renders through
CairoSVG, so closure metrics and browser-free visual verification work without
another extra.

## Provenance

Since the 2026-08-01 cutover this repository is the MCP source of truth. The
former extraction script is historical; the monorepo depends on this package
in its dev group and no longer owns a second MCP implementation.

See [MIGRATION.md](MIGRATION.md) and
[`examples/font_closure_tool_call.json`](examples/font_closure_tool_call.json)
for the portable closure call shape,
[`examples/optional_backends_tool_call.json`](examples/optional_backends_tool_call.json)
for the optional-lane probe and the failure envelope a missing lane returns, and
[`examples/tool_declarations_call.json`](examples/tool_declarations_call.json)
for the per-tool read-only/destructive/idempotent/open-world declarations and
how to act on them.

The same reports are importable, for callers that drive the loop in-process:

```python
from frameforge_mcp import lane_available, install_hint, optional_backends

if not lane_available("vision"):
    raise SystemExit(install_hint("vision"))
optional_backends()["lanes"]["vision"]["tools"]   # what the lane unlocks
```

```python
from frameforge_mcp import TOOL_FACTS, ToolEnvelope, security_posture

TOOL_FACTS["run_sdk_code"].destructive        # True — and .writes says why
TOOL_FACTS["list_fonts"].read_only            # True — free to call, and to repeat
ToolEnvelope.model_validate(result)           # the contract every tool result satisfies
security_posture()["input_roots"]["roots"]    # which paths a tool may read
```

## Licence

MIT — see [LICENSE](LICENSE).
