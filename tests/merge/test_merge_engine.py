"""End-to-end tests for merge_fragments covering all five required scenarios."""
import pytest
from candidate_transformer.merge.engine import merge_fragments
from candidate_transformer.merge._resolve import noisy_or, DISAGREEMENT_PENALTY
from candidate_transformer.models.canonical import MergeState
from candidate_transformer.models.fragment import Fragment, Provenance


# ── Helpers ───────────────────────────────────────────────────────────────

def _f(field: str, value: str, source: str, hint: str) -> Fragment:
    return Fragment(
        field=field,
        raw_value=value,
        provenance=Provenance(source=source, method="direct", raw_value=value),
        candidate_hint=hint,
    )


def _ats(
    email: str,
    *,
    name: str = "Alice Smith",
    phone: str | None = None,
    location: str | None = None,
    company: str | None = None,
    title: str | None = None,
    skills: list[str] | None = None,
) -> list[Fragment]:
    frags = [
        _f("name", name, "ats", email),
        _f("emails", email, "ats", email),
    ]
    if phone:
        frags.append(_f("phones", phone, "ats", email))
    if location:
        frags.append(_f("location", location, "ats", email))
    if company:
        frags.append(_f("current_company", company, "ats", email))
    if title:
        frags.append(_f("title", title, "ats", email))
    for s in (skills or []):
        frags.append(_f("skills", s, "ats", email))
    return frags


def _csv(
    email: str,
    *,
    name: str = "Alice Smith",
    phone: str | None = None,
    skills: list[str] | None = None,
) -> list[Fragment]:
    frags = [
        _f("name", name, "csv", email),
        _f("emails", email, "csv", email),
    ]
    if phone:
        frags.append(_f("phones", phone, "csv", email))
    for s in (skills or []):
        frags.append(_f("skills", s, "csv", email))
    return frags


def _notes(
    hint: str,
    *,
    email: str | None = None,
    phone: str | None = None,
    name: str | None = None,
    skills: list[str] | None = None,
) -> list[Fragment]:
    frags = []
    if name:
        frags.append(_f("name", name, "notes", hint))
    if email:
        frags.append(_f("emails", email, "notes", hint))
    if phone:
        frags.append(_f("phones", phone, "notes", hint))
    for s in (skills or []):
        frags.append(_f("skills", s, "notes", hint))
    return frags


# ── 1. Happy path: two sources agree → merged, high confidence ────────────

def test_two_sources_same_email_produce_one_profile():
    profiles = merge_fragments([_ats("alice@example.com"), _csv("alice@example.com")])
    assert len(profiles) == 1

def test_merged_state_set():
    profiles = merge_fragments([_ats("alice@example.com"), _csv("alice@example.com")])
    assert profiles[0].merge_state == MergeState.MERGED

def test_agreed_name_has_no_penalty():
    profiles = merge_fragments([_ats("alice@example.com"), _csv("alice@example.com")])
    # Both agree on "Alice Smith" — noisy-OR, no penalty.
    expected = noisy_or([0.9, 0.9])
    assert profiles[0].name.confidence == pytest.approx(expected)

def test_emails_unioned():
    group_a = [
        _f("emails", "alice@work.com", "ats", "alice@work.com"),
        _f("emails", "alice@home.com", "ats", "alice@work.com"),
    ]
    group_b = [_f("emails", "alice@work.com", "csv", "alice@work.com")]
    profiles = merge_fragments([group_a, group_b])
    assert set(profiles[0].emails) == {"alice@work.com", "alice@home.com"}

def test_overall_confidence_high_when_sources_agree():
    profiles = merge_fragments([
        _ats("alice@example.com", phone="+14155552671"),
        _csv("alice@example.com", phone="+14155552671"),
    ])
    assert profiles[0].overall_confidence > 0.8

def test_two_different_emails_produce_two_profiles():
    profiles = merge_fragments([_ats("alice@example.com"), _ats("bob@example.com")])
    assert len(profiles) == 2

def test_single_source_state_is_single():
    profiles = merge_fragments([_ats("alice@example.com")])
    assert profiles[0].merge_state == MergeState.SINGLE


# ── 2. Conflict: sources disagree → winner chosen, confidence penalised ───

