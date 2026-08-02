---
disclaimer: >
  No information within this document should be taken for granted. Verify all
  commands against your environment before relying on them.
last_verified: 2026-08-02
tool_versions:
  - tool: frameforge-mcp
    version: 2.0.0
---

# Migration guides for frameforge-mcp

## How to upgrade to 2.0: file inputs are confined by default

### Overview

This is the **only breaking change in 2.0**. No tool was renamed or removed, no
argument changed, and no result field was dropped.

Before 2.0, leaving `FRAMEFORGE_MCP_INPUT_ROOTS` unset meant *any readable path
is accepted*. The server runs with your filesystem privileges, so an agent that
could be steered into naming `~/.ssh/id_rsa` would pull it into the model's
context. From 2.0 the default is confined and openness is opt-in.

Allowed by default:

| Root | Why |
|---|---|
| the session root | chaining tools means reading back the PNG a render just wrote |
| the working directory | an agent refers to its own project's reference images |
| the repository root | SDK clients and example assets live there |

Affected tools: `propose_from_image`, `propose_from_document`,
`propose_from_svg`, `coach_vectorize`, the measure/CV image inputs, and any
`font_closure` path.

### Prerequisites

1. `frameforge-mcp >= 2.0.0`.
2. Know where your source images and `.fp` closures actually live.

### Steps

#### Step 1: Ask the server what it will accept

```json
{"tool": "describe_capabilities", "arguments": {"topic": "security"}}
```

Read `security_posture.input_roots`. `mode` is `restricted` or `open`, `source`
is `default` / `environment` / `unrestricted`, and `roots` lists what is in
force. Derived live from the environment on every call — never cached.

#### Step 2: Choose a posture

**If your inputs already live under the project or a session** — do nothing.

**If they live elsewhere** (a shared asset volume, a mounted dataset), name the
directories. This is the recommended path:

```bash
export FRAMEFORGE_MCP_INPUT_ROOTS=/mnt/assets:/workspace/fonts
```

Entries are joined by the platform path separator (`:` on POSIX, `;` on
Windows). Named roots **replace** the defaults, so include the session root if
you also chain renders.

**If you need the pre-2.0 behaviour** — accept any readable path explicitly:

```bash
export FRAMEFORGE_MCP_INPUT_ROOTS='*'
```

Understand what this restores: every file the server process can read becomes
reachable by any tool that takes a path. `security_posture()` will report
`mode: open` and carry a warning for as long as it is set.

### Verification

```json
{"tool": "describe_capabilities", "arguments": {"topic": "security"}}
```

`input_roots.roots` lists what you configured, and `warnings` is empty unless
you chose `*`. Then run the tool that reads your file — `propose_from_image` on
a real path is the cheapest probe — and confirm `ok: true`.

### Troubleshooting

- `input path is outside the allowed input roots (...)`: the message names the
  roots in force and the three ways out. This is the new default doing its job,
  not a bug.
- A refusal with **no** `hint`: you are on a build older than 2.0.0. Upgrade.
- Tests or CI that feed fixtures from a temp directory now fail: declare the
  temp base as an input root, exactly as this repository's own
  `tests/conftest.py` does. Prefer that over `*` — a suite that opts out of
  confinement entirely cannot notice when confinement breaks.
- Relative paths resolve against the **server process's** working directory, not
  the client's. If they differ, pass absolute paths or set the roots explicitly.

---

## How to migrate MCP renders to a portable font closure

### Overview

Use this guide when an MCP render currently relies on `real_metrics=true` or
`auto`. The end state validates, fits, and renders against exact font bytes and
returns the evidence needed to reproduce the result.

### Prerequisites

1. Install or update the base `frameforge-mcp` package.
2. Export a `.fp` containing every face used by the document.
3. Place the closure under an allowed input root. Since 2.0 that means the
   session root, working directory, or repository by default — or whatever
   `FRAMEFORGE_MCP_INPUT_ROOTS` names. Check with
   `describe_capabilities(topic="security")`.

### Steps

#### Step 1: Add the closure arguments

Add these arguments to `run_sdk_code`, `run_sdk_client`, or
`render_frameforge_yaml`:

```json
{
  "font_closure": "/workspace/fonts/book.fp",
  "font_generics": {"sans-serif": "Inter"}
}
```

