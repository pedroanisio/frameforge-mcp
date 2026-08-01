# frameforge-mcp — CHANGELOG

*Version headings mark distribution releases. The document contract this server
speaks is `frameforge_api.HEAD_VERSION`, which moves on its own schedule.*

---

## Unreleased

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