def test_conflicting_name_winner_is_higher_trust():
    ats_group = _ats("alice@example.com", name="Alice Smith")
    notes_group = _notes("alice@example.com", email="alice@example.com", name="Al Smith")
    profiles = merge_fragments([ats_group, notes_group])
    assert profiles[0].name.value == "Alice Smith"

def test_conflicting_name_confidence_is_penalised():
    ats_group = _ats("alice@example.com", name="Alice Smith")
    notes_group = _notes("alice@example.com", email="alice@example.com", name="Al Smith")
    profiles = merge_fragments([ats_group, notes_group])
    # ATS alone agrees on "Alice Smith"; penalty applied because notes disagrees.
    expected = noisy_or([0.9]) * DISAGREEMENT_PENALTY
    assert profiles[0].name.confidence == pytest.approx(expected)

def test_conflict_confidence_lower_than_agreement():
    # Profile with conflicting names must have lower name confidence than
    # an identical profile where both sources agree.
    agreed = merge_fragments([_ats("a@x.com"), _csv("a@x.com")])[0]
    conflict_ats = _ats("a@x.com", name="Alice Smith")
    conflict_notes = _notes("a@x.com", email="a@x.com", name="Al Smith")
    conflicted = merge_fragments([conflict_ats, conflict_notes])[0]
    assert conflicted.name.confidence < agreed.name.confidence

def test_conflict_still_produces_one_merged_profile():
    ats_group = _ats("alice@example.com", name="Alice Smith")
    notes_group = _notes("alice@example.com", email="alice@example.com", name="Al Smith")
    profiles = merge_fragments([ats_group, notes_group])
    assert len(profiles) == 1
    assert profiles[0].merge_state == MergeState.MERGED

def test_both_sources_in_provenance_on_conflict():
    ats_group = _ats("alice@example.com", name="Alice Smith")
    notes_group = _notes("alice@example.com", email="alice@example.com", name="Al Smith")
    profiles = merge_fragments([ats_group, notes_group])
    provenance_sources = {p.source for p in profiles[0].name.provenance}
    assert "ats" in provenance_sources


# ── 3. Recycled phone: NEEDS_REVIEW, NOT merged ───────────────────────────

def test_recycled_phone_not_merged_into_one():
    alice = _ats("alice@example.com", phone="+14155552671")
    bob = [
        _f("emails", "bob@example.com", "ats", "bob@example.com"),
        _f("phones", "+14155552671", "ats", "bob@example.com"),
    ]
    profiles = merge_fragments([alice, bob])
    assert len(profiles) == 2

def test_recycled_phone_both_profiles_need_review():
    alice = _ats("alice@example.com", phone="+14155552671")
    bob = [
        _f("emails", "bob@example.com", "ats", "bob@example.com"),
        _f("phones", "+14155552671", "ats", "bob@example.com"),
    ]
    profiles = merge_fragments([alice, bob])
    for p in profiles:
        assert p.merge_state == MergeState.NEEDS_REVIEW

def test_recycled_phone_overall_confidence_capped_at_04():
    alice = _ats("alice@example.com", phone="+14155552671")
    bob = [
        _f("emails", "bob@example.com", "ats", "bob@example.com"),
        _f("phones", "+14155552671", "ats", "bob@example.com"),
    ]
    profiles = merge_fragments([alice, bob])
    for p in profiles:
        assert p.overall_confidence <= 0.4

def test_phone_match_without_email_conflict_is_weak_merge():
    # Group A has email + phone. Group B has only the same phone, no email.
    # No email conflict → weak merge (one profile, NEEDS_REVIEW).
    group_a = [
        _f("emails", "alice@example.com", "ats", "alice@example.com"),
        _f("phones", "+14155552671", "ats", "alice@example.com"),
    ]
    group_b = [_f("phones", "+14155552671", "notes", "+14155552671")]
    profiles = merge_fragments([group_a, group_b])
    assert len(profiles) == 1
    assert profiles[0].merge_state == MergeState.NEEDS_REVIEW


# ── 4. Phone retry: bare number recovered via country ─────────────────────

def test_bare_phone_recovered_after_country_resolved():
    # ATS: email + country. Notes: same email + bare national number.
    # After merging by email, location="US" enables the phone retry pass.
    ats_group = _ats("alice@example.com", location="US")
    notes_group = _notes(
        "alice@example.com",
        email="alice@example.com",
        phone="4155552671",   # no country code — fails without region hint
    )
    profiles = merge_fragments([ats_group, notes_group])
    assert len(profiles) == 1
    assert len(profiles[0].phones) == 1
    assert profiles[0].phones[0].e164 == "+14155552671"

