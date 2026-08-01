"""Collapse schema-validation noise into author-site root-cause groups."""
from __future__ import annotations

import re
from typing import Any

from frameforge_sdk.provenance import format_author_site

_GRADIENT_HELPERS = {
    "sdk.paint.linear_gradient",
    "sdk.paint.radial_gradient",
    "sdk.paint.conic_gradient",
}
_GRADIENT_HINT = (
    "gradient stops are (color, position) tuples or bare colors; "
    "a GradientStop-shaped dict is wrapped as a color value, not coerced"
)


def _pointer(loc: tuple[Any, ...] | list[Any]) -> str:
    if not loc:
        return ""
    def stable_part(part: Any) -> str:
        value = str(part)
        if value.startswith(("function-after[", "function-before[", "function-wrap[")):
            model_names = re.findall(r"\b[A-Z][A-Za-z0-9_]*\b", value)
            if model_names:
                value = model_names[-1]
        return value.replace("~", "~0").replace("/", "~1")

    return "/" + "/".join(stable_part(part) for part in loc)


def _pointer_parts(pointer: str) -> tuple[str | int, ...]:
    if not pointer:
        return ()
    parts: list[str | int] = []
    for encoded in pointer.lstrip("/").split("/"):
        value = encoded.replace("~1", "/").replace("~0", "~")
        parts.append(int(value) if value.isdigit() else value)
    return tuple(parts)


def _is_ordered_prefix(prefix: tuple[str | int, ...], loc: tuple[Any, ...]) -> bool:
    """Match raw-document paths through Pydantic's inserted union-arm labels."""
    if not prefix:
        return True
    index = 0
    for part in loc:
        if part == prefix[index]:
            index += 1
            if index == len(prefix):
                return True
    return False


def _nearest_site(
    loc: tuple[Any, ...], provenance: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    matches = [
        (_pointer_parts(prefix), site)
        for prefix, site in provenance.items()
        if _is_ordered_prefix(_pointer_parts(prefix), loc)
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: len(item[0]))[1]


def _message(via: str | None, loc: tuple[Any, ...], fallback: str) -> str:
    if via in _GRADIENT_HELPERS and "stops" in loc and "color" in loc:
        return "gradient stop color is not a string"
    return fallback


def _hint(via: str | None) -> str | None:
    if via in _GRADIENT_HELPERS:
        return _GRADIENT_HINT
    return None


def _fallback_key(loc: tuple[Any, ...], message: str) -> tuple[str, str]:
    named = [str(part) for part in loc if not isinstance(part, int)]
    leaf = named[-1] if named else "document"
    return leaf, message


def group_validation_errors(
    errors: list[dict[str, Any]],
    provenance: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return compact representative issues plus root-cause groups.

    Pydantic reports every union-arm mismatch. Errors with the same nearest
    author site and SDK helper are one actionable cause; only one representative
    remains under ``validation.issues`` while ``issues_total`` preserves the
    original count.
    """
    source_map = provenance or {}
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    order: list[tuple[Any, ...]] = []

    for error in errors:
        loc = tuple(error.get("loc", ()))
        path = _pointer(loc)
        fallback = str(error.get("msg", ""))
        site = _nearest_site(loc, source_map)
        via = str(site.get("via")) if site and site.get("via") else None
        if site:
            key = (
                site.get("file"),
                site.get("line"),
                site.get("function"),
                via,
            )
            rendered_site = format_author_site(site)
        else:
            key = ("unmapped", *_fallback_key(loc, fallback))
            rendered_site = "unknown authoring site"
        if key not in grouped:
            message = _message(via, loc, fallback)
            group: dict[str, Any] = {
                "site": rendered_site,
                "count": 0,
                "sample_path": path,
                "message": message,
            }
            hint = _hint(via)
            if hint:
                group["hint"] = hint
            grouped[key] = group
            order.append(key)
        grouped[key]["count"] += 1

    error_groups = [grouped[key] for key in order]
    representative_issues = [
        {
            "rule_id": "structure",
            "severity": "error",
            "path": group["sample_path"],
            "message": group["message"],
        }
        for group in error_groups
    ]
    return {
        "issues": representative_issues,
        "issues_total": len(errors),
        "groups_total": len(error_groups),
        "error_groups": error_groups,
    }


__all__ = ["group_validation_errors"]
