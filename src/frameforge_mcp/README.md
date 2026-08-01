# FrameForge MCP server

An optional [Model Context Protocol](https://modelcontextprotocol.io) adapter for
AI authoring feedback loops: a model writes Python that uses `frameforge.sdk`, the
server **validates and renders** the generated FrameForge document, and returns the
artifacts (validation issues, SVG, and a PNG the model can actually *see*) so the
output can be verified — never trusted blind (PALS's Law).

> The MCP boundary is optional. The core SDK and renderers never import it unless
> `frameforge_mcp.create_server()` is called; its dependencies live in the `mcp`
> dependency group. See [codebase-standards.md](../../../docs/codebase-standards.md) §13.

## Run it

```bash
uv sync --group mcp                       # installs mcp[cli] + cairosvg (raster fallback)
uv run --group mcp python -m frameforge_mcp
# or:
make mcp                                  # same, over the default FastMCP transport
make live                                 # local web UI over the same session functions
```

## Tools & resources

Discovery (look up, don't guess):

- `describe_capabilities` — LIVE introspection of the document model (`src/frameforge/model.py`
  via `frameforge.sdk.model`): no topic returns the capability index (object types, flowable
  types, inline kinds, canvas presets, profiles, tool names); a topic of
  `flowables`/`inlines`/`style`/`presets`/`tools` returns that catalog; a type/model name
  (`rect`, `paragraph`, `document`, `page`, `canvas`) returns its fields + JSON schema.
- `list_fonts` — the font families fontconfig can resolve (`fc-list`), with an optional
  `family` resolution check (`fc-match`) that catches silent substitution before a render,
  plus the session document's pinned `defs.tokens.fonts`. Degrades to a structured error with
  an install hint when fontconfig is absent.
- `get_guide` — the `frameforge_guide` prompt text as a tool, for prompt-less MCP clients.

Forward (author → render):

- `run_sdk_code` / `run_sdk_client` — run Python that builds a document, then validate + render it.
- `render_frameforge_yaml` — validate + render caller-supplied YAML directly (no Python).
- `write_sdk_client` / `read_sdk_client` / `list_sdk_clients` — edit whitelisted SDK client files.
  `write_sdk_client` also accepts an **anchored edit** (`old_string` + `new_string`, exact and
  unique in the file) as an alternative to re-sending the whole `code`.

Render options (all three render tools): `to='pdf'` additionally assembles the rendered pages
into a vector `document.pdf` via CairoSVG + pypdf (the `pdfout` group; the CLI `--to pdf`
mechanism), reported under `result.pdf` and as a session resource. `to='html'` additionally
writes a self-contained `document.html` (the CLI `--to html` mechanism, via
`frameforge.conform.render_html`): semantic shell, inline SVG artwork, hoisted palette + text-style
classes, screen-reader landmark — no extra dependency, and full object-type parity with SVG
because the same engine paints it. Both are reported by reference, never inlined. `scale` sets the PNG raster
zoom (2.0 = double resolution — DPI control). `real_metrics` (`'auto'`|`true`|`false`, default
`'auto'` = on when fontTools is installed) measures text with real glyph advances so
wrap/shrink/ellipsis decisions match the rendered pixels; the resolved mode is reported as
`result.real_metrics`. Pass `font_closure='/path/book.fp'` to use exact
SHA-256-pinned bytes instead; `font_generics={'sans-serif': 'Inter'}` maps CSS
generics to concrete faces inside that closure. A closure outranks
`real_metrics`, is strict by default, and reaches static validation, SVG/HTML,
reports, and `fit_text`. Results include `result.metrics_mode == 'closure'`,
`result.font_closure.sha256`, and the same value in
`result.diagnostics.metrics_mode`. Every render also returns a `result.diagnostics` block (renderer
`warnings`, `skipped_objects`, `skipped_flowables`, `font_fallbacks`, opt-in `layout`
report) persisted into the session's `diagnostics.json` — nothing the renderer drops or
substitutes is silent.

Inverse (image / PDF / SVG → draft), needs the `vision` group:

- `propose_from_image` / `propose_from_document` — propose a **draft** document from a
  screenshot or rasterized PDF page, then round-trip it through validate + render. The
  proposal is unverified CV/VLM output; treat it as a starting point.
- `propose_from_svg` — ingest an existing SVG's elements as FrameForge objects (1:1
  vector lowering, no raster step), optionally recoloured by region, then validate + render.

Visual QA (reference vs. recreation), needs Pillow (`vision` or `render` group):

- `compare_images` — crop matching regions from a **reference** and a **candidate** and lay
  them out `reference | candidate | difference` (bright red = mismatch), each crop scaled up
  and stamped with a naive pixel-match score. Lets a vision model *see* where a recreation is
  off instead of eyeballing two downscaled thumbnails. Either image can be a filesystem path
  or a `frameforge://session/<id>/page/<n>.png` URI, so a page just rendered by
  `run_sdk_client` compares directly against a reference. `regions` are `{name, box}` with the
  box normalized `[x, y, w, h]` in 0..1; omit them to auto-split by `grid` (default `[2, 3]`).
  Each region also reports real `metrics` (**NCC / RMSE / MAE / pct_diff**); `align=True`
  phase-aligns the candidate first (so a pure offset doesn't read as error) and reports
  `shift_px`. Scores are relative hints, **not** verdicts — the panels are the signal (PALS's Law).

Measure + reconstruct (raster → reliable coordinates, for vector recreation), needs Pillow:

- `measure_image` — overlay an auto **grid + rulers + coordinate system** on an image (and
  optional zoomed crops), box + ID named **regions**, and anchor **landmarks**; returns the
  overlay PNG plus an exact `spatial` payload — coordinate system (`top-left` / `bottom-left`
  / `center`), per-region `bbox/centroid/area/offset`, structural + detected landmarks, and
  each zoom crop's `origin`+`scale` back to source pixels. The overlay keeps the source's
  pixel size, so coordinates read 1:1; a zoomed crop's rulers stay labelled in **source**
  coordinates (zoom-aware).
- `mark_points` — the AI's aim + click: give points in **any frame** (`norm` / `px` / `cs` /
  `{landmark, dx, dy}` / `viewport_px`) and get numbered crosshairs plus each point resolved
  in every frame (image px + coordinate system + normalized + viewport px). Points are
  anchored to the image, so the aim stays fixed as the viewport moves; `connect` previews the
  path they would trace.
- `overlay_images` — align an overlay onto a base by matched **landmark pairs**, report
  per-pair offsets + residuals and the best-fit **scale + translation** (rotation not
  modelled), and emit an aligned composite.

  All measured geometry and the structural anchors (`A1..A9`) are exact; **detected**
  landmarks (`L*`) are UNVERIFIED CV hints (PALS's Law).

Coordinate workspace + reconstruction (the AI's precise pointer), needs the `vision`
group (Pillow + numpy; `score_reconstruction` needs numpy, `vectorize_image` needs
OpenCV and — for `trace` — the potrace binary):

- `workspace` — a **stateful** pin board bound to one image, persisted per `session_id`
  (`workspace.json`). Actions: `open`, `pin` (points in any frame; may reference existing
  pins), `nudge` (the "mouse" — move selected pins by a delta, e.g. `unit="norm", dx=-0.01`),
  `move`, `snap` (snap pins to the nearest **bright/dark/edge/centroid** pixel — pixel-accurate
  refinement), `transform` (translate+scale+rotate a pin group about a pivot — fix
  proportions/perspective), `unpin`, `clear`, `viewport` (set/clear a crop), `pan`/`zoom`
  (fixed aim), `checkpoint`/`revert` (save + roll back — try, `score_reconstruction`, undo if
  worse), `render`. Pins persist across calls and are image-anchored, enabling **multi-pass
  refinement**, **multi-pinning**, and **group adjustment** until pixel-accurate.
- `construct_vectors` — draw FrameForge geometry from anchor points (workspace `pins` or
  explicit `points`): `line`, `path`/`trace`, `curve`, `spline`, `triangle`, `polygon`,
  `closed`, `rect`, `ellipse`, `circle`, `star`, `arc` (3 points → circumcircle sweep, or
  centre + `r` + `start_deg`/`end_deg`), and `text` (anchor point + `text` + `size`, or 2+
  points as a bbox). Sizes the page to the source so it overlays 1:1, then validates +
  renders. Diff against the source with `compare_images` to converge.
- `score_reconstruction` — the **numeric** convergence signal: samples the constructed
  shapes (same schema as `construct_vectors`) and measures each sample's distance to the
  source image's real edges, returning `on_edge_frac` (fraction within `tol` px of an edge)
  + mean/median/p90 distances over a match overlay (edges cyan, samples green on-edge / red
  off). Where `compare_images` shows *where* a recreation is off, this reports *how far* —
  drive `on_edge_frac` up across passes. `symmetry_pairs`/`collinear_groups` add a
  geometry-consistency report; their points accept raw `[x, y]` pixels **or workspace
  pin / landmark ids** (resolved against the session's pins). Edges are an adaptive-Sobel
  **heuristic**: a RELATIVE guide, not ground truth (PALS's Law).
- `vectorize_image` — **automatic** raster→vector: `region` (k-means colour → filled polygons),
  `outline` (edges → polylines), `trace` (potrace Bézier → SVG ingest; smooth outlines of a
  crisp bi-level mark), `layers` (**solid-bg logo tracer**: AA-aware palette + even-odd
  holes — highest fidelity for flat, solid-background logos), or `auto` (classify the raster
  and route to the best mode; the decision + presets are reported under
  `result.vectorize.auto`, and explicit args always win). `region_box` traces just a crop,
  placed 1:1 in the full image; `ocr` adds text objects and reports backend status under
  `result.vectorize.ocr` (never a silent empty list). Use it when hand-pinning an intricate
  mark can't converge — `trace` for a crisp mark on a busy/gradient ground, `layers` for a
  solid-background multi-colour logo.
- `detect_regions` — **region analysis** of a raster (`method='closed'|'flat'|'consensus'`):
  returns a `spatial` payload of detected regions (`bbox_px` + `box_norm` + `centroid_px`/
  `centroid_norm`, fill colour, polygon/holes, shape class) with optional `cluster`ing of
  repeated shapes, and renders an annotated overlay as the session's page 1. Answers "what
  regions exist?" so pins/`construct_vectors` can start from measured geometry instead of
  guesses.
- `map_coordinates` — transpose coordinates: `homography` (fit + apply a projective map to
  points, ≥4 pairs), `to_3d` (lift 2D onto a plane), `project` (3D→2D via the SDK camera), or
  `warp` (apply the fitted homography to **rectify/dewarp an image** — emits the corrected PNG).
  Honest scope: plane-to-plane projective + pinhole camera (no lens distortion).

Sessions:

- `get_session_resource`, `list_sessions`, `cleanup_sessions`.
- Resources: `frameforge://session/{id}/document.yaml`, `…/document.pdf` (after a `to='pdf'`
  render), `…/document.html` (after a `to='html'` render), `…/page/{n}.svg`, `…/page/{n}.png`, `…/diagnostics.json` (full result incl. the
  complete `spatial` coordinate payload), `…/workspace.json` (persisted `workspace` pins +
  viewport).
- **Render clobber:** every image tool resets the session's `page/*.png` on each call, so
  `page/1.png` always holds the LAST tool's render — only `workspace.json` pins persist.
  When a call replaces renders a **different** tool left in the session, the result says so
  (`replaced_renders` + a `render_warning` naming the prior tool). In a shared-session loop
  (construct → score/compare), pass a render's `frameforge://…/page/1.png` into the next tool
  *before* the next call overwrites it, or use a distinct `session_id` to keep both renders.

The `frameforge_guide` prompt returns a model-facing capability guide for the SDK.

## Visual verification (how a render is *seen*)

A vision model can only see a raster (PNG), not SVG, so the render tools rasterize to
PNG by default (`raster_png=True`) and attach it as an image content block; the SVG
stays a resource link. Rasterization uses the first backend that can run:

| Order | Backend | Group | Notes |
|---|---|---|---|
| 1 | Headless Chromium | `browser` (+ `playwright install chromium`) | Highest CSS fidelity (filters, blend modes, masks). |
| 2 | CairoSVG | `mcp` / `pdfout` | Browser-free; faithful for the vector/text/gradient core. |

Each render reports the `backend` it used. Only when **neither** backend is available
does the result carry a `render_warning` and ship SVG/diagnostics text alone — read the
warning, install a backend, and re-render.

## Failure feedback (one round-trip)

- Every tool returns the shared structured envelope on an expected failure —
  `{ok: false, error, error_type?, hint?}` — instead of raising; the `hint` names the fix
  (e.g. a missing client file points at `list_sdk_clients`, a missing session artifact
  points at `list_sessions` and lists what the session *does* contain). `isError` is set on
  every tool result, and `ok: false` always carries an `error`.
- A non-zero build puts a bounded `stderr_tail` in the model-facing summary, so the
  traceback is visible without a second fetch of the diagnostics resource. The summary
  also surfaces `hint`, `pdf`, and `replaced_renders` whenever they are present, and
  vision-group import failures carry the install command as a separate `hint`.
- A schema-invalid SDK build returns root-cause-grouped `error_groups` plus
  `issues_total` / `groups_total`. Each group carries the nearest authoring
  `file:line:function`, a representative path/message, and a known-helper hint when
  available; `validation.issues` retains one compact representative per group instead of
  every Pydantic union-arm echo. The harness lowers these into `build_error.json`, and the
  parent result is enriched from that sidecar. Capture is enabled by default only in the
  MCP SDK subprocesses; `DocumentBuilder(capture_provenance=False)` or
  `FRAMEFORGE_SDK_PROVENANCE=0` opts out. Provenance never enters serialized documents.
  Static-rule failures still set `error` + a `hint` pointing at `validation.issues` and
  `describe_capabilities`.

## Operational note — live discovery; restart rendering code after changes

`describe_capabilities` and `get_guide` import the configured source tree in a fresh,
secret-stripped subprocess. Their results are cached by a metadata token covering
`src/frameforge/**/*.py`; a source edit invalidates the cache on the next call without an
MCP restart. Every `describe_capabilities` payload carries `source_token` and
`introspected_at`, so clients can record exactly which discovery snapshot they used.

The SDK **client** also runs in a fresh per-call subprocess, but the **validate/render
pipeline still runs in the long-lived MCP server process**. Edits to validation,
rendering, or other already-imported server code therefore **do not take effect until the
server restarts**. After changing that code, restart `make mcp` (and `make live`, which
shares the same functions). Use a fresh interpreter to verify pipeline changes during
development rather than the running server.

## Configuration (environment variables)

| Variable | Effect |
|---|---|
| `FRAMEFORGE_REPO` | Where the standalone `frameforge-sdk` looks for this engine's `tooling/validate.py`. Read by `frameforge_sdk.validate` when the engine is not pip-installed (an uninstalled checkout); unset, it resolves through the installed `frameforge` package and raises `EngineUnavailable` if neither is found. |
| `FRAMEFORGE_MCP_SESSION_ROOT` | Where per-session scratch dirs/artifacts live (default: `frameforge-mcp-sessions` under the system temp dir). |
| `FRAMEFORGE_MCP_EDIT_ROOTS` | `os.pathsep`-joined roots the client-file tools may read/write (default: `static/examples`). |
| `FRAMEFORGE_MCP_INPUT_ROOTS` | Confine `propose_*` inputs and `font_closure` paths to these roots (unset = any readable path). Relative closure paths resolve from the document/client base directory. |
| `FRAMEFORGE_MCP_KEEP_ENV` | Truthy keeps secret-looking env vars in the code subprocess (default: stripped). |
| `FRAMEFORGE_SDK_PROVENANCE` | Set `0`/`false`/`off` to disable author-site capture in MCP SDK subprocesses (default: enabled there; disabled for ordinary SDK use). |
| `FRAMEFORGE_MCP_STRUCT_LOG_PATH` | Path for the JSONL structured tool log (default: under the session root). |
| `FRAMEFORGE_MCP_RENDER_TIMEOUT` | Soft per-render wall-clock budget, seconds (default: 30). |
| `FRAMEFORGE_MCP_RENDER_MAX_PAGES` | Hard page ceiling refused before the in-process render starts (default: 200). |
| `FRAMEFORGE_MCP_RENDER_MAX_OBJECTS` | Hard object ceiling refused before rendering (default: 50000). |
| `FRAMEFORGE_MCP_RASTER_MAX_PAGES` | Max pages rasterized to PNG per call (default: 8). |
| `FRAMEFORGE_MCP_RASTER_TIMEOUT` | Soft wall-clock budget for the rasterization loop, seconds (default: 60). |
| `FRAMEFORGE_MCP_MAX_INLINE_IMAGES` | Max PNGs inlined as image blocks (rest stay resource links; default: 4). |
| `FRAMEFORGE_MCP_MAX_RESULT_CHARS` | Per-tool-result transport budget; no result ever exceeds it (default: 60000). |
| `FRAMEFORGE_MCP_MAX_TEXT_CHARS` | Page size for paginated text artifacts, capped by the result budget (default: 40000). |
| `FRAMEFORGE_MCP_MAX_RESOURCE_BYTES` | Byte cap for binary resource endpoints (default: the inline-blob cap derived from the result budget — 43500 at the stock 60000). |
| `FRAMEFORGE_MCP_MIN_CLEANUP_AGE` | `cleanup_sessions` age floor, seconds — younger sessions are never pruned (default: 60). |
| `FRAMEFORGE_MCP_PUBLISH_ROOT` | Durable root for published session deliverables; render tools accept `publish=true` and copy `document.fg.yaml`, pages, PDF, `diagnostics.json` + a sha256 manifest to `<root>/<session_id>/` (unset = publishing disabled; `publish=true` then fails fast). Must sit outside the session root; `cleanup_sessions` never touches it. |
| `FRAMEFORGE_REAL_METRICS` | Truthy opts the shared SDK/validator/renderer default into host-bound real glyph advances (fontTools); unset means deterministic estimates, and an explicit per-call flag wins unless `font_closure` supplies stronger byte-pinned evidence. |
| `FRAMEFORGE_MATH_SVG` | `fallback` forces the deterministic math-glyph fallback instead of node MathJax. |
| `FRAMEFORGE_CHROMIUM_NO_SANDBOX` | Truthy launches the raster Chromium with `--no-sandbox` (rootless Docker). |
| `FRAMEFORGE_CHROMIUM_ARGS` | Replace the raster Chromium launch flags entirely (space-separated). |
| `FRAMEFORGE_VISION_VLM_URL` | Optional VLM lane for `propose_from_image`: chat/completions endpoint (unset = lane off). |
| `FRAMEFORGE_VISION_VLM_MODEL` | VLM lane model id (required with the URL). |
| `FRAMEFORGE_VISION_VLM_KEY` | VLM lane bearer token (optional). |

Numeric knobs share one fallback rule: a non-numeric or non-positive value is
IGNORED and the stated default applies (`_positive_env` / the pipeline's raw
readers) — misconfiguration degrades to the documented behaviour, never to a
crash or an unbounded limit. The table above is gated: every consumed
`FRAMEFORGE_*` variable must appear here with its real default
(`tests/test_env_var_docs.py` compares the stated numbers against the code's
defaults, so a changed default with a stale row fails the suite).
Container-only knobs (`FRAMEFORGE_REFRESH_FONTS` — rebuild the fontconfig
cache at container start) are read by `docker/entrypoint.sh`, not by this
package, and are documented in [docker/README.md](../../../docker/README.md).

## Security posture — trusted-operator only

`run_sdk_code` / `run_sdk_client` execute caller-supplied Python in a **subprocess** with
secret-looking env vars stripped, a wall-clock timeout, and hard input ceilings. This is
**process isolation, not a security sandbox**: the code still runs with the server user's
filesystem and network access. Run the server only for local, trusted use — do not expose
it to untrusted callers.

---

[↑ Back to the project README](../../../README.md)
