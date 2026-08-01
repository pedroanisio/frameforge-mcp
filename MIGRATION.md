---
disclaimer: >
  No information within this document should be taken for granted. Verify all
  commands against your environment before relying on them.
last_verified: 2026-08-01
tool_versions:
  - tool: frameforge-mcp
    version: 1.0.0
---

# How to migrate MCP renders to a portable font closure

## Overview

Use this guide when an MCP render currently relies on `real_metrics=true` or
`auto`. The end state validates, fits, and renders against exact font bytes and
returns the evidence needed to reproduce the result.

## Prerequisites

1. Install or update the base `frameforge-mcp` package.
2. Export a `.fp` containing every face used by the document.
3. If `FRAMEFORGE_MCP_INPUT_ROOTS` is set, place the closure under one listed root.

## Steps

### Step 1: Add the closure arguments

Add these arguments to `run_sdk_code`, `run_sdk_client`, or
`render_frameforge_yaml`:

```json
{
  "font_closure": "/workspace/fonts/book.fp",
  "font_generics": {"sans-serif": "Inter"}
}
```

You may leave `real_metrics` in the call; the closure has explicit precedence.

### Step 2: Use the same arguments for preflight fitting

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

## Verification

Confirm all three fields in the render result:

```text
metrics_mode == "closure"
diagnostics.metrics_mode == "closure"
font_closure.sha256 is a 64-character hexadecimal digest
```

Repeat in a new session. The page hashes and closure digest must match.

## Troubleshooting

- `input path is outside the allowed FRAMEFORGE_MCP_INPUT_ROOTS`: move the
  closure below an allowed root or update the operator configuration.
- `no face in the closure satisfies ...`: add the face/weight or correct
  `font_generics`. MCP closure mode is intentionally strict.
- `font closure does not exist`: use an absolute path or resolve the relative
  path from the client/document base directory, not the session output folder.
