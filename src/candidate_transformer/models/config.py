from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field


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
    These can differ from the canonical default — e.g. you can request
    NATIONAL when the canonical record stores E.164. That's only possible
    because the canonical record is lossless (it stores the full parsed object)."""
    E164 = "e164"
    NATIONAL = "national"
    ISO3166 = "iso3166"
    YYYY_MM = "yyyy-mm"
    YYYY = "yyyy"


class FieldSpec(BaseModel):
    """Describes one field in the projected output document."""
    path: str                   # key name in the output, e.g. "phone_number"
    from_path: str = Field(      # path into the canonical record, e.g. "phones[0].e164"
        alias="from", default=""
    )
    type: FieldType = FieldType.STRING
    required: bool = False
    normalize: NormalizeAs | None = None  # optional render override

    model_config = {"populate_by_name": True}


class GlobalConfig(BaseModel):
    include_confidence: bool = True
    include_provenance: bool = False
    on_missing: OnMissing = OnMissing.NULL


class ProjectionConfig(BaseModel):
    """The full runtime config document, loaded from JSON and validated by Pydantic.
    The engine reads this to decide what to emit; the canonical record is untouched."""
    fields: list[FieldSpec]
    globals: GlobalConfig = Field(default_factory=GlobalConfig)