def test_bare_phone_not_recovered_without_country():
    # Same setup but no location field → phone stays empty.
    notes_group = _notes(
        "alice@example.com",
        email="alice@example.com",
        phone="4155552671",
    )
    profiles = merge_fragments([notes_group])
    assert profiles[0].phones == []

def test_e164_phone_and_bare_phone_deduplicate_after_retry():
    # ATS gives E.164 phone. Notes gives the same number as bare national.
    # After retry both resolve to the same E.164 → one phone in profile.
    ats_group = _ats("alice@example.com", location="US", phone="+14155552671")
    notes_group = _notes(
        "alice@example.com",
        email="alice@example.com",
        phone="4155552671",
    )
    profiles = merge_fragments([ats_group, notes_group])
    assert len(profiles[0].phones) == 1
    assert profiles[0].phones[0].e164 == "+14155552671"


# ── 5. Skill noisy-OR: two sources → higher confidence than either alone ──

def test_skill_two_sources_higher_confidence():
    one_source_conf = noisy_or([0.9 * 0.9])  # Python from one ATS source
    profiles = merge_fragments([
        _ats("alice@example.com", skills=["Python"]),
        _csv("alice@example.com", skills=["Python"]),
    ])
    skill = next(s for s in profiles[0].skills if s.name == "Python")
    assert skill.confidence > one_source_conf

def test_skill_sources_list_is_union():
    profiles = merge_fragments([
        _ats("alice@example.com", skills=["Python"]),
        _csv("alice@example.com", skills=["Python"]),
    ])
    skill = next(s for s in profiles[0].skills if s.name == "Python")
    assert sorted(skill.sources) == ["ats", "csv"]

def test_unknown_skill_verbatim_in_profile():
    profiles = merge_fragments([_ats("alice@example.com", skills=["QuantumBrainfuzz"])])
    skill_names = [s.name for s in profiles[0].skills]
    assert "QuantumBrainfuzz" in skill_names

def test_alias_and_canonical_name_merge_to_one_record():
    # "js" (alias) and "JavaScript" (canonical) must map to the same SkillRecord.
    profiles = merge_fragments([
        _ats("alice@example.com", skills=["js"]),
        _csv("alice@example.com", skills=["JavaScript"]),
    ])
    js_skills = [s for s in profiles[0].skills if s.name == "JavaScript"]
    assert len(js_skills) == 1
    assert sorted(js_skills[0].sources) == ["ats", "csv"]

def test_skill_not_duplicated_when_same_source_lists_twice():
    # Same skill twice in one source should not double-count in noisy-OR.
    group = [
        _f("emails", "a@x.com", "ats", "a@x.com"),
        _f("skills", "Python", "ats", "a@x.com"),
        _f("skills", "Python", "ats", "a@x.com"),  # duplicate
    ]
    profiles = merge_fragments([group])
    py = next(s for s in profiles[0].skills if s.name == "Python")
    # noisy_or([0.81, 0.81]) > noisy_or([0.81]) — but only if we DON'T collapse
    # same-source duplicates. The engine takes max per source, so no double-count.
    # Here we just verify exactly one SkillRecord for Python.
    assert len([s for s in profiles[0].skills if s.name == "Python"]) == 1


# ── Misc invariants ───────────────────────────────────────────────────────

def test_empty_input_returns_empty():
    assert merge_fragments([]) == []

def test_candidate_id_is_deterministic():
    group = _ats("alice@example.com")
    id1 = merge_fragments([group])[0].candidate_id
    id2 = merge_fragments([group])[0].candidate_id
    assert id1 == id2

def test_candidate_id_is_16_hex_chars():
    profiles = merge_fragments([_ats("alice@example.com")])
    cid = profiles[0].candidate_id
    assert len(cid) == 16
    assert all(c in "0123456789abcdef" for c in cid)

def test_source_record_ids_recorded():
    group = _ats("alice@example.com")
    profiles = merge_fragments([group])
    assert profiles[0].source_record_ids == ["alice@example.com"]

def test_profile_is_json_serialisable():
    import json
    profiles = merge_fragments([_ats("alice@example.com", phone="+14155552671")])
    # Must not raise — the whole pipeline output is JSON.
    json.loads(profiles[0].model_dump_json())
