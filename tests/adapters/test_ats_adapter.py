import json
import pytest
from candidate_transformer.adapters.ats_adapter import extract_ats
from candidate_transformer.adapters._hint import content_hint

VALID_RECORD = {
    "candidate_name": "Alice Smith",
    "contact_email": "alice@example.com",
    "contact_phone": "+14155552671",
    "employer": "Acme Corp",
    "position": "Senior Engineer",
    "country": "US",
    "summary": "Experienced engineer.",
    "profile_url": "https://github.com/alice",
    "tags": ["Python", "AWS", "Docker"],
}

VALID_JSON = json.dumps([VALID_RECORD])
SINGLE_OBJECT_JSON = json.dumps(VALID_RECORD)  # object, not array


# --- Failure / edge-case paths ---

def test_malformed_json_returns_empty():
    assert extract_ats("{not valid json") == []

def test_wrong_root_type_returns_empty():
    # A bare string at root is not a candidate record
    assert extract_ats('"just a string"') == []

def test_empty_string_returns_empty():
    assert extract_ats("") == []

def test_record_with_no_email_no_phone_uses_content_hash():
    record = {"candidate_name": "Ghost Person", "employer": "Unknown Co"}
    groups = extract_ats(json.dumps([record]))
    assert len(groups) == 1
    hint = groups[0][0].candidate_hint
    assert len(hint) == 64  # SHA-256 hex

def test_content_hash_salted_differently_from_csv():
    record = {"candidate_name": "Ghost Person", "employer": "Unknown Co"}
    raw = json.dumps(record, sort_keys=True)
    hint_ats = content_hint("ats", raw)
    hint_csv = content_hint("csv", raw)
    assert hint_ats != hint_csv

def test_non_dict_record_in_array_skipped():
    data = json.dumps([VALID_RECORD, "not a record", VALID_RECORD])
    groups = extract_ats(data)
    # The two valid records come through; the string is skipped
    assert len(groups) == 2

def test_missing_ats_field_omitted_not_null():
    # A record with no "summary" must not emit a bio fragment with None value
    record = {k: v for k, v in VALID_RECORD.items() if k != "summary"}
    groups = extract_ats(json.dumps([record]))
    bio_frags = [f for f in groups[0] if f.field == "bio"]
    assert bio_frags == []


# --- Correctness ---

def test_single_object_at_root_accepted():
    # ATS sometimes returns one object, not an array
    groups = extract_ats(SINGLE_OBJECT_JSON)
    assert len(groups) == 1

def test_field_name_mapping():
    groups = extract_ats(VALID_JSON)
    alice = groups[0]
    fields = {f.field for f in alice}
    assert "name" in fields          # from candidate_name
    assert "emails" in fields        # from contact_email
    assert "phones" in fields        # from contact_phone
    assert "current_company" in fields  # from employer
    assert "title" in fields         # from position
    assert "location" in fields      # from country
    assert "bio" in fields           # from summary
    assert "github_url" in fields    # from profile_url

def test_tags_become_skill_fragments():
    groups = extract_ats(VALID_JSON)
    skill_frags = [f for f in groups[0] if f.field == "skills"]
    skill_values = {f.raw_value for f in skill_frags}
    assert skill_values == {"Python", "AWS", "Docker"}

def test_email_is_candidate_hint():
    groups = extract_ats(VALID_JSON)
    hints = {f.candidate_hint for f in groups[0]}
    assert hints == {"alice@example.com"}

def test_all_fragments_share_one_hint():
    groups = extract_ats(VALID_JSON)
    for group in groups:
        assert len({f.candidate_hint for f in group}) == 1

def test_provenance_source_is_ats():
    groups = extract_ats(VALID_JSON)
    for frag in groups[0]:
        assert frag.provenance.source == "ats"

def test_email_stored_lowercase():
    record = dict(VALID_RECORD, contact_email="Alice@EXAMPLE.COM")
    groups = extract_ats(json.dumps([record]))
    email_frag = next(f for f in groups[0] if f.field == "emails")
    assert email_frag.raw_value == "alice@example.com"

def test_adapter_does_not_normalize_phone():
    groups = extract_ats(VALID_JSON)
    phone_frag = next(f for f in groups[0] if f.field == "phones")
    assert phone_frag.raw_value == "+14155552671"  # unchanged
