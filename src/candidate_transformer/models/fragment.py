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

    # Grouping key used by the merge stage to cluster fragments into candidates
    # without comparing every fragment against every other (avoids O(n^2)).
    #
    # Contract: adapters MUST always set this — never leave it None.
    #   Strong key available  -> normalized email or E.164 phone (preferred)
    #   No strong key         -> SHA-256 hex of the adapter's raw record bytes
    #
    # This matches the spec's candidate_id fallback chain (email -> phone ->
    # content hash). A GitHub-only or notes-only fragment that carries no email
    # and no phone uses a content hash so it becomes its own single-source
    # candidate rather than being silently dropped or merged with unrelated
    # None-hint fragments.
    candidate_hint: str
