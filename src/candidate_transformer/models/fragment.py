from __future__ import annotations
from typing import Any
from pydantic import BaseModel


class Provenance(BaseModel):
    """Records exactly where one value came from — attached to every fragment and
    every field in the canonical record."""
    source: str       # "csv" | "ats" | "github" | "notes"
    method: str       # "direct" | "regex" | "api_field" | "inferred"
    raw_value: str | None = None  # the original string before any normalization


class Fragment(BaseModel):
    """One raw field value emitted by a single adapter.

    Adapters produce fragments and nothing else — they never normalize values
    or try to figure out which candidate a fragment belongs to. That work
    happens in later pipeline stages.
    """
    field: str           # canonical field name this value targets, e.g. "emails"
    raw_value: Any       # exactly what the adapter read — str, list, dict, etc.
    provenance: Provenance

    # The adapter sets this when it can: the raw email or phone it saw.
    # The merge stage uses it to group fragments into candidate clusters
    # without comparing all pairs.
    candidate_hint: str | None = None
