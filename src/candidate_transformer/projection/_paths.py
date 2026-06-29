from __future__ import annotations
import inspect
import re
from typing import Any

from ..models.canonical import CandidateProfile, FieldValue

_INDEX_RE = re.compile(r'^(\w+)\[(\d+)\](.*)$')
_WILDCARD_RE = re.compile(r'^(\w+)\[\](.*)$')


def _is_field_value(ann: Any) -> bool:
    # Pydantic v2 evaluates FieldValue[str] into a concrete parametrized class,
    # so get_origin() returns None. issubclass is the correct check.
    return inspect.isclass(ann) and issubclass(ann, FieldValue)


# Derived at import time from CandidateProfile.model_fields so it stays in
# sync automatically when new FieldValue fields are added to the model.
FIELD_VALUE_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in CandidateProfile.model_fields.items()
    if _is_field_value(field.annotation)
)


class MissingFieldError(Exception):
    """Raised when an indexed or dotted path cannot be resolved."""


def resolve_path(obj: Any, path: str) -> Any:
    """Navigate a CandidateProfile (or any nested object) with a path expression.

    Supported forms:
        "name"             – simple field; FieldValue is unwrapped to .value
        "emails[0]"        – index into a list
        "phones[0].e164"   – index then attribute
        "skills[].name"    – wildcard: returns [item.name for item in skills]

    Raises MissingFieldError for out-of-range indices.
    Returns None for absent attributes (not an error — caller handles on_missing).
    """
    path = path.lstrip('.')
    if not path:
        return obj

    # Wildcard: "skills[].name" → list comprehension
    m = _WILDCARD_RE.match(path)
    if m:
        field, rest = m.group(1), m.group(2).lstrip('.')
        collection = _attr(obj, field)
        if not isinstance(collection, (list, tuple)):
            return []
        if not rest:
            return list(collection)
        return [resolve_path(item, rest) for item in collection]

    # Indexed: "emails[0]" or "phones[0].e164"
    m = _INDEX_RE.match(path)
    if m:
        field, index, rest = m.group(1), int(m.group(2)), m.group(3).lstrip('.')
        collection = _attr(obj, field)
        if not isinstance(collection, (list, tuple)):
            raise MissingFieldError(path)
        if index >= len(collection):
            raise MissingFieldError(path)
        item = collection[index]
        return resolve_path(item, rest) if rest else item

    # Simple or dotted: "name" or "phones[0].country_code" remainder
    dot = path.find('.')
    if dot == -1:
        return _field(obj, path)
    field, rest = path[:dot], path[dot + 1:]
    child = _field(obj, field)
    if child is None:
        raise MissingFieldError(field)
    return resolve_path(child, rest)


def _attr(obj: Any, name: str) -> Any:
    """Get attribute or dict key without unwrapping FieldValue."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _field(obj: Any, name: str) -> Any:
    """Get a field, automatically unwrapping FieldValue → .value."""
    val = _attr(obj, name)
    if isinstance(val, FieldValue):
        return val.value
    return val
