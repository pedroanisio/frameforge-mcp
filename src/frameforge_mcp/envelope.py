"""The shared shape of every tool result — declared once, published, and enforced.

Input validation in this server was always thorough: every tool parameter
carries ``Annotated[..., Field(description=...)]``, so an agent is told what to
send and pydantic rejects what is wrong. The other direction had nothing. Tools
returned ``dict[str, Any]``; the transport hand-built ``structuredContent``; no
``outputSchema`` was published. A caller had no machine-readable account of what
would come back, and a malformed result would have shipped silently.

This module is the missing half. :class:`ToolEnvelope` states the keys every
tool guarantees, FastMCP publishes its JSON Schema as each tool's
``outputSchema``, and — because the schema is wired together with an output
*model* — FastMCP validates the ``structuredContent`` of every call against it
before the result leaves the server.

The contract is deliberately narrow. ``ok`` is the only required key, because it
is the only one every tool can honestly promise; the rest of a result is
tool-specific and passes through untouched (``extra="allow"``). A wider contract
would be a more impressive schema and a false one.

Writing this down is what exposed the defect fixed alongside it: two tools
returned no ``ok`` at all, so the one key the whole surface branches on was
missing from exactly the two tools the README tells an agent to call first.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ToolEnvelope(BaseModel):
    """The keys every FrameForge MCP tool result carries.

    ``extra="allow"`` is load-bearing, not laziness: each tool's real payload
    (``families``, ``spatial``, ``validation``, ``design``, ...) rides on the
    same object, and a contract that dropped it would make the published schema
    actively misleading about what the caller receives.
    """

    model_config = ConfigDict(extra="allow")

    ok: bool = Field(
        # Strict on purpose. Pydantic's lax mode reads the string "yes" as True,
        # which would let a tool that built its envelope wrongly pass validation
        # and report success — the exact silent mis-shape this contract exists
        # to catch. Every producer in this package sets a real bool.
        strict=True,
        description=(
            "Whether the call succeeded. Branch on this before reading anything else: "
            "an expected failure (missing optional lane, bad path, document that will "
            "not validate) is reported as ok=false with a structured reason, never as "
            "a raised exception."
        )
    )
    error: str | None = Field(
        default=None,
        description="Human-readable failure reason. Present when ok is false.",
    )
    error_type: str | None = Field(
        default=None,
        description="Exception class name behind the failure (e.g. 'FileNotFoundError').",
    )
    hint: str | None = Field(
        default=None,
        description=(
            "An actionable next step for this specific failure — the install command "
            "for an uninstalled lane, the tool that lists valid inputs, or the "
            "pagination argument that brings an over-budget result into range."
        ),
    )
    renders: list[dict[str, Any]] | None = Field(
        default=None,
        description="Rendered pages: page number, resource URI, mimeType, sha256, path.",
    )
    resources: list[dict[str, Any]] | None = Field(
        default=None,
        description="MCP resource links to the artifacts this call wrote to the session.",
    )


#: The published JSON Schema — served as each tool's ``outputSchema`` and through
#: ``describe_capabilities(topic='envelope')`` for clients that do not surface one.
ENVELOPE_SCHEMA: dict[str, Any] = ToolEnvelope.model_json_schema()


def validate_envelope(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    """Check *result* against the contract, naming *tool* when it does not fit.

    Raises ``ValueError`` rather than returning a verdict: a result that breaks
    the shared shape is a server bug, and the failure mode of tolerating it is a
    client that silently reads ``undefined`` where it expected ``ok``. The tool
    name is in the message because a bare pydantic traceback out of a 35-tool
    surface does not say which tool is at fault.
    """
    try:
        ToolEnvelope.model_validate(result)
    except ValidationError as exc:
        raise ValueError(
            f"{tool} returned a result that does not satisfy the tool-result "
            f"contract (frameforge_mcp.envelope.ToolEnvelope): {exc}"
        ) from exc
    return result


def envelope_report() -> dict[str, Any]:
    """The contract as a discovery payload for ``describe_capabilities``."""
    return {
        "schema": "frameforge_mcp.envelope.v1",
        "note": (
            "Every tool but get_guide (which returns prose) resolves to this shape. "
            "`ok` is the only guaranteed key; tool-specific keys ride alongside it."
        ),
        "json_schema": ENVELOPE_SCHEMA,
    }


__all__ = ["ENVELOPE_SCHEMA", "ToolEnvelope", "envelope_report", "validate_envelope"]
