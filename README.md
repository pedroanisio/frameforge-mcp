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
- **Visual QA**: real NCC/RMSE/MAE metrics between a reference and a candidate.
- **Raster → vector**: a coordinate-aware reconstruction workspace — measure,
  mark, overlay, fit primitives, vectorize, score.
- **Image → draft**: propose documents from images, PDFs, or SVGs. Every
  proposal is unverified CV/VLM output and is round-tripped through a render
  before it is shown.

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

The base install renders through CairoSVG, so a vision model can see — and
therefore verify — a render with no browser present.

## Provenance

Every module under `src/` is extracted verbatim from the
[frameforge](https://github.com/pedroanisio/frameforge) monorepo by
`tooling/extract_mcp.py`, which repoints intra-distribution module names and
nothing else. To re-sync:

```bash
make extract        # re-derive src/ from the monorepo
make extract-check  # GATE: fail if the committed tree drifted
```

## Licence

MIT — see [LICENSE](LICENSE).
