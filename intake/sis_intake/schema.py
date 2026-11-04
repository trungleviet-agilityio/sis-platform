"""Interpreter for a fixed subset of JSON Schema 2020-12 (stdlib only).

Supported validation keywords: type, enum, const, required, properties,
additionalProperties, minProperties, items, pattern, minimum, maximum, minItems, and $ref to a
local "#/$defs/<name>". Annotation and structural keywords ($schema, $id, $defs, title,
description) are accepted. Anything else makes check_schema_keywords report a problem.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

VALIDATION_KEYWORDS = frozenset(
    {
        "type",
        "enum",
        "const",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "pattern",
        "minimum",
        "maximum",
        "minItems",
        "minProperties",
        "$ref",
    }
)
ANNOTATION_KEYWORDS = frozenset({"$schema", "$id", "$defs", "title", "description"})
SUPPORTED_KEYWORDS = VALIDATION_KEYWORDS | ANNOTATION_KEYWORDS


class SchemaIssue(NamedTuple):
    path: str
    message: str


def check_schema_keywords(schema: Any, path: str = "") -> list[str]:
    """Return one problem string per keyword outside the supported subset."""
    problems: list[str] = []
    if not isinstance(schema, dict):
        return problems
    for key, value in schema.items():
        where = path + "/" + key if path else "/" + key
        if key not in SUPPORTED_KEYWORDS:
            problems.append("{}: unsupported keyword {!r}".format(path or "/", key))
        elif key in ("properties", "$defs") and isinstance(value, dict):
            for name, sub in value.items():
                problems.extend(check_schema_keywords(sub, where + "/" + name))
        elif key in ("items", "additionalProperties"):
            problems.extend(check_schema_keywords(value, where))
    return problems


def _type_ok(value: Any, name: str) -> bool:
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    if name == "null":
        return value is None
    raise ValueError(f"unsupported type {name!r}")


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    return type(value).__name__


def _same(a: Any, b: Any) -> bool:
    """JSON equality: True is not 1."""
    return isinstance(a, bool) == isinstance(b, bool) and a == b


def _pattern_search(pattern: str, value: str) -> re.Match[str] | None:
    # ECMA 262 `$` matches only at the very end; Python's also matches before a final newline.
    if pattern.endswith("$") and not pattern.endswith("\\$"):
        pattern = pattern[:-1] + r"\Z"
    return re.search(pattern, value)


def _join(path: str, key: str) -> str:
    return path + "." + key if path else key


def _resolve(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    prefix = "#/$defs/"
    if not ref.startswith(prefix):
        raise ValueError(f"unsupported $ref {ref!r} (only local #/$defs/<name>)")
    target = root.get("$defs", {}).get(ref[len(prefix) :])
    if not isinstance(target, dict):
        raise ValueError(f"unresolved $ref {ref!r}")
    return target


def _check(
    value: Any, schema: dict[str, Any], root: dict[str, Any], path: str, out: list[SchemaIssue]
) -> None:
    if "$ref" in schema:
        _check(value, _resolve(schema["$ref"], root), root, path, out)
    if "type" in schema and not _type_ok(value, schema["type"]):
        out.append(
            SchemaIssue(path, "expected {}, got {}".format(schema["type"], _type_name(value)))
        )
        return
    if "enum" in schema and not any(_same(value, option) for option in schema["enum"]):
        out.append(SchemaIssue(path, "must be one of {}, got {!r}".format(schema["enum"], value)))
    if "const" in schema and not _same(value, schema["const"]):
        out.append(SchemaIssue(path, "must be {!r}, got {!r}".format(schema["const"], value)))
    if (
        isinstance(value, str)
        and "pattern" in schema
        and _pattern_search(schema["pattern"], value) is None
    ):
        out.append(
            SchemaIssue(path, "{!r} does not match pattern {}".format(value, schema["pattern"]))
        )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(
                SchemaIssue(path, "{!r} is below the minimum {!r}".format(value, schema["minimum"]))
            )
        if "maximum" in schema and value > schema["maximum"]:
            out.append(
                SchemaIssue(path, "{!r} is above the maximum {!r}".format(value, schema["maximum"]))
            )
    if isinstance(value, dict):
        _check_object(value, schema, root, path, out)
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append(SchemaIssue(path, f"needs at least {schema['minItems']} item(s)"))
        if "items" in schema:
            for index, item in enumerate(value):
                _check(item, schema["items"], root, f"{path}[{index}]", out)


def _check_object(
    value: dict[str, Any],
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
    out: list[SchemaIssue],
) -> None:
    if "minProperties" in schema and len(value) < schema["minProperties"]:
        out.append(SchemaIssue(path, f"needs at least {schema['minProperties']} key(s)"))
    for key in schema.get("required", []):
        if key not in value:
            out.append(SchemaIssue(path, f"missing required key '{key}'"))
    props = schema.get("properties", {})
    extra = schema.get("additionalProperties", True)
    for key, item in value.items():
        if key in props:
            _check(item, props[key], root, _join(path, key), out)
        elif extra is False:
            out.append(SchemaIssue(_join(path, key), f"unknown key '{key}'"))
        elif isinstance(extra, dict):
            _check(item, extra, root, _join(path, key), out)


def validate(instance: Any, schema: dict[str, Any]) -> list[SchemaIssue]:
    """Validate instance against schema (the root, for $ref). Returns the issues found."""
    out: list[SchemaIssue] = []
    _check(instance, schema, schema, "", out)
    return out
