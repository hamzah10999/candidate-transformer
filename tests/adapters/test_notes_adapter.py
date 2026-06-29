import pytest
from candidate_transformer.adapters.notes_adapter import extract_notes
from candidate_transformer.adapters._hint import content_hint

FULL_NOTES = """\
Candidate: Alice Smith
Email: alice@example.com
Phone: +14155552671
Title: Senior Engineer
Company: Acme Corp
Skills: Python, AWS, some-unknown-framework
Strong communicator. Recommended for final round.
"""

EMAIL_ONLY_NOTES = """\
Name: Bob Jones
Email: bob@work.com
Good background in backend systems.
"""

NO_EMAIL_NO_PHONE_NOTES = """\
Name: Ghost Person
They seemed strong but left no contact info.
"""


# --- Failure / edge-case paths ---

def test_empty_file_returns_empty():
    assert extract_notes("") == []

def test_whitespace_only_returns_empty():
    assert extract_notes("   \n\n  ") == []

def test_no_email_no_phone_uses_content_hash():
    groups = extract_notes(NO_EMAIL_NO_PHONE_NOTES)
    assert len(groups) == 1
    hint = groups[0][0].candidate_hint
    assert len(hint) == 64

def test_content_hash_salted_with_source():
    # Same raw text from notes vs csv must produce different hints.
    text = NO_EMAIL_NO_PHONE_NOTES
    hint_notes = content_hint("notes", text)
    hint_csv = content_hint("csv", text)
    assert hint_notes != hint_csv

def test_unknown_skill_extracted_verbatim():
    # "some-unknown-framework" is not in the alias map.
    # The adapter must still emit it — the normalizer handles confidence later.
    groups = extract_notes(FULL_NOTES)
    skill_values = {f.raw_value for f in groups[0] if f.field == "skills"}
    assert "some-unknown-framework" in skill_values

def test_notes_with_no_labelled_fields_returns_empty_group():
    # Pure prose, no structured fields at all → no fragments → empty list.
    groups = extract_notes("This candidate was interesting but I forgot everything.")
    assert groups == []

def test_only_first_phone_emitted():
    # Multiple phone patterns in the text — only the first is emitted to avoid
    # noise (company numbers, references, etc.).
    notes = "Email: x@x.com\nPhone: +14155550001\nAlternate: +14155550002\n"
    groups = extract_notes(notes)
    phone_frags = [f for f in groups[0] if f.field == "phones"]
    assert len(phone_frags) == 1
    assert phone_frags[0].raw_value == "+14155550001"


# --- Correctness ---

def test_full_notes_emits_expected_fields():
    groups = extract_notes(FULL_NOTES)
    assert len(groups) == 1
    fields = {f.field for f in groups[0]}
    assert {"name", "emails", "phones", "title", "current_company", "skills"}.issubset(fields)

def test_email_is_hint():
    groups = extract_notes(FULL_NOTES)
    hints = {f.candidate_hint for f in groups[0]}
    assert hints == {"alice@example.com"}

def test_skills_comma_split():
    groups = extract_notes(FULL_NOTES)
    skill_values = {f.raw_value for f in groups[0] if f.field == "skills"}
    assert "Python" in skill_values
    assert "AWS" in skill_values
    assert "some-unknown-framework" in skill_values

def test_provenance_method_is_regex():
    groups = extract_notes(FULL_NOTES)
    for frag in groups[0]:
        assert frag.provenance.source == "notes"
        assert frag.provenance.method == "regex"

def test_all_fragments_share_one_hint():
    groups = extract_notes(FULL_NOTES)
    for group in groups:
        assert len({f.candidate_hint for f in group}) == 1

def test_email_only_notes_no_phone_fragment():
    groups = extract_notes(EMAIL_ONLY_NOTES)
    phone_frags = [f for f in groups[0] if f.field == "phones"]
    assert phone_frags == []

def test_name_label_variants():
    for label in ("Candidate: Eve\nEmail: e@e.com", "Name: Eve\nEmail: e@e.com"):
        groups = extract_notes(label)
        name_frags = [f for f in groups[0] if f.field == "name"]
        assert len(name_frags) == 1
        assert name_frags[0].raw_value == "Eve"
