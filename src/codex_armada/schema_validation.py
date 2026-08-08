from __future__ import annotations

import re
from typing import Any


class SchemaValidationError(ValueError):
    """Raised when a value does not satisfy the supported JSON Schema subset."""


def validate_json_schema(value: Any, schema: dict[str, Any], *, path: str = "$") -> list[str]:
    """Validate the JSON Schema features used by Codex Armada's bundled contracts.

    The implementation deliberately supports a small, deterministic subset rather
    than pulling a runtime dependency: type, enum, required, properties,
    additionalProperties, items, min/max items, min/max length, pattern, and numeric
    minimum/maximum. Unknown keywords are ignored because the bundled schemas are
    validated at release time and use only this subset.
    """

    errors: list[str] = []
    _validate(value, schema, path, errors)
    return errors


def require_json_schema(value: Any, schema: dict[str, Any], *, path: str = "$") -> None:
    errors = validate_json_schema(value, schema, path=path)
    if errors:
        raise SchemaValidationError("; ".join(errors))


def _validate(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']!r}, observed {value!r}")
        return

    expected_type = schema.get("type")
    if expected_type is not None:
        accepted = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_matches_type(value, item) for item in accepted):
            errors.append(f"{path}: expected type {accepted!r}, observed {_type_name(value)}")
            return

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            properties = {}
        for key, child in value.items():
            child_path = f"{path}.{key}"
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                _validate(child, child_schema, child_path, errors)
                continue
            additional = schema.get("additionalProperties", True)
            if additional is False:
                errors.append(f"{path}: unexpected property {key!r}")
            elif isinstance(additional, dict):
                _validate(child, additional, child_path, errors)

    if isinstance(value, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"{path}: expected at least {minimum} items, observed {len(value)}")
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append(f"{path}: expected at most {maximum} items, observed {len(value)}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate(item, item_schema, f"{path}[{index}]", errors)

    if isinstance(value, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"{path}: expected length >= {minimum}, observed {len(value)}")
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append(f"{path}: expected length <= {maximum}, observed {len(value)}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                matched = re.search(pattern, value) is not None
            except re.error as exc:
                errors.append(f"{path}: invalid bundled schema pattern {pattern!r}: {exc}")
            else:
                if not matched:
                    errors.append(f"{path}: value does not match {pattern!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{path}: expected >= {minimum}, observed {value}")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"{path}: expected <= {maximum}, observed {value}")


def _matches_type(value: Any, expected: Any) -> bool:
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return type(value).__name__
