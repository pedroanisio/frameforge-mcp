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
| `frameforge_mcp` | the server, its ~33 registered tools, and (nested) `live`, the local feedback-session web UI | — |
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

## PALS's Law

Every tool in this server treats model output as untrusted. Proposals are
labelled unverified, estimate-mode measurements name themselves as estimates,
and a signal the server cannot resolve is reported as unresolved rather than
scored as a pass. That is the point of the render loop: an agent that cannot
see its own output cannot correct it.

## Optional extras

```bash
pip install 'frameforge-mcp[vision]'   # the frameforge-vision lane: measure, vectorize, propose
pip install 'frameforge-mcp[vlm]'      # local CPU vision-language describer
pip install 'frameforge-mcp[pdf]'      # PDF input for propose_from_document
pip install 'frameforge-mcp[browser]'  # headless Chromium raster
```

The base install includes `frameforge-sdk[metrics]` and renders through
CairoSVG, so closure metrics and browser-free visual verification work without
another extra.

## Provenance

Since the 2026-08-01 cutover this repository is the MCP source of truth. The
former extraction script is historical; the monorepo depends on this package
in its dev group and no longer owns a second MCP implementation.

See [MIGRATION.md](MIGRATION.md) and
[`examples/font_closure_tool_call.json`](examples/font_closure_tool_call.json)
for the portable closure call shape.

## Licence

MIT — see [LICENSE](LICENSE).
