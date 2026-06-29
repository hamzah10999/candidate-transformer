from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator


class FieldType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"


class OnMissing(str, Enum):
    NULL = "null"    # write null for the key in the output
    OMIT = "omit"    # drop the key entirely
    ERROR = "error"  # raise a validation error before returning


class NormalizeAs(str, Enum):
    """Render formats available to the projection layer.

    CANONICAL is a no-op — skill names are already canonicalized by the
    normalizer pipeline. It is accepted here so configs can be explicit.
    """
    E164 = "e164"
    NATIONAL = "national"
    ISO3166 = "iso3166"
    YYYY_MM = "yyyy-mm"
    YYYY = "yyyy"
    CANONICAL = "canonical"


class FieldSpec(BaseModel):
    """Describes one field in the projected output document."""
    path: str
    from_path: str = Field(alias="from", default="")
    type: FieldType = FieldType.STRING
    required: bool = False
    normalize: NormalizeAs | None = None

    model_config = {"populate_by_name": True}

    @field_validator("type", mode="before")
    @classmethod
    def _coerce_type(cls, v: object) -> object:
        # Accept "string[]" (assignment spec shorthand) as ARRAY.
        if isinstance(v, str) and v.endswith("[]"):
            return "array"
        return v

    @field_validator("normalize", mode="before")
    @classmethod
    def _coerce_normalize(cls, v: object) -> object:
        # Accept "E164", "National", etc. — case-insensitive.
        if isinstance(v, str):
            return v.lower()
        return v


class GlobalConfig(BaseModel):
    include_confidence: bool = True
    include_provenance: bool = False
    on_missing: OnMissing = OnMissing.NULL


class ProjectionConfig(BaseModel):
    """The full runtime config document, loaded from JSON and validated by Pydantic.

    Accepts two equivalent shapes so both the nested form used internally and
    the flat form from the assignment spec parse correctly:

      Nested (internal):                 Flat (assignment spec):
      {                                  {
        "fields": [...],                   "fields": [...],
        "globals": {                       "include_confidence": true,
          "include_confidence": true,      "on_missing": "null"
          "on_missing": "null"           }
        }
      }
    """
    fields: list[FieldSpec]
    globals: GlobalConfig = Field(default_factory=GlobalConfig)

    @model_validator(mode="before")
    @classmethod
    def _absorb_flat_globals(cls, data: object) -> object:
        # If include_confidence / on_missing / include_provenance appear at the
        # top level (flat spec format), fold them into a "globals" dict.
        if not isinstance(data, dict):
            return data
        flat_keys = {"include_confidence", "include_provenance", "on_missing"}
        flat = {k: data[k] for k in flat_keys if k in data}
        if flat and "globals" not in data:
            data = {k: v for k, v in data.items() if k not in flat_keys}
            data["globals"] = flat
        return data
