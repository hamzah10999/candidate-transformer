from __future__ import annotations
from collections import defaultdict

from ..models.canonical import FieldValue, ParsedPhone, SkillRecord
from ..models.fragment import Fragment
from ..normalizers.phone import normalize_phone
from ..normalizers.skill import normalize_skill

# Trust assigned to each source. ATS and CSV are treated as equally authoritative;
# GitHub is enrichment; notes are the least reliable (human free-text).
SOURCE_TRUST: dict[str, float] = {
    "ats": 0.9,
    "csv": 0.9,
    "github": 0.7,
    "notes": 0.5,
}

DISAGREEMENT_PENALTY: float = 0.8

# Stable priority for tie-breaking: lower index = preferred when trust is equal.
_TRUST_PRIORITY: list[str] = ["ats", "csv", "github", "notes"]


def noisy_or(trust_values: list[float]) -> float:
    """Combine independent evidence: conf = 1 − Π(1 − trust_i).

    Two agreeing sources at 0.9 each beat a single source at 0.9 because
    conf = 1 − (0.1)(0.1) = 0.99 > 0.9. An empty list returns 0.0.
    """
    product = 1.0
    for t in trust_values:
        product *= 1.0 - t
    return round(1.0 - product, 6)


def resolve_scalar(fragments: list[Fragment]) -> FieldValue[str]:
    """Resolve a scalar field to the winning value, with confidence and provenance.

    Agreement: fragments whose values are identical case-insensitively are
    treated as corroborating evidence and combined via noisy-OR.

    Disagreement: if multiple distinct values exist, the highest-trust group
    wins and a DISAGREEMENT_PENALTY is applied to the winner's confidence —
    a contested value is never reported as certain.

    Tie-breaking among groups with equal max trust: prefer the group with
    more fragments, then the group whose best source appears earliest in
    _TRUST_PRIORITY (stable, deterministic).
    """
    if not fragments:
        return FieldValue()

    # Group by lowercased value so "Alice Smith" and "alice smith" are treated
    # as the same value for the purpose of agreement detection.
    groups: dict[str, list[Fragment]] = defaultdict(list)
    for f in fragments:
        key = str(f.raw_value).strip().lower()
        groups[key].append(f)

    def _score(key: str) -> tuple[float, int, int]:
        frags = groups[key]
        max_trust = max(SOURCE_TRUST.get(f.provenance.source, 0.0) for f in frags)
        count = len(frags)
        best_priority = min(
            _TRUST_PRIORITY.index(f.provenance.source)
            if f.provenance.source in _TRUST_PRIORITY else 99
            for f in frags
        )
        # Negate priority so a lower index (= higher priority) sorts higher.
        return (max_trust, count, -best_priority)

    winner_key = max(groups, key=_score)
    winner_frags = groups[winner_key]

    # Preserve the original casing from the highest-trust fragment.
    best_frag = max(
        winner_frags,
        key=lambda f: SOURCE_TRUST.get(f.provenance.source, 0.0),
    )

    confidence = noisy_or([
        SOURCE_TRUST.get(f.provenance.source, 0.0) for f in winner_frags
    ])

    # Apply penalty when at least one source disagrees.
    if len(groups) > 1:
        confidence = round(confidence * DISAGREEMENT_PENALTY, 6)

    return FieldValue(
        value=str(best_frag.raw_value).strip(),
        confidence=confidence,
        provenance=[f.provenance for f in winner_frags],
    )


def resolve_emails(fragments: list[Fragment]) -> list[str]:
    """Union + dedup email fragments, preserving first-seen order.

    Emails are already lowercase from the adapters. List fields use union
    rather than winner-takes-all because the canonical profile can hold
    multiple contact addresses.
    """
    seen: set[str] = set()
    result: list[str] = []
    for f in fragments:
        val = str(f.raw_value).strip().lower()
        if val and val not in seen:
            seen.add(val)
            result.append(val)
    return result