You may leave `real_metrics` in the call; the closure has explicit precedence.

#### Step 2: Use the same arguments for preflight fitting

```json
{
  "text": "Portable",
  "font_family": "Inter",
  "font_size": 12,
  "font_closure": "/workspace/fonts/book.fp",
  "font_generics": {"sans-serif": "Inter"}
}
```

Send this payload to `fit_text` before committing positioned geometry.

### Verification

Confirm all three fields in the render result:

```text
metrics_mode == "closure"
diagnostics.metrics_mode == "closure"
font_closure.sha256 is a 64-character hexadecimal digest
```

Repeat in a new session. The page hashes and closure digest must match.

### Troubleshooting

- `input path is outside the allowed input roots (...)`: move the closure below
  an allowed root or name its directory in `FRAMEFORGE_MCP_INPUT_ROOTS`. See the
  2.0 confinement guide above.
- `no face in the closure satisfies ...`: add the face/weight or correct
  `font_generics`. MCP closure mode is intentionally strict.
- `font closure does not exist`: use an absolute path or resolve the relative
  path from the client/document base directory, not the session output folder.

---

## How to repair an optional lane installed before 2026-08-01

### Overview

Use this guide when a CV, describe, or PDF tool answers `ok: false` with a
missing-module error (`No module named 'cv2'`, `No module named 'pypdf'`) even
though you installed the extra it belongs to. Before 2026-08-01 three extras
under-declared their backends: `[vision]` and `[pdf]` installed
`frameforge-vision` without its `cv` extra, `[vlm]` installed torch without
`frameforge-vision`, and PDF *output* had no extra at all. The lane resolved,
installed clean, and did nothing.

### Prerequisites

1. `frameforge-mcp >= 1.0.0` (post-2026-08-01 declaration).
2. Nothing else — this is a re-install, not a code change. No tool argument, tool
   name, or result field changed.

### Steps

#### Step 1: Ask the server what it actually has

```json
{"tool": "describe_capabilities", "arguments": {"topic": "backends"}}
```

Each lane reports `available`, the `missing` modules, and the `install` command.

#### Step 2: Re-install the lanes reported unavailable

```bash
uv sync --extra vision            # in a checkout; --all-extras for every lane
pip install --upgrade 'frameforge-mcp[vision]'   # from the published distribution
```

Re-installing is required even if the extra name is unchanged: the *contents* of
`[vision]`, `[vlm]`, and `[pdf]` changed, and a resolver will not revisit an
already-satisfied extra without being asked.

#### Step 3: Install what no resolver can

- `[browser]` — `playwright install chromium`
- `[vlm]` — nothing extra to run, but note that the lane needs **torchvision**:
  transformers 5.x requires it for the image processor of Idefics3/SmolVLM, the
  default model. If `backends` reports `"missing": ["torchvision"]`, the
  `frameforge-vision` release you have predates that declaration — install it
  alongside (`pip install torchvision`) or upgrade `frameforge-vision`.
- `vectorize_image(method="trace")` — the `potrace` binary, from your OS package
  manager
- PDF **output** is now its own extra: `uv sync --extra pdfout`

### Verification

```json
{"tool": "describe_capabilities", "arguments": {"topic": "backends"}}
```

Every lane you installed reports `"available": true` with an empty `missing`.
Then run the tool that failed — `detect_regions` on any PNG is the cheapest
probe, and returns `ok: true` with a populated `spatial.regions`.

### Troubleshooting

- Lane still unavailable after a re-install: compare
  `optional_backends.lanes.<name>.missing` against the environment the *server
  process* runs in. A server started from a different virtualenv than the one
  you installed into reports that virtualenv's truth, not yours.
- `pip install 'frameforge-mcp[vision]'` reports "Requirement already satisfied":
  add `--upgrade --force-reinstall`, or install
  `'frameforge-vision[cv]'` directly.
- `describe_render` returns `ok: false` with `"missing": ["torchvision"]` even
  though torch and transformers are installed: that is the gate working as
  intended, not a false negative. transformers 5.x moved image processing behind
  a `pil`/`torchvision` backend split and both Idefics3 classes need
  torchvision, so without it the model loads and the *processor* does not.
  Before this was probed, the same environment raised a `ValueError` out of
  `AutoProcessor.from_pretrained` instead.
