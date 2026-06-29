from __future__ import annotations
from typing import Any

import jsonschema
import phonenumbers

from ..models.canonical import CandidateProfile, FieldValue, ParsedPhone
from ..models.config import FieldType, NormalizeAs, OnMissing, ProjectionConfig
from ._paths import FIELD_VALUE_FIELDS, MissingFieldError, resolve_path
from ._schema import derive_schema


class ProjectionError(Exception):
    """on_missing=error and a required field is absent."""


class ProjectionValidationError(Exception):
    """The projected dict failed the config-derived JSON schema."""


def project(profile: CandidateProfile, config: ProjectionConfig) -> dict:
    """Project a canonical CandidateProfile into an output dict.

    This is a read-only transform: the canonical record is never mutated.

    For each FieldSpec:
      1. Resolve from_path against the profile (see _paths.py for syntax).
      2. Apply normalize override if present — possible only because the
         canonical record stores parsed objects (ParsedPhone components,
         not a formatted string), so any render format is lossless.
      3. Handle missing value per on_missing policy (null / omit / error).
      4. Optionally attach _confidence and _provenance for FieldValue fields.
      5. Validate the complete output against the config-derived JSON schema.
    """
    on_missing = config.globals.on_missing
    include_conf = config.globals.include_confidence
    include_prov = config.globals.include_provenance

    output: dict = {}

    for spec in config.fields:
        # If from_path is omitted, treat path as the field name.
        from_path = spec.from_path or spec.path

        try:
            value = resolve_path(profile, from_path)
        except MissingFieldError:
            value = None

        # Missing / None value handling
        if value is None:
            if on_missing == OnMissing.ERROR:
                raise ProjectionError(
                    f"Field {spec.path!r} resolved from {from_path!r} is missing "
                    f"and on_missing=error"
                )
            if on_missing == OnMissing.OMIT:
                continue
            output[spec.path] = None
            continue

        # Normalize override — renders the canonical parsed object differently.
        if spec.normalize is not None:
            value = _apply_normalize(value, spec.normalize)

        output[spec.path] = value

        # Confidence / provenance attachment for FieldValue-backed fields.
        # List fields (emails, phones, skills) don't have a single FieldValue,
        # so we skip attachment for them rather than silently attaching garbage.
        if (include_conf or include_prov) and from_path in FIELD_VALUE_FIELDS:
            fv: FieldValue | None = getattr(profile, from_path, None)
            if isinstance(fv, FieldValue):
                if include_conf:
                    output[f"{spec.path}_confidence"] = fv.confidence
                if include_prov:
                    output[f"{spec.path}_provenance"] = [
                        {"source": p.source, "method": p.method}
                        for p in fv.provenance
                    ]

    # Derive a JSON schema from the config and validate before returning.
    # This catches mismatches between what the config declares and what was
    # actually produced (e.g. a required field that came out null).
    schema = derive_schema(config)
    try:
        jsonschema.validate(output, schema)
    except jsonschema.ValidationError as exc:
        raise ProjectionValidationError(exc.message) from exc

    return output


def _apply_normalize(value: Any, normalize: NormalizeAs) -> Any:
    """Render a canonical parsed value in the format requested by the config.

    The canonical record stores ParsedPhone as structured components — this is
    why we can render NATIONAL format here even though the default is E.164.
    If the value isn't the expected type (e.g. already a string), it passes through.
    """
    if isinstance(value, ParsedPhone):
        if normalize == NormalizeAs.E164:
            return value.e164
        if normalize == NormalizeAs.NATIONAL:
            # Re-parse from E.164 so libphonenumber can format with country context.
            parsed = phonenumbers.parse(value.e164)
            return phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.NATIONAL
            )
    return value
