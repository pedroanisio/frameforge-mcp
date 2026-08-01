"""The model-facing FrameForge capability guide returned by the guide prompt."""
from __future__ import annotations


FRAMEFORGE_GUIDE = """\
# FrameForge MCP — what the SDK offers and the server's capabilities

FrameForge v2 is a document/graphics DSL. The Pydantic model is the source of
truth; the SDK lowers Python to validated YAML and this server renders it. Always
verify rendered output — CV/LLM output is unverified by default (PALS's Law).

This guide is hand-maintained prose and can drift behind the code. The
`describe_capabilities` tool is the authoritative, live-introspected source of
the model surface and the server's security posture — when this text and its
output disagree, `describe_capabilities` wins. It imports the configured source
tree in a fresh interpreter and returns `source_token` plus `introspected_at`;
compare those fields when diagnosing checkout/server skew. `get_guide` uses the
same source-token cache, so both discovery surfaces notice Python source edits
without an MCP server restart.

## Author with the SDK (`frameforge_sdk`)
Fluent builder:
    from frameforge_sdk import DocumentBuilder
    doc = DocumentBuilder(title="Deck", profile="deck")
    h1 = doc.define_text_style("h1", font_family="sans", font_size=48, color="#E8EAED")
    page = doc.page("p1", canvas={"size": [1280, 720], "units": "px"}, coordinate_mode="absolute")
    page.layer("main").rect([0, 0, 1280, 720], fill="#0E0F11")
    page.text([64, 96, 900, 80], "Hello", id="title", style=h1)
    doc.write(OUTPUT_YAML_PATH, fail_on_error=True)

- Standalone flow and static layout builders are top-level SDK exports:
      from frameforge_sdk import FlowBuilder, grid, inset
      story = FlowBuilder().heading(1, "Results").para("Verified findings.").story()
      doc.flow("report", master=body_master, story=story)
      content = inset([0, 0, 1280, 720], [48, 64])
      cards = grid(content, cols=3, count=5, gap=24)
  `FlowBuilder` (`frameforge_sdk.flow`) provides typed, chainable helpers for
  every flowable and lowers with `.story()` into `DocumentBuilder.flow`; prefer
  `DocumentBuilder.section(...)` when a context manager is more convenient.
  `inset(box, pad)` and `grid(box, cols=, rows=|count=, gap=, pad=)`
  (`frameforge_sdk.layout`) are pure functions returning static `[x, y, w, h]`
  boxes for page primitives; use `Box.inset()` / `Box.grid()` for typed results,
  or renderer-arranged `.stack(...)` when layout should remain dynamic.
- Primitives via `PageBuilder`: `.rect` `.text` `.line` `.image` `.ellipse` `.circle`
  `.polyline` `.polygon` `.path` `.curve`, plus `.icon`, `.dimension`, `.arc`,
  `.sector`, `.ring`, `.star`, `.add(obj)` / `.extend(objs)`, and
  `.stack(box, kind="row|column|grid|wrap")` layout groups. `DocumentBuilder.master()`
  exposes `running_header`, `running_footer`, and `footnote_area`; `define_counter`
  declares numbering series for generated labels.
  - `.connector(start, end, ...)` — anchored connector between objects (typed at
    HEAD): endpoints are an object id, a point, or `{"ref", "port"|"side", "offset"}`;
    optional `route=[...waypoints]` + `route_kind`, boxed `label`/`label_box`, and
    `arrow_start`/`arrow_end` markers (merged into the inline `stroke_style`).
    `route_kind="orthogonal"` with no waypoints computes real axis-aligned
    elbows from the endpoint sides (authored waypoints always win).
    Marker kinds (validated; unknown names fail): `filled_triangle` (= `true`),
    `hollow_triangle`, `filled_diamond`, `hollow_diamond`, `open_arrow`.
  - Stacking: layers paint by `Layer.z`; within a layer/group, object `z` wins
    over `style.z_index` (both stable, default 0; conflicting values raise a
    `z_conflict` diagnostic).
- Paint (`frameforge_sdk.paint`): `stroke(width, color=...)`, `fill_stroke(...)`,
  `linear_gradient`/`radial_gradient`/`conic_gradient`,
  `hatch`/`dots`/`grid_pattern`/`pattern`, `glow`/`neon`/`shadow`/`soft_shadow`,
  `rgba`, and `text_style(size, color=...)` for the text subset of `Style`,
  including OpenType/variable-font fields (`feature_settings`, `variation_settings`,
  `variant_caps`, `variant_numeric`, `variant_ligatures`). Filter/style helpers:
  `blur_filter`, `turbulence`, `displacement_map`, `diffuse_lighting`,
  `specular_lighting`, `filter_chain`, `style_effects`, `effect`, `effect_stack`,
  and `appearance`. `displacement_map(...)` is self-noised: set its own
  `base_frequency`, `num_octaves`, `seed`, and noise `type`; do not prepend a
  `turbulence(...)` item. Standalone `turbulence(...)` is a visible texture
  overlay whose strength is `opacity` and whose blend operation is `mode`.
  `filter_chain(...)` entries are stacked self-contained presets, applied
  independently in order; they are not wired into one SVG primitive graph.
  Static validation warns when a primitive preset is mixed into a longer chain.
  Stroke geometry MUST go through `stroke()` (paint in `stroke`,
  geometry in the inline `stroke_style` bundle); an inline `stroke_width` on a
  paint-only line/polyline/path is rejected. `dash=` accepts either a length list
  or SVG-style `"4 4"` / `"4, 4"`; it normalizes to `stroke_dasharray`.
- Widgets (`frameforge_sdk.widgets`): `avatar` `badge` `button` `card` `kpi` `pill`
  `progress` `table` `tabs` `toggle` `divider` `field`, plus `Panel`/`Theme`.
- Data & geometry (`frameforge_sdk.chart` / `.topology` / `.geometry` / `.draw`): `Chart`+`Frame` (series: `line`, `bars`, `scatter`, `area`, `pie`,
  `donut`, plus `marker`/`axes`/`legend`), `Graph`/`Node`/`Edge`, `Camera`/`Scene3D`/
  `Mat3`/`Mat4`, `CubicBezier`/`Path`, `ScalarField`/`VectorField`, `lattice`/`Lattice`/`manifold`
  (`frameforge_sdk.lattices` / `.fields` / `.manifold`), `greeble`, `grid_lines` (`frameforge_sdk.macros`).
  - Curve sampling: `parametric_curve(fn, domain)`, `function_plot(f, frame)`,
    `polar_plot(r, frame)` — adaptive subdivision, emit polyline/path.
  - Surfaces (`frameforge_sdk.manifold`): `sphere`/`torus`/`mobius`/`klein_bottle`/`saddle`/`wave`
    plus `parametric(fn, u=, v=)` and the bicubic patches `bezier_patch(net)` /
    `bspline_patch(net)` (4×4+ control grid → a tessellated `Scene3D`).
  - Geometry kernel (`frameforge_sdk.geometry`, CG-canon): `Mat3.reflect`/`mirror`; the
    named viewing pipeline `window_to_viewport(window, viewport)` / `ViewingPipeline`
    (the fit `Scene3D.render` uses); 2-D intersections (`segment_intersection`/
    `ray_segment_intersection`/`line_intersection`/`segment_polygon_intersections`),
    3-D intersections (`ray_plane_intersection`/`segment_plane_intersection`/
    `ray_triangle_intersection`) and curve×line (`segment_curve_intersections`/
    `line_curve_intersections`, de Casteljau); curves `CubicBezier.curvature`/`arc_length` +
    `polyline_length` and surfaces `surface_curvature(fn, u, v)` → `(K, H)`; comp-geometry
  `convex_hull`/`convex_hull_3d`/`aabb`/`aabb3`/`obb`/`polygon_area`/`point_in_polygon`.
  - UML 2.5.1 (`frameforge_sdk.uml_models` + `frameforge_sdk.uml`): validate a
    typed semantic model such as `UMLClassDiagramModel`, then call one of the 14
    `compose_*` functions. Start with `compose_class_diagram`; behavioral
    counterparts include `compose_sequence_diagram` and `compose_state_machine`. The
    suite covers class, package, use-case, component, deployment, activity,
    state-machine, sequence, timing, communication, interaction-overview,
    profile, composite-structure, and object diagrams. A composed result's
    `to_document(title=, page_id=, canvas_size=)` returns a model-valid v2
    document; `to_page(...)` returns an embeddable absolute page. Hierarchical
    composers use the deterministic four-stage `sugiyama_layout`
    (`frameforge_sdk.sugiyama`): Eades-Lin-Smyth cycle removal, longest-path
    layers with dummy bends, median crossing minimization, and Brandes-Kopf
    coordinate assignment. OMG UML 2.5.1 XMI reference files and checksums live
    under `static/specs/uml-2.5.1/` and are not loaded on the render hot path.
  - `Scene3D.render(shading=, cull_backfaces=, near_clip=)` — opt-in `near_clip=True`
    Sutherland–Hodgman-clips faces straddling the near plane instead of dropping them.
  - Fractals (`frameforge_sdk.fractal`): an `lsystem` + `turtle` engine with
    `koch_curve`/`dragon_curve`/`sierpinski_arrowhead` presets — self-similar curves
    lowered to plain polylines.
  - Deterministic sampling (`frameforge_sdk.rand`):
        from frameforge_sdk import Rand, halton, poisson_disk, jittered_grid
        root = Rand("document")
        dots = poisson_disk([0, 0, 640, 360], radius=12,
                            rand=root.derive("dots"), max_points=500)
    `derive(name)` creates an independent named sub-stream whose output does not
    depend on parent draws or sibling creation order. `halton` produces
    low-discrepancy points; `poisson_disk` enforces a minimum separation;
    `jittered_grid` emits one point per cell. All return plain `Vec2` values,
    page space is Y-down, and the default seed is deterministic. This API is
    not cryptographic. Use it directly through `run_sdk_code`; no dedicated MCP
    tool is needed.
  - Sampleable coherent noise (`frameforge_sdk.noise`):
        from frameforge_sdk import Noise, ScalarField, domain_warp
        source = Noise(7, frequency=0.35, basis="simplex")
        field = ScalarField(Noise(7, basis="simplex").field(),
                            domain=(0, 0, 8, 5))
        heatmap = field.heatmap(box=[0, 0, 640, 360], steps_x=32, steps_y=20)
        warped_xy = domain_warp(2.5, 1.25, seed=7, strength=0.8)
    `value_noise_2d`, `perlin_2d`, and `simplex_2d` return author-time CPU values;
    `fbm` adds normalised octaves and `domain_warp` returns coordinates
    for re-sampling. This standard-library API is deterministic and not
    cryptographic. It is distinct from `paint.turbulence`, which is a
    renderer-side SVG filter and cannot position or colour geometry in Python.
    Use sampleable noise through `run_sdk_code`; no dedicated MCP tool is needed.
  - `Frame` scales accept structured specs: `{"kind":"log","base":b}` / `{"kind":"pow","exp":e}`.
  - `multiview(scene, box=...)` — orthographic front/top/side/iso panel grid of a `Scene3D`.
  - `Graph.render(box=...)` auto-lays-out from declared edges (`auto_layout`/`layout_kind`);
    omit `positions` and the algorithm is inferred (grid/radial/layered/spring).
  - `Graph.to_object(box=..., algorithm="auto")` emits a DECLARATIVE `type: graph`
    object that `sdk.expand` lowers into a positioned group at expansion time —
    the render-time auto-layout bridge (nodes+edges in, computed geometry out;
    a node's `pos` overrides the algorithm). Prefer it over baking coordinates.
- Figures (`frameforge_sdk.figure`): `place_figure(source, box)` / `load_figure` /
  `FigureRef` import another FrameForge page's objects as editable children (not a frozen
  image); `FigureAsset` / `place_imported_figure` place an extracted book/PDF figure with
  caption + provenance.
- Design canon — START HERE for colour and type decisions, instead of ad-hoc picks:
  - Colour (`frameforge_sdk.chevreul`, after Chevreul 1839): `closed_palette(ground=,
    ink=, accent=)` assigns every colour a duty and emits a `defs.tokens.colors` fragment
    (dose per `AREA_GUIDE` ≈ 62/30/8); the six harmonies (`harmony_of_scale`,
    `harmony_of_hues`, `dominant_light`, `contrast_of_scale`, `contrast_of_hues`,
    `contrast_of_colours`) + `complement`/`tone_scale` pick colours that agree;
    `color_guide(base)` returns all six harmonies for any base colour (the declarative Color Guide); `contrast_ratio(a, b)` (WCAG) checks text-on-ground legibility BEFORE rendering;
    `grey_document(doc)` is the tone audit — render it next to the original to prove
    hierarchy survives without hue.
  - Perceptual colour (`frameforge_sdk.colorspace`):
    `from frameforge_sdk import delta_e, mix, ramp, to_oklab` gives pure sRGB ↔ XYZ ↔
    CIELab/LCh and OKLab/OKLCh conversions, perceptual distance, and shorter-arc hue
    interpolation. Every transform is an invertible pair — `to_oklab`/`from_oklab`,
    `to_oklch`/`from_oklch`, `to_lab`/`from_lab`, `to_lch`/`from_lch`, `to_xyz`/`from_xyz`,
    plus `srgb_to_linear`/`linear_to_srgb` for the transfer function alone — so a hex
    colour round-trips through any space. `mix(a, b, t)` blends two colours and
    `ramp(stops, n)` walks a multi-stop scale into `n` evenly spaced steps. For example,
    `mix("#172a46", "#f3c969", 0.5, space="oklab")`. The new `mix` and `ramp` default to OKLab;
    existing Chevreul helpers keep `space="srgb"` so old documents remain byte-identical.
    Conversion clips out-of-gamut sRGB channels rather than applying chroma-preserving
    gamut mapping. Use these author-time functions through `run_sdk_code`; no dedicated
    MCP tool or renderer change is needed.
  - Typography (`frameforge_sdk.canon`, after Johnston 1906): `modular_scale(base, ratio)`
    for sizes that agree; `content_box(page_w, page_h, unit, side="recto"|"verso")` for
    the book margin canon (inner 1½ · top 2 · outer 3 · foot 4); `measure_fits(chars)`
    for the 45–75 chars/line band; `caps_tracking(font_size)` for all-caps labels.
- Markdown (`frameforge_sdk.markdown`): `from_markdown(text)` converts a whole
  CommonMark/GFM-subset document into a validated flow document (headings,
  lists, tables, code, quotes, images; front-matter; page breaks) — the fast
  path from prose to a paginated render.
- Geometry engines (compute in the SDK, emit plain paths — never hand-place what
  these can derive):
  - Planar kernel (`frameforge_sdk.planar`, Pathfinder-class): `union`/`intersect`/
    `subtract`/`divide` booleans on flattened rings (holes native — multi-ring
    even-odd paths), `offset_polygon(ring, d)` (miter, collapse-aware),
    `split_at(points, t)` / `cut_along(ring, p1, p2)` path surgery,
    `fill_regions(shapes)` (every bounded region of an overlay as its own fillable
    face, <=8 shapes), `to_path(rings, fill=...)` to emit.
  - Stroke outlines & brushes (`frameforge_sdk.outline`): `stroke_outline(points,
    width, profile=t->scale, pen_angle=, pen_thin=, cap=, join=, smooth=True)` lowers
    a centre-line to a CLOSED filled path — constant width = outline-stroke, profile
    = variable width, pen_angle = calligraphic nib; `repeat_along_path(points,
    spacing=, stamp=obj)` places copies by arc length with tangent rotation.
  - Clipping & masking (`frameforge_sdk.clip`): `clip_rect`/`clip_circle`/`clip_ellipse`/
    `clip_inset`/`clip_polygon`/`clip_path` build the `clip` bag for an object or group;
    `normalize_clip` canonicalises it. `mask_url`, `mask_gradient`, `mask_none`,
    `normalize_mask`, and `mask_style` build the model-native `style.mask` values.
    Nest a clip on a STATIC parent — a clip on a transformed group rides along inside
    the transform.
  - Regions & grading (`frameforge_sdk.region`): `select_in(doc, box)` / `extract_objects`
    pick objects by area; `region_grade` / `gradient_map(objects, ...)` apply a positional
    colour grade; `place_region` re-lays a captured region; `object_bbox` measures it.
  - SVG ingest & embedded lowering (`frameforge_sdk.io`): `svg_to_objects(svg, box=...)`
    ingests SVG text, a `.svg` path, or a `data:image/svg+xml` URI (plain/URL-encoded/
    base64) as native objects; `lower_embedded_svg(doc)` walks a document and replaces
    every embedded-SVG `image` (literal src or a `defs.assets` key) with a `group` of
    native objects fitted into its box — stable `<id>.<i>` child ids + `meta.region`
    provenance — so recolor/design_audit/planar/effects can reach detail that was
    trapped inside opaque image blobs.
- Style richness (2.4.0 object fields + helpers):
  - `effects: [{kind: "shadow"|"glow", preset?, color/blur/dx/dy/opacity?}, ...]` —
    an ORDERED effect stack (kinds may repeat, first->last); `appearance:
    [{fill?/stroke?/stroke_style?/opacity?}, ...]` — the same geometry painted once
    per pass, bottom->top. Use `effect_stack(effect(...), ...)` and
    `appearance({...}, ...)` instead of hand-writing those bags. Both render only
    when declared (absence is identity).
  - Backend support statement: Chromium has the highest CSS/SVG fidelity for
    filters, blend modes, masks, and `backdrop_filter`. The CairoSVG fallback can
    produce PNGs without a browser but is limited and may not honor those style
    effects fully; inspect render diagnostics and rerender with Chromium when
    those effects are material to the output.
    The `pdf-tex` target renders object-level shadow/glow fields and ordered
    effect stacks on rect, ellipse/circle, line, polyline, polygon, path,
    curve/bezier, text, image, and table. Because portable TikZ has no blur
    filter, its contract is deterministic approximation: a shadow is a
    translated translucent silhouette; vector glows widen or expand the
    silhouette; text glows use eight fixed neighbouring silhouettes; and
    image/table effects use a bounding-box silhouette. Use Chromium when exact
    CSS filter pixels, raster-alpha contours, or true blur are material.
  - `recolor(doc, mapping)` — one-call palette remap: `defs.tokens.colors` by name
    or value, paint literals and gradient stops; input never mutated.
  - Named gradient/pattern fills live in `defs.tokens.fill_styles` and resolve from
    any `fill:`/`stroke:` string.
- Type finesse (`frameforge_sdk.metrics`): `measure_text`/`fit_width`/`wrap_text`/
  `text_height` size boxes to content BEFORE rendering. Use `fit_width` for a
  positioned text box because it includes the renderer's fit tolerance. SDK and
  renderer default to the same deterministic estimate mode; pass the same
  `real_metrics=True` value to both (or set `FRAMEFORGE_REAL_METRICS=1`) to opt
  into installed glyph advances. Preserve authored spacing with
  `style.white_space = pre|pre-wrap|pre-line|break-spaces`;
  `kerned_spans(text, pairs=...)` applies
  explicit pair kerning as grammar-native spans; `font_kern_pairs(family, text,
  font_size=...)` reads the resolved font's kern table (fontTools; degrades to {}).
- Slide patterns (`frameforge.patterns`): `load_catalog()` — 375 typed layout
  patterns; `compose(pattern_id, fill)` validates a `{role: content}` payload and
  returns a full deck page (zone boxes from the placement vocabulary, treatments
  applied). Prefer a catalog pattern over hand-rolling a standard slide.
- Content library (`frameforge.library`): `load_theme(name)` — 7 consulting themes
  (bain/bcg/deloitte/ey/kpmg/mckinsey/pwc) as ready `defs.tokens` fragments;
  `load_symbols(pack)` + `support_text_styles(pack)` — cover/agenda/insight/hex
  symbol packs instantiated via `use` objects and lowered by `sdk.expand`;
  `honeycomb_capability_map(data)` / `module_hub_radial(data)` generate whole
  diagram pages from plain data dicts (render-ready, pre-expanded).
- Books (`frameforge_sdk.book`): `BookBuilder(title=, author=)` -> `.chapter(t)`
  -> `.section(t)` / `.para` / `.figure(obj, caption=)` composes front matter +
  chapters into ONE paginated flow document — numbering computed at build time
  (chapters `1`, sections `1.1`, captions `Figure 2.1 — ...`), chapters open on
  fresh pages, figures keep their captions (`keep_with_caption`), boxless
  geometry gets a derived size, and the TOC lists chapters only.
- Symbols & lowering (`frameforge_sdk.expand`): `expand(doc)` lowers grammar-level
  `use`/`component` objects into core primitives and pins asset/font hashes — run it
  before rendering any document that carries `defs.symbols`.
- Humanize (seeded imperfection): set `humanize: {seed: N, roughen: ..., drift_deg:
  ...}` on the document or any object — a deterministic hand-drawn wobble applied at
  expansion; absence is identity, same seed = same page.
- Overlap separation (`frameforge_sdk.separate`): `separate_rects(boxes, world=...)`
  is a deterministic AABB separation kernel (pairwise relaxation, world-clamped);
  `apply_separation(doc)` nudges ONLY the boxes the static audit's `overlap` rule
  flags — the solver for detect-without-solve overlap findings.
- Validation: `validate_static_rules(doc) -> ValidationReport(ok, issues)` includes
  text-fit diagnostics by default; use `text_fit=False` only for a structure-only
  pass. Deep containment resolves group-local children. `decorative` is
  accessibility/overlap intent, while `containment="allowed"` explicitly consents
  to intentional bleed (and applies to a group's subtree). Also available:
  `assert_golden(...)`; `HEAD_VERSION` is the current spec version.

## Flow defaults & reserved styles (ADR-0006)
The flow renderer injects NO undefined style — it renders only what the document
defines. Five reserved `tokens.styles` names carry the flow defaults (the
authoritative list is the engine's `RESERVED_STYLES` constant, exported live by
`describe_capabilities("style")`):
- **`body`** — the DEFAULT text style for every text surface. Define it to set
  the document face/size/colour; without it, text falls back to a single
  documented engine default (you usually do not want that).
- **`caption`** — styles generated figure and table captions.
- **`code`** — styles code blocks (fallback: monospace / 10 / #333).
- **`toc`** — styles generated table-of-contents entry lines.
- **`toc_title`** — styles the generated table-of-contents title.
Headings/lists resolve their own `style`; a `table` carries its chrome via
`style` (header_fill/header_text/cell_text/zebra_fill/grid_color/cell_size —
header_text/cell_text are colour-or-style-ref: a defined style name is a style
ref, any other string is a colour, identically in flow tables and TableObject) —
chrome it does not define is not drawn. Every render result reports a compact
`design` census (faces/sizes/weights/colours + sprawl health flags); the
`design_audit` tool returns the full drift-proof report for a session.

## Server tools
Discovery (look up, don't guess):
- `describe_capabilities` — LIVE introspection of the document model: no topic = the
  capability index (object types, flowable types, inline kinds, canvas presets, profiles,
  tool names, SDK export count); topic = `flowables`/`inlines`/`style`/`presets`/`tools`/
  `sdk` (the ENTIRE public SDK surface — every export with kind, signature and a one-line
  explanation, introspected live from `frameforge_sdk.__all__`), or a type name
  (`rect`, `paragraph`, `document`, `page`, `canvas`) for its fields + JSON schema.
  Check the schema BEFORE authoring instead of iterating on validation errors.
- `list_fonts` — the font families fontconfig can resolve; pass `family` to see what a
  request actually resolves to (`resolves.exact=false` = silent substitution) BEFORE a
  render swaps in a default face. Reports a session document's pinned `defs.tokens.fonts`.
- `fit_text` — measure a string in the render tool's selected metric mode and return
  both its raw advance and a line-breaker-safe width; use it before assigning
  absolutely positioned token boxes.
- `get_guide` — this guide as a tool, for MCP clients that do not surface prompts.

Forward (author -> render):
- `run_sdk_code` / `run_sdk_client` — run Python that builds a doc, then validate + render SVG.
- `write_sdk_client` / `read_sdk_client` / `list_sdk_clients` — edit whitelisted SDK clients.
  `write_sdk_client` also does anchored edits: pass `old_string`+`new_string` (exact match,
  must be unique in the file) instead of re-sending the whole `code`. For a file too large
  for one `code` argument (some clients cap a single tool argument at ~tens of KB), build it
  in chunks: `append=true` with `allow_partial=true` on every chunk except the last. The
  whole file is capped at 2,000,000 bytes.
- `render_frameforge_yaml` — validate + render caller-supplied YAML directly.
- `get_session_resource` — read `frameforge://session/...` artifacts, transport-budgeted:
  text artifacts paginate (`offset`/`max_chars`, with `total_chars`/`next_offset`), JSON
  artifacts answer targeted `query='/rfc6901/pointer'` requests, and binary artifacts
  (PNG/PDF) return reference metadata — bytes, sha256, on-disk path — with `mode='blob'`
  as a small-file opt-in. No result ever exceeds `FRAMEFORGE_MCP_MAX_RESULT_CHARS`.
- `list_sessions` / `cleanup_sessions` — enumerate and prune per-session scratch dirs.
  Cleanup respects an age floor: sessions younger than `FRAMEFORGE_MCP_MIN_CLEANUP_AGE`
  seconds are never pruned, so a concurrent loop's live session survives a sweep.
- Publishing: the session dir is EPHEMERAL (tempdir + a 5-revision history ring).
  When `FRAMEFORGE_MCP_PUBLISH_ROOT` is set, pass `publish=true` on a render tool
  as the TERMINAL act of an iteration loop: the session's deliverables —
  `document.fg.yaml`, page SVGs/PNGs, `document.pdf`, `diagnostics.json` (the
  caveats travel with the claim) — are copied to `<root>/<session_id>/` with a
  sha256 `manifest.json`; the result gains `result.published`. Re-publishing a
  session replaces its published directory; `cleanup_sessions` never touches the
  publish root. `publish=true` with the root unset fails fast (nothing renders).

Render options (the three render tools): `to='pdf'` additionally assembles the rendered
pages into a vector `document.pdf` (needs the `pdfout` group; reported under `result.pdf`
and as the `frameforge://session/<id>/document.pdf` resource). `to='html'` additionally
writes a self-contained `document.html` — semantic shell, inline SVG artwork, the
document's own palette hoisted to `:root` custom properties, named text styles as
`.fg-ts-<name>` classes, and a screen-reader landmark. It needs no extra dependency and
has full object-type parity with SVG (same engine), so it is the target to ask for when
the deliverable is a shareable, accessible page rather than a raster or a print PDF.
Both are reported BY REFERENCE (path + uri + bytes), never inlined. `scale` controls the PNG
raster zoom (2.0 = double resolution — DPI control). `real_metrics` ('auto'|true|false,
default 'auto' = on when fontTools is installed) measures text with real glyph advances
so wrap/ellipsis decisions match the rendered pixels; the result reports the resolved mode.

Render diagnostics: every successful render also returns a `result.diagnostics` block —
the renderer's structured feedback (`warnings` from the renderer AND painter,
`skipped_objects` swallowed by the per-object safety net, per-type `skipped_flowables`
counts, `font_fallbacks`, and an opt-in `layout` report) — persisted into the session's
`diagnostics.json`. Read it when a render is ok:true but looks wrong: a dropped flowable
or a swallowed object is reported there, not silently passed (PALS's Law).

Failures are structured: every tool returns `{ok: false, error, error_type?, hint?}` on an
expected failure (bad path, bad session id, missing dependency) — read the `hint`, it names
the fix (e.g. which tool lists valid inputs). `ok: false` always carries an `error`.
Schema failures from `run_sdk_code` / `run_sdk_client` also return `error_groups`,
`issues_total`, and `groups_total`. Each group localizes the root cause to the
authoring file, line, and function, names a producing SDK helper when known, and
keeps one representative path/message/hint instead of repeating Pydantic union-arm
noise. `validation.issues` contains those compact representatives. Capture is on
for MCP SDK subprocesses; pass `DocumentBuilder(capture_provenance=False)` or set
`FRAMEFORGE_SDK_PROVENANCE=0` for a hot path. Provenance is sidecar-only and never
changes serialized documents or render hashes.

Security posture: `describe_capabilities(topic="security")` reports the live confinement.
Propose inputs are open by default — any readable path, the localhost-dev posture; set
`FRAMEFORGE_MCP_INPUT_ROOTS` (pathsep-joined roots) to confine the `propose_*` tools in a
hardened deployment. Client writes stay under the editable roots
(`FRAMEFORGE_MCP_EDIT_ROOTS`, default `static/examples`). SDK code runs in a subprocess
with secret-looking env vars stripped (`FRAMEFORGE_MCP_KEEP_ENV=1` keeps them).

Provenance (opt-in): the three render tools (`run_sdk_code` / `run_sdk_client` /
`render_frameforge_yaml`) accept `sign=True` to embed a FrameForge provenance
metatag — a sha256 content fingerprint + tool + version — in every rendered SVG.
`signed_at` sets a fixed UTC timestamp shared by all pages (omit for render time;
pass `""` for a deterministic, fingerprint-only stamp). Signing never alters the
visual render; the result reports `signed: {applied, timestamp}`.

## Seeing the render (visual verification)
A vision model can only *see* a raster (PNG), not SVG. The render tools therefore
rasterize to PNG by default (`raster_png=True`) and attach the PNG as an image
content block; the SVG is kept as a resource link. Rasterization prefers headless
Chromium (`browser` group + `playwright install chromium`, highest CSS fidelity)
and falls back to CairoSVG (browser-free; `mcp`/`pdfout` group) so a PNG is
produced even without a browser; each render reports the `backend` it used. Only
when *neither* backend is available does the result carry a `render_warning` and
ship SVG/diagnostics text alone — read the warning, install a backend, re-render.

Inverse (image/document -> author):
- `propose_from_image` — classical OpenCV/numpy detectors (+ an optional VLM lane)
  propose a DRAFT document from a screenshot/photo.
- `propose_from_document` — the same pipeline over a rasterised PDF page.
- `propose_from_svg` — ingest an existing SVG's elements as FrameForge objects
  (1:1 vector lowering), optionally recoloured by region.
  The `propose_*` drafts are UNVERIFIED: each round-trips through validate + render
  so you see whether it holds, lists which detectors ran vs were skipped, and returns
  the per-object observations. A starting point to refine with the SDK — never final.

Machine verification (read this BEFORE declaring a render done):
A render that returns `ok: true` can still be unusable, so every render result
carries the signals that say so. Check them — they cost nothing and they are the
difference between "it rendered" and "it is readable".
- `design.collisions` — unintended same-layer text painted OVER text. The records
  are in `diagnostics.collisions`, each naming the page, the overlap extent, both
  ink rectangles (`boxes`) and a bounded excerpt of each party (`texts`). `ids` is
  `[None, None]` unless both objects were authored with an `id`, which generated
  documents rarely are — so read `texts` to find them. Non-zero means two blocks
  are stacked; fix the layout, or declare `overlap: "allowed"` on BOTH objects if
  the overlap is the design (watermark, caption over an image).
- `design.unreadable` — the render was faithful and the reader still cannot read
  it: WCAG 2.1 SC 1.4.3 contrast failures against the ink actually painted behind
  the text, type below the legible floor for the page width, runaway measure,
  colliding leading. Details in `diagnostics.legibility`, each with a `basis`
  string carrying the measured number and the threshold.
- `design.unpainted` — shapes that painted NO INK: the object is in the model,
  passes validation, reaches the SVG, and is invisible. This is the one defect a
  visual check cannot catch, because there is nothing on the page to look at.
  The usual cause is stroke intent written as `style: {color, width}` — the shape
  of the pre-P3 bundle, which validates (`Style.color` is TEXT colour,
  `Style.width` is BOX width) and paints nothing. Put paint in `stroke` and
  geometry in `stroke_style`. Details in `diagnostics.paint`, each carrying what
  was `declared`, what was `substituted`, and a copy-pasteable `remedy`; a `line`
  or `connector` with the same mistake is painted `#000`/1px instead of vanishing,
  which is why it survives review. `validate` reports the static half of this as
  `inert-stroke-declaration` before you ever render.
- `render_warning` — the same findings in one line, plus text-fit losses,
  `collapsed_line_breaks` (an authored `\n` collapsed because `white_space` is
  `normal` — set `pre-wrap` to keep the rows), and font substitutions.
- `design_audit` — the full report for the session's last render, identical to the
  CLI's `--to audit`, persisted as `audit.json`/`audit.md`.

Visual QA:
- `compare_images` — crop matching regions from a reference and a candidate, lay them
  out reference|candidate|difference (bright red = mismatch) scaled up, so you *see*
  where a recreation is off. Each region also reports real `metrics` (NCC/RMSE/MAE/
  pct_diff); `align=True` phase-aligns the candidate first (so a pure offset doesn't read
  as error) and reports the `shift_px`. Scores are relative hints, not verdicts — the
  panels are the signal (PALS's Law).

## Coordinate-aware reconstruction (raster -> precise vectors)
The measurement + workspace tools give you a coordinate-aware "mouse" for turning a
raster into exact vector geometry. Eight tools, one loop.

Coordinate frames (a point is reported in all that apply):
- image px — pixels from the image origin; the canonical, exact frame.
- coordinate system — image px re-expressed under `origin` = `top-left` (default, +y
  down, = FrameForge page space), `bottom-left` (+y up), or `center` (+y up).
- normalized — fractions 0..1 of width/height (resolution-independent).
- viewport px — pixels within the current zoom crop; a crop is enlarged but its rulers
  stay labelled in SOURCE coordinates, and `source_px = crop.origin_px + read_px/scale`.

Tools:
- `measure_image` — overlay an auto grid + rulers + coordinate system on an image (and
  optional zoom crops), box + ID named regions, anchor landmarks; returns the overlay
  PNG (same pixel size as the source, so it reads 1:1) plus an exact `spatial` payload:
  coordinate system, per-region bbox/centroid/area/offset, landmarks, and each crop's
  origin+scale back to source px.
- `mark_points` — aim + click (stateless): give points in any frame and get numbered
  crosshairs plus each point resolved in every frame; `connect` previews the traced path.
- `overlay_images` — align an overlay onto a base by matched landmark pairs (opacity
  adjustable); reports per-pair offset + residual + the best-fit scale+translation and
  emits the aligned composite.
- `workspace` — a STATEFUL pin board bound to one image; state persists per session_id
  (`workspace.json`). Actions: `open` (bind image), `pin` (points in any frame; may
  reference existing pins by id), `nudge` (move selected pins by a delta — the mouse:
  `unit='norm'|'px'|'viewport'`, e.g. dx=-0.01 = a hair left), `move`, `snap` (snap
  selected pins to the nearest bright/dark/edge/centroid pixel, or sub-pixel edge with
  `snap_to='edge_subpixel'` — refine perpendicular to the local gradient),
  `transform` (translate+scale+rotate selected pins as a group about a pivot — fix
  proportions/perspective), `unpin`, `clear`, `viewport` (set/clear a crop), `pan`/`zoom`
  (aim stays put — coordinate continuity), `checkpoint`/`revert` (save + roll back state:
  try an adjustment, `score_reconstruction` it, undo if worse), `render`. The geometry-
  constraint actions place pins by the *right* method for a rigid mark — fit lines to
  edges, intersect them for corners, enforce symmetry (a luminance diff is blind to a
  single-corner offset): `fit_edge` (re-project selected pins onto one sub-pixel edge
  line — collinear + edge-accurate), `collinear` (project selected pins onto their best-
  fit line), `intersect` (set a corner pin at the meeting of two edges,
  `geometry={'edge1':[ids],'edge2':[ids],'target':id}`), `symmetrize` (enforce bilateral
  symmetry over pin pairs, `geometry={'pairs':[[l,r],...]}` — reports the outlier pair).
  Pins are image-anchored; refine over passes (`select={ids:[...]}` or `{group:...}` for
  multi-pin / group adjust) until pixel-exact.
- `detect_regions` — what closed/filled/stable regions does an image contain? Three
  methods: `closed` (purely topological enclosed faces — any line art), `flat` (fill
  partition: every maximal uniform-colour area, solid AND hollow, with outline-stroke
  recovery), `consensus` (default — ensemble mollified level sets, smooth Fourier
  boundaries; robust on tangled/open linework). Returns exact per-region geometry
  (`bbox_px` + `box_norm`, centroid in px and normalized, sampled fill, boundary
  polygon + holes) under `spatial`, optional shape-equivalence `classes`
  (`cluster='translation'|'congruent'`), and the annotated overlay as page 1. Regions
  feed `workspace` pins and `construct_vectors` points directly. Heuristic output —
  verify the overlay (PALS's Law).
  `fit_spines=True` (G1 — the stroke_outline INVERSE) additionally fits each
  big-enough region's SPINE: skeleton thinning + longest path extended to the
  tips, exact perpendicular-chord widths, an anchored least-squares cubic. The
  per-region `spine` payload (`spine` polyline / `cubic`+`cubic_rms` /
  `width_max` / `profile` / `peak` / `elongation`) is EXACTLY what
  `sdk.outline.stroke_outline(spine, width_max, profile=spine_profile(profile))`
  consumes — a measured shape becomes ONE authored parametric object, not a
  traced outline. `elongation < ~2` flags non-spine-like regions (disks/blobs).
  The authored-clone recipe: detect_regions(fit_spines=True) → stroke_outline
  per region (+ your rims/gloss) → `refine_reconstruction(geometry=True)` —
  the G3 pass first coordinate-descends each provenance-carrying outline's
  GEOMETRY (stroke_outline embeds its spine/width/profile as
  meta.stroke_outline by default; global/tip/base/bow shifts + width scale,
  descent-only, dependent rim/clip overlays re-pointed), then refits the
  paints on the corrected silhouettes. Measured on the lotus reference:
  hand-guessed spines NCC 0.49 → fitted 0.90 → fitted + geometry-refined
  0.94 / 95.4% match, with the document staying a ~40-object semantic source.
  The geometry cost carries an EDGE term by default (H2): candidate
  boundaries are pulled onto the reference's contour field, so recovery works
  even when the document paint carries no colour signal (edge_weight=0
  restores the pure-colour cost). `bands=N` (H1) adds rim-band shading fitted
  on VISIBLE pixels only — decorative craft overlays neither occlude nor get
  banded; rings are meta.band-tagged and replaced idempotently. MEASURED
  CAVEAT: banding pays only when silhouettes verify near-exact (trace-lane
  regime); at authored-petal IoU ~0.93 it degrades the render (clone-v3:
  0.94 → ~0.77) — refine geometry first, add bands only on tight contours.
- `construct_vectors` — draw FrameForge geometry from anchor points (workspace `pins`
  or explicit `points`): line, path/trace, curve, spline, arc (3 points = start /
  on-arc / end through their circumcircle, or 1 centre point + `r` + `start_deg`/
  `end_deg`), triangle, polygon, closed region, rect, ellipse, circle, star, and text
  (requires `"text"` + `"size"` font px; 1 anchor point = box top-left, or 2+ points =
  the bbox). Sizes the page to the source so it overlays 1:1,
  then validates + renders. Best for placing a handful of exact anchors by hand.
- `score_reconstruction` — the NUMERIC convergence signal: samples the constructed
  shapes and measures each sample's distance to the source's real edges, returning
  `on_edge_frac` (fraction within `tol` px of an edge) + mean/median/p90 distances over
  a match overlay (edges cyan, samples green on-edge / red off). Where `compare_images`
  shows you *where* it's off, this tells you *how far* — drive `on_edge_frac` up and the
  distances down across passes. Pass `symmetry_pairs`/`collinear_groups` to add a
  geometry-consistency report (`score.geometry`) — the internal-symmetry and edge-
  collinearity residuals that catch a single-corner offset the luminance % cannot see.
  Geometry points may be raw `[x, y]` pixels OR workspace pin/landmark id strings
  ("P3" / "A9"), resolved like shape `pins` — nudge a pin, re-score, no re-typing.
  Scored `text` shapes contribute no edge samples (glyph outlines are font geometry).
  Heuristic Sobel edges: a RELATIVE guide, not ground truth.
- `vectorize_image` — AUTOMATIC trace of a raster into editable FrameForge objects:
  `region` (k-means colour → filled polygons), `outline` (edges → polylines), `trace`
  (potrace Bézier → SVG ingest; smooth outlines of a crisp bi-level mark), `layers`
  (solid-bg logo tracer: AA-aware palette + even-odd holes — highest fidelity for flat,
  solid-background logos), or `auto` (classify the raster and route to the best of the
  four; the decision + presets are reported under `result.vectorize.auto`, and explicit
  args always win over the route's presets). `region_box` traces just a crop, placed
  1:1 in the full image; `ocr` adds text objects and reports the OCR backend status
  under `result.vectorize.ocr` (`ok` / `no_text` / `unavailable` / `error` — a missing
  Tesseract is never a silent empty list). Reach for this when hand-pinning an
  intricate mark can't converge — `trace` on a thresholded logomark reproduces its
  strokes far better than manual anchors; `layers` for a solid-background multi-colour
  logo.
  For GRADIENT/shaded art (glossy emblems, soft-shaded marks), add
  `fill_mode='gradient'`: every traced shape is re-painted from the SOURCE pixels —
  flat/linear/radial candidates fitted per shape and ranked by colour rms (the
  `fit_primitives` doctrine: a richer family must beat the simpler one, never win by
  default), so ramps become real multi-stop Gradient fills instead of posterised
  bands. Fitted gradients are emitted as EXACT user-space geometry — linear
  `line: [[x1,y1],[x2,y2]]` / radial px `at`+`radius` in each object's local
  space (SVG userSpaceOnUse) — so the ramp lands back on the sampled pixels
  precisely; the same fields are authorable by hand (plus `focal` for off-centre
  gloss and per-stop `opacity`). Works with `region`/`trace`/`layers`; the paint
  summary lands under `result.vectorize.paint`. In trace mode,
  `thresholds=[30, 110, 190]` runs one potrace pass per luminance level and
  stacks the layers darkest-first — base shapes, mid-tone planes, highlights —
  the multi-level recipe for shaded logo art. `supersample=2..3` (trace mode)
  upscales before thresholding so anti-aliased edges are located subpixel
  instead of quantised to whole pixels — kills the traced-edge halo on
  soft-edged sources (turdsize keeps source-pixel semantics; cost ~s²).
  `fill_mode='shading'` goes further (A2): each deep-enough shape is decomposed
  by distance-to-boundary into 3 bands — the core re-fit plus contour-following
  rim bands emitted as self-clipped inner strokes with their own fitted paints —
  the shape-conforming shading a single gradient cannot express (dark rims,
  bright spines). After any reconstruction, run `refine_reconstruction`
  (session_id + the source image): it recomputes per-pixel paint OWNERSHIP in
  z-order and refits every paint on its VISIBLE pixels only (overlapped shapes
  otherwise inherit fits contaminated by occluded pixels), keeps only refits
  whose analytic rms improves, and re-renders — deterministic, descent-only.
  The proven glossy-emblem recipe: trace + thresholds ladder + supersample=2 +
  fill_mode='shading', then refine_reconstruction — measured NCC 0.976 → 0.994
  on the lotus reference. For soft-media targets, `Page.post`
  ({blur, bloom, grain}) adds raster-stage finishing (deterministic seeded
  grain; vector output unaffected, warned).
  Flat default is unchanged; all options are additive.
- `refine_reconstruction` — the descent pass over a session's reconstruction
  (e.g. a prior `vectorize_image`): recomputes per-pixel paint OWNERSHIP in
  z-order and refits every evaluable paint on its VISIBLE pixels only, so
  overlapped shapes shed the contaminated fits full-mask sampling gave them.
  A refit is kept only when its analytic rms improves (deterministic,
  idempotent, can only descend); `min_pixels` floors the refit; summary under
  `result.refine`.
- `map_coordinates` — transpose coordinates: `homography` (fit + apply a projective map
  to points, from >=4 pairs), `to_3d` (lift 2D onto a plane), `project` (3D→2D via the
  SDK camera), or `warp` (apply the fitted homography to actually rectify/dewarp an
  image — perspective correction, emits the corrected PNG).

The CAD operator layer (parametric, computed, verified):
- Solids (`frameforge_sdk.solids`): `extrude(profile, depth)`, `revolve(profile,
  segments=, angle=)` (partial angles grow end caps), `sweep(profile, path3d)`
  (tangent-oriented rings, mitred corners), `loft(profiles, heights=)` — all
  emit `Scene3D` meshes for `render`/`multiview`. `section_loops(scene,
  plane_point=, plane_normal=)` cuts a scene into closed 2D loops;
  `section_object(...)` fits them into a frame as one even-odd hatched path —
  the engineering section view.
- Sketch surgery (`frameforge_sdk.planar`): `fillet_ring(ring, r)` /
  `chamfer_ring(ring, d)` round or cut corners (per-corner selection, oversized
  radii left sharp); `trim_segment` / `extend_segment` cut or prolong to a line.
- Patterns: `array(obj, linear=(dx, dy, n) | polar=(cx, cy, n) | along=pts,
  spacing=)` — geometry-translated linear instances, pivot-rotated polar groups
  (`rotate_items=False` orbits upright), tangent-rotated along-path stamps.
- Construction geometry: `construction: true` objects and `role: construction`
  layers are non-printing datums — excluded from renders unless the document
  sets `meta.show_construction`. Layer `role` also declares
  geometry/annotation/dimension intent.
- Document parameters (`frameforge_sdk.params`, `defs.params`): named numbers
  (or '=expr' strings over earlier ones); ANY '=expr' string field resolves
  before validation — geometry positions become numbers, `text` fields become
  formatted strings (driven dimension labels). Whitelisted arithmetic AST, never
  eval; resolved values are recorded under `meta.resolved_params`.

Primitives-first reconstruction (numeric loop closure):
- `fit_primitives` — measured point sets (e.g. detect_regions polygons) ->
  {line | circular arc | axis-aligned ellipse arc} PARAMETERS: centre/radius/
  radii, angular span, stroke thickness, angle, endpoints — typed straight into
  SDK primitives instead of traced paths. Best fit + all candidates ranked by a
  like-for-like radial rms; an ellipse must show a consistent axis gap above the
  band's noise floor to beat the circle.
- render tools accept `reference=<image>`: the result gains `reference_diff`
  with per-object GHOST VECTORS — each authored object's displacement toward its
  best match in the reference (page 1) — so corrections are typed from numbers,
  not eyeballed off an overlay's double image.
- every successful render archives page artifacts into a history ring (last 5;
  `revision` + `history` on the result); `diff_renders` compares any two —
  default latest vs previous ("did that nudge help?").
- `match_font` — rank resolvable families by shape similarity to a reference
  crop (ink-cropped NCC + aspect penalty); verify the winner in a real render.
- every image input also accepts a `data:image/<type>;base64,` URI — a pasted
  reference reaches the tools without touching the filesystem.
- `overlay_images(rotation=true)` opts into the full-similarity fit (2D
  Procrustes, >=2 pairs) and a rotated composite; the default stays
  rotation-free so tilt keeps surfacing honestly as residuals.
- SDK type-on-path (`frameforge_sdk.pathtext`): `text_on_path(points, text,
  size=, family=, offset=, ...)` sets type glyph-by-glyph along a polyline —
  real-metric advances measured on the offset path (concave side at +offset),
  tangent-following rotation; `offset_path`/`path_walker`/`path_length` are the
  underlying walkers. Wrap the extend in `page.lettering()`.

Reconstruction loop:
  measure_image (see the coordinate field) -> detect_regions (inventory the shapes:
  exact boxes/centroids/fills to seed pins from) -> workspace open + pin the key
  points -> zoom/pan and nudge pins over passes to refine -> construct_vectors from
  the pins -> score_reconstruction (a number: how far the vectors sit from the edges) +
  compare_images(source, reconstruction) (see the residual) -> nudge + rebuild until
  on_edge_frac stops climbing. For a rigid geometric mark, prefer the constraint path
  over eyeballing corners: `fit_edge` the long edges (sub-pixel), `intersect` them for
  corners, and `symmetrize` pin pairs — corners inherit the edges' sub-pixel accuracy,
  and symmetry catches the offset the diff can't. Use map_coordinates when the source is
  perspective-distorted or 3D; vectorize_image when hand-pinning an intricate mark can't
  converge.

Exactness (PALS's Law): the coordinate system, grid, rulers, explicit regions, pins,
and structural landmarks (A1..A9) are exact geometry — trust them. DETECTED landmarks
(L*) and `propose_*` output are unverified guesses — anchor to the structural ones and
verify. The overlay images are drawing aids; the `spatial` JSON is the source of truth.

## Resources
Every tool writes artifacts under `frameforge://session/<id>/`: `document.yaml`,
`page/<n>.svg`, `page/<n>.png`, `document.pdf` (after a `to='pdf'` render),
`document.html` (after a `to='html'` render),
`diagnostics.json` (the full result incl. the complete `spatial` payload), and
`workspace.json` (persisted pins). Read `diagnostics.json` for the exact numbers behind
any measurement; the tool response only summarizes them.
Sessions are single-writer: run ONE agent (or loop) per `session_id` at a time —
concurrent writers race on `page/*.png` and `workspace.json`; give parallel work
distinct `session_id`s.
Only `workspace.json` (pins) persists: every image tool resets `page/*.png`, so
`page/1.png` holds the LAST tool's render. When a call replaces renders a DIFFERENT tool
left in the session, the result says so (`replaced_renders` + a `render_warning` naming
the prior tool). In a shared-session loop, pass a render's `page/1.png` URI to the next
tool before the following call overwrites it, or score/compare under a distinct
`session_id` to keep the reconstruction render viewable alongside.

## Migrating v0.1 documents
A predecessor-dialect document (`scene:`/`visual:` or `deck:`/`slides:`, float
version) converts mechanically: `uv run python tooling/codemod.py doc.yml --from-v01`
(see docs/migration-v01.md for the mapping table) — then validate and render as
usual. Do not hand-translate the envelope.

## Coach — one call, raster to styled document
- `describe_render` — a local (CPU) vision model describes/assesses a rendered page
  in words: pass a filesystem path or a `frameforge://session/<id>/page/<n>.png`
  URI, an optional free-form `question`, and/or a coach `stage`
  (construction/silhouette/style/detail/final) whose rubric it answers. ADVISORY
  (PALS's Law) — a steer, not a measurement; verify with compare_images /
  score_reconstruction / the validator. Needs the optional `vlm` group.
- `coach_vectorize` — the Vector Construction Coach pipeline end to end: ingest a
  raster -> clean -> redraw (Bezier / snap) -> recolor -> gradientize -> paint
  atmosphere, all driven by a named `style` grammar (clean_line, flat_icon,
  blueprint, comic_ink, woodcut, children_book), then validate + render with the
  silhouette readability gate attached. One call: image -> styled FrameForge doc.
  Still UNVERIFIED heuristic geometry — the render + gate is the check.

## Workflow
Author or propose -> read the returned validation issues + the rendered PNG (or the
`render_warning` when raster is unavailable) -> refine the SDK code/YAML -> re-render.
For reconstruction, follow the loop above. Verify every result against pixels, never
against the YAML alone.
"""
