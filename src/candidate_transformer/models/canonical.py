from __future__ import annotations
from enum import Enum
from typing import Generic, TypeVar
from pydantic import BaseModel, Field

from .fragment import Provenance

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Parsed value types
# The spec says: store parsed, structured values — NOT formatted strings —
# so projection can render any format without re-parsing or information loss.
# ---------------------------------------------------------------------------

class ParsedPhone(BaseModel):
    """Output of libphonenumber, kept structured so we can render E.164,
    national, or any other format in the projection layer."""
    e164: str            # "+14155552671"  — canonical render
    country_code: int    # ITU calling code, e.g. 1 for US
    national_number: int # 4155552671


class ParsedDate(BaseModel):
    """Year is always present when the date is known.
    Month and day stay None rather than being invented."""
    year: int
    month: int | None = None   # 1–12
    day: int | None = None     # 1–31


class DateRange(BaseModel):
    start: ParsedDate
    end: ParsedDate | None = None  # None encodes "Present"


class SkillRecord(BaseModel):
    """One skill entry after merging across all sources by canonical name.
    sources[] is a union of every source that mentioned this skill;
    confidence is combined by noisy-OR so two agreeing sources beat one strong one."""
    name: str                    # canonical form, e.g. "JavaScript"
    sources: list[str]           # e.g. ["csv", "github"]
    confidence: float            # 0.0–1.0
    provenance: list[Provenance] = []


# ---------------------------------------------------------------------------
# FieldValue — the confidence+provenance wrapper for every scalar field
# ---------------------------------------------------------------------------

class FieldValue(BaseModel, Generic[T]):
    """Wraps a canonical scalar with its confidence score and the provenance
    chain that produced it. Generic so the type checker enforces
    FieldValue[str] vs FieldValue[ParsedPhone] etc."""
    value: T | None = None
    confidence: float = 0.0        # 0.0–1.0
    provenance: list[Provenance] = []


# ---------------------------------------------------------------------------
# Merge state
# ---------------------------------------------------------------------------

class MergeState(str, Enum):
    SINGLE = "single"              # only one source contributed
    MERGED = "merged"              # confident multi-source merge
    NEEDS_REVIEW = "needs_review"  # weak link (e.g. recycled phone) — held back


# ---------------------------------------------------------------------------
# CandidateProfile — the canonical record built once, projected later
# ---------------------------------------------------------------------------

class CandidateProfile(BaseModel):
    """One canonical record per person.

    All values are structured and parsed. The projection layer renders them
    into whatever shape the config requests — the engine never touches this
    record during projection.
    """
    # Deterministic hash: email → phone → content hash (same inputs → same id)
    candidate_id: str

    # Core identity (these four fields feed overall_confidence)
    name: FieldValue[str] = Field(default_factory=FieldValue)
    emails: list[str] = []          # lowercase-normalized, deduped
    phones: list[ParsedPhone] = []  # parsed, deduped by e164

    # Professional fields
    current_company: FieldValue[str] = Field(default_factory=FieldValue)
    title: FieldValue[str] = Field(default_factory=FieldValue)
    location: FieldValue[str] = Field(default_factory=FieldValue)  # ISO-3166 alpha-2

    # Unstructured / enrichment
    bio: FieldValue[str] = Field(default_factory=FieldValue)
    github_url: FieldValue[str] = Field(default_factory=FieldValue)
    skills: list[SkillRecord] = []

    # Merge metadata
    merge_state: MergeState = MergeState.SINGLE
    source_record_ids: list[str] = []  # IDs of every source record merged here

    # mean of name/email/phone confidence (spec also notes min as a conservative alt.)
    overall_confidence: float = 0.0