def resolve_phones(
    fragments: list[Fragment],
    resolved_country: str | None = None,
) -> list[ParsedPhone]:
    """Normalise phone fragments to ParsedPhone objects, deduped by E.164.

    STEP-4 phone retry (cross-source reasoning pass):
    A fragment that returns (None, "unparseable") on the first attempt is
    retried with region=resolved_country if one is available. This lets a
    bare national number from notes ("4155552671") be recovered when ATS
    supplies the country ("US"). The retry is only safe because the country
    came from a different, independent source — not invented.
    """
    seen_e164: set[str] = set()
    result: list[ParsedPhone] = []

    for f in fragments:
        raw = str(f.raw_value).strip()
        parsed, _ = normalize_phone(raw)

        if parsed is None and resolved_country:
            # Cross-source retry with the resolved country as a region hint.
            parsed, _ = normalize_phone(raw, region=resolved_country)

        if parsed and parsed.e164 not in seen_e164:
            seen_e164.add(parsed.e164)
            result.append(parsed)

    return result


def resolve_skills(fragments: list[Fragment]) -> list[SkillRecord]:
    """Merge skill fragments by canonical name, combining confidence via noisy-OR.

    Per-source contribution = normalizer_confidence × source_trust, so:
    - Known skill (norm_conf=0.9) from ATS (trust=0.9)  → contributes 0.81
    - Unknown verbatim (norm_conf=0.5) from notes (trust=0.5) → contributes 0.25

    noisy-OR across all sources means corroboration always raises confidence,
    even for unknown verbatim skills.
    """
    # canonical_name → {source: (max_contribution, [provenance_objects])}
    groups: dict[str, dict[str, tuple[float, list]]] = {}

    for f in fragments:
        name, norm_conf, _ = normalize_skill(str(f.raw_value))
        src = f.provenance.source
        trust = SOURCE_TRUST.get(src, 0.0)
        contribution = norm_conf * trust

        if name not in groups:
            groups[name] = {}
        if src not in groups[name]:
            groups[name][src] = (contribution, [f.provenance])
        else:
            prev_contrib, prev_provs = groups[name][src]
            groups[name][src] = (
                max(prev_contrib, contribution),
                prev_provs + [f.provenance],
            )

    records: list[SkillRecord] = []
    for name, src_map in groups.items():
        contributions = [v[0] for v in src_map.values()]
        confidence = noisy_or(contributions)
        all_provenance = [p for _, (_, provs) in src_map.items() for p in provs]
        records.append(SkillRecord(
            name=name,
            sources=sorted(src_map.keys()),
            confidence=round(confidence, 6),
            provenance=all_provenance,
        ))

    # Highest confidence first; name as secondary key for stability.
    records.sort(key=lambda r: (-r.confidence, r.name))
    return records


def email_confidence(email_fragments: list[Fragment]) -> float:
    """Confidence that we know at least one correct email address.

    Uses the noisy-OR of the sources that agree on the most-corroborated email.
    """
    if not email_fragments:
        return 0.0
    by_email: dict[str, list[str]] = defaultdict(list)
    for f in email_fragments:
        by_email[str(f.raw_value).strip().lower()].append(f.provenance.source)
    best_sources = max(by_email.values(), key=len)
    return noisy_or([SOURCE_TRUST.get(s, 0.0) for s in best_sources])


def phone_confidence(
    phone_fragments: list[Fragment],
    resolved_country: str | None = None,
) -> float:
    """Confidence that we know at least one correct phone number (after retry)."""
    if not phone_fragments:
        return 0.0
    by_e164: dict[str, list[str]] = defaultdict(list)
    for f in phone_fragments:
        raw = str(f.raw_value).strip()
        parsed, _ = normalize_phone(raw)
        if parsed is None and resolved_country:
            parsed, _ = normalize_phone(raw, region=resolved_country)
        if parsed:
            by_e164[parsed.e164].append(f.provenance.source)
    if not by_e164:
        return 0.0
    best_sources = max(by_e164.values(), key=len)
    return noisy_or([SOURCE_TRUST.get(s, 0.0) for s in best_sources])
