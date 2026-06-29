import pytest
from candidate_transformer.adapters.csv_adapter import extract_csv
from candidate_transformer.adapters._hint import content_hint


VALID_CSV = """\
name,email,phone,current_company,title
Alice Smith,alice@example.com,+14155552671,Acme Corp,Engineer
Bob Jones,bob@work.com,,Globex,Manager
"""

NO_EMAIL_NO_PHONE_CSV = """\
name,email,phone,current_company,title
Charlie Anon,,,SomeCo,Analyst
"""

EMPTY_CSV = "name,email,phone,current_company,title\n"

MALFORMED_CSV = "this is not, csv at all\nwithout proper headers\n"


# --- Failure / edge-case paths ---

def test_empty_content_returns_empty():
    assert extract_csv("") == []

def test_header_only_no_rows_returns_empty():
    assert extract_csv(EMPTY_CSV) == []

def test_row_with_no_email_no_phone_uses_content_hash():
    groups = extract_csv(NO_EMAIL_NO_PHONE_CSV)
    assert len(groups) == 1
    hint = groups[0][0].candidate_hint
    # Must be a 64-char hex SHA-256, not empty
    assert len(hint) == 64
    assert all(c in "0123456789abcdef" for c in hint)

def test_hint_is_salted_with_source_name():
    # Two different sources with identical raw text must produce different hints.
    raw = "Charlie Anon"
    hint_csv = content_hint("csv", raw)
    hint_notes = content_hint("notes", raw)
    assert hint_csv != hint_notes

def test_missing_column_skipped_gracefully():
    # CSV with only name and email — phone/company/title columns absent
    csv_no_phone = "name,email\nDana,dana@x.com\n"
    groups = extract_csv(csv_no_phone)
    assert len(groups) == 1
    fields = {f.field for f in groups[0]}
    assert "phones" not in fields
    assert "name" in fields
    assert "emails" in fields


# --- Correctness ---

def test_two_rows_produce_two_groups():
    groups = extract_csv(VALID_CSV)
    assert len(groups) == 2

def test_email_becomes_hint_and_emails_fragment():
    groups = extract_csv(VALID_CSV)
    alice = groups[0]
    hints = {f.candidate_hint for f in alice}
    assert hints == {"alice@example.com"}
    email_frags = [f for f in alice if f.field == "emails"]
    assert len(email_frags) == 1
    assert email_frags[0].raw_value == "alice@example.com"

def test_phone_becomes_hint_when_email_absent():
    csv = "name,email,phone\nNoEmail,,+14155550000\n"
    groups = extract_csv(csv)
    assert groups[0][0].candidate_hint == "+14155550000"

def test_all_five_canonical_fields_emitted():
    groups = extract_csv(VALID_CSV)
    alice_fields = {f.field for f in groups[0]}
    assert alice_fields == {"name", "emails", "phones", "current_company", "title"}

def test_provenance_source_is_csv():
    groups = extract_csv(VALID_CSV)
    for frag in groups[0]:
        assert frag.provenance.source == "csv"
        assert frag.provenance.method == "direct"

def test_all_fragments_in_group_share_same_hint():
    groups = extract_csv(VALID_CSV)
    for group in groups:
        hints = {f.candidate_hint for f in group}
        assert len(hints) == 1, "all fragments in a group must share one hint"

def test_adapters_never_normalize_phone():
    # The raw value must be stored as-is, not converted to E.164.
    # Normalisation is the normalizer's job, not the adapter's.
    groups = extract_csv(VALID_CSV)
    phone_frag = next(f for f in groups[0] if f.field == "phones")
    assert phone_frag.raw_value == "+14155552671"  # unchanged from CSV
