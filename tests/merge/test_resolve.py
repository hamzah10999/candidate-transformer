"""Unit tests for the resolve helpers and noisy-OR math."""
import pytest
from candidate_transformer.merge._resolve import (
    DISAGREEMENT_PENALTY,
    SOURCE_TRUST,
    email_confidence,
    noisy_or,
    phone_confidence,
    resolve_emails,
    resolve_phones,
    resolve_scalar,
    resolve_skills,
)
from candidate_transformer.models.fragment import Fragment, Provenance


def _f(field: str, value: str, source: str) -> Fragment:
    return Fragment(
        field=field,
        raw_value=value,
        provenance=Provenance(source=source, method="direct", raw_value=value),
        candidate_hint="hint@example.com",
    )


# ── noisy_or ─────────────────────────────────────────────────────────────

def test_noisy_or_empty():
    assert noisy_or([]) == pytest.approx(0.0)

def test_noisy_or_single():
    assert noisy_or([0.9]) == pytest.approx(0.9)

def test_noisy_or_two_identical():
    assert noisy_or([0.9, 0.9]) == pytest.approx(1 - 0.01)

def test_noisy_or_two_beats_one():
    assert noisy_or([0.9, 0.9]) > noisy_or([0.9])

def test_noisy_or_zero_contributes_nothing():
    assert noisy_or([0.0, 0.9]) == pytest.approx(noisy_or([0.9]))


# ── resolve_scalar: happy path ────────────────────────────────────────────

def test_single_source_returns_that_value():
    fv = resolve_scalar([_f("name", "Alice Smith", "ats")])
    assert fv.value == "Alice Smith"
    assert fv.confidence == pytest.approx(SOURCE_TRUST["ats"])

def test_two_sources_agree_no_penalty():
    frags = [_f("name", "Alice Smith", "ats"), _f("name", "Alice Smith", "csv")]
    fv = resolve_scalar(frags)
    assert fv.value == "Alice Smith"
    expected = noisy_or([0.9, 0.9])
    assert fv.confidence == pytest.approx(expected)

def test_agreement_is_case_insensitive():
    # "alice smith" and "Alice Smith" are the same value — should not trigger penalty.
    frags = [_f("name", "Alice Smith", "ats"), _f("name", "alice smith", "csv")]
    fv = resolve_scalar(frags)
    assert fv.confidence == pytest.approx(noisy_or([0.9, 0.9]))

def test_casing_preserved_from_highest_trust_fragment():
    frags = [_f("name", "Alice Smith", "ats"), _f("name", "alice smith", "notes")]
    fv = resolve_scalar(frags)
    # Both agree (case-insensitive) so no penalty; ATS value preferred.
    assert fv.value == "Alice Smith"

def test_empty_fragments_returns_null():
    fv = resolve_scalar([])
    assert fv.value is None
    assert fv.confidence == 0.0


# ── resolve_scalar: conflict ──────────────────────────────────────────────

def test_conflict_applies_disagreement_penalty():
    frags = [_f("name", "Alice Smith", "ats"), _f("name", "Al Smith", "notes")]
    fv = resolve_scalar(frags)
    # ATS wins, but penalty applied because notes disagrees.
    expected = noisy_or([0.9]) * DISAGREEMENT_PENALTY
    assert fv.confidence == pytest.approx(expected)

def test_conflict_winner_is_higher_trust():
    frags = [_f("name", "Alice Smith", "ats"), _f("name", "Al Smith", "notes")]
    fv = resolve_scalar(frags)
    assert fv.value == "Alice Smith"

def test_conflict_winner_is_higher_count_on_trust_tie():
    # Two notes fragments agree on "alice" vs one notes fragment says "ali".
    frags = [
        _f("name", "alice", "notes"),
        _f("name", "alice", "notes"),
        _f("name", "ali", "notes"),
    ]
    fv = resolve_scalar(frags)
    assert fv.value == "alice"  # more agreeing fragments wins the tie


# ── resolve_phones: retry pass ────────────────────────────────────────────

def test_e164_phone_resolves_without_region():
    phones = resolve_phones([_f("phones", "+14155552671", "ats")])
    assert len(phones) == 1
    assert phones[0].e164 == "+14155552671"

def test_bare_national_fails_without_region():
    phones = resolve_phones([_f("phones", "4155552671", "notes")])
    assert phones == []

def test_bare_national_recovered_with_region():
    # The phone retry pass: country from another source enables recovery.
    phones = resolve_phones([_f("phones", "4155552671", "notes")], resolved_country="US")
    assert len(phones) == 1
    assert phones[0].e164 == "+14155552671"

def test_duplicate_phones_deduped_by_e164():
    frags = [_f("phones", "+14155552671", "ats"), _f("phones", "+14155552671", "csv")]
    phones = resolve_phones(frags)
    assert len(phones) == 1

def test_garbage_phone_produces_no_output():
    phones = resolve_phones([_f("phones", "not-a-phone", "notes")])
    assert phones == []


# ── resolve_skills ────────────────────────────────────────────────────────

def test_known_skill_alias_resolved():
    records = resolve_skills([_f("skills", "js", "ats")])
    assert records[0].name == "JavaScript"

def test_known_skill_confidence():
    # norm_conf=0.9 × source_trust=0.9 → noisy_or([0.81])
    records = resolve_skills([_f("skills", "Python", "ats")])
    assert records[0].confidence == pytest.approx(noisy_or([0.9 * 0.9]))

def test_same_skill_two_sources_higher_than_one():
    frags = [_f("skills", "Python", "ats"), _f("skills", "python", "csv")]
    records = resolve_skills(frags)
    one_source = noisy_or([0.9 * 0.9])
    assert records[0].confidence > one_source

def test_same_skill_sources_unioned():
    frags = [_f("skills", "Python", "ats"), _f("skills", "python", "github")]
    records = resolve_skills(frags)
    assert len(records) == 1
    assert sorted(records[0].sources) == ["ats", "github"]

def test_unknown_skill_kept_verbatim():
    records = resolve_skills([_f("skills", "QuantumBrainfuzz", "ats")])
    assert records[0].name == "QuantumBrainfuzz"
    # verbatim (0.5) × ats trust (0.9) = 0.45
    assert records[0].confidence == pytest.approx(noisy_or([0.5 * 0.9]))

def test_unknown_skill_two_sources_beats_one():
    frags = [_f("skills", "QuantumBrainfuzz", "ats"), _f("skills", "QuantumBrainfuzz", "csv")]
    records = resolve_skills(frags)
    one_conf = noisy_or([0.5 * 0.9])
    assert records[0].confidence > one_conf
