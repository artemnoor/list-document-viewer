from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ReferenceResolutionError(ValueError):
    pass


def pointer_tokens(pointer: str) -> list[str]:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ReferenceResolutionError("Reference must be an absolute JSON Pointer")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def resolve_pointer(document: Any, pointer: str) -> Any:
    value = document
    for token in pointer_tokens(pointer):
        if isinstance(value, list):
            try:
                index = int(token)
                value = value[index]
            except (ValueError, IndexError) as exc:
                raise ReferenceResolutionError(f"Array index {token!r} does not resolve") from exc
        elif isinstance(value, dict) and token in value:
            value = value[token]
        else:
            raise ReferenceResolutionError(f"JSON Pointer token {token!r} does not resolve")
    return value


def parent_pointer(pointer: str) -> str:
    pointer_tokens(pointer)
    return pointer.rsplit("/", 1)[0]


def get_value_container(document: dict[str, Any], value_pointer: str) -> dict[str, Any] | None:
    """Return the Extraction field wrapper that owns a /value leaf."""
    tokens = pointer_tokens(value_pointer)
    if not tokens or tokens[-1] != "value":
        return None
    try:
        container = resolve_pointer(document, parent_pointer(value_pointer))
    except ReferenceResolutionError:
        return None
    return container if isinstance(container, dict) else None


@dataclass(frozen=True)
class ExtractedReference:
    value: Any
    container: dict[str, Any] | None
    raw_value: Any
    provenance: dict[str, Any] | None
    status: str | None


def resolve_extracted_reference(document: dict[str, Any], value_pointer: str) -> ExtractedReference:
    value = resolve_pointer(document, value_pointer)
    container = get_value_container(document, value_pointer)
    if container is None:
        return ExtractedReference(value, None, value, None, None)
    return ExtractedReference(
        value=value,
        container=container,
        raw_value=container.get("source_value"),
        provenance=container.get("provenance") if isinstance(container.get("provenance"), dict) else None,
        status=container.get("status"),
    )


def sibling_unit(document: dict[str, Any], value_pointer: str) -> str | None:
    tokens = pointer_tokens(value_pointer)
    if len(tokens) < 4 or tokens[0] != "line_items" or not tokens[1].isdigit():
        return None
    row_pointer = "/line_items/" + tokens[1]
    try:
        row = resolve_pointer(document, row_pointer)
    except ReferenceResolutionError:
        return None
    if not isinstance(row, dict):
        return None
    unit = row.get("unit")
    if isinstance(unit, dict):
        unit = unit.get("value")
    return str(unit) if unit is not None else None


def row_id_for_pointer(document: dict[str, Any], value_pointer: str) -> str | None:
    tokens = pointer_tokens(value_pointer)
    if len(tokens) < 3 or tokens[0] != "line_items" or not tokens[1].isdigit():
        return None
    try:
        row = resolve_pointer(document, f"/line_items/{tokens[1]}")
    except ReferenceResolutionError:
        return None
    return row.get("row_id") if isinstance(row, dict) else None
