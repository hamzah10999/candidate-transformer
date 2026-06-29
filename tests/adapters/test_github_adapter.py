import json
import pytest
from candidate_transformer.adapters.github_adapter import extract_github
from candidate_transformer.adapters._hint import content_hint

VALID_PROFILE = {
    "login": "alicesmith",
    "name": "Alice Smith",
    "email": "alice@example.com",
    "bio": "Software engineer @ Acme.",
    "location": "San Francisco, CA, USA",
    "html_url": "https://github.com/alicesmith",
    "repos": [
        {"name": "backend", "language": "Python"},
        {"name": "frontend", "language": "JavaScript"},
        {"name": "infra", "language": "Python"},   # duplicate language
    ],
}

NO_EMAIL_PROFILE = {
    "login": "ghost99",
    "name": "Ghost",
    "bio": "I exist.",
    "html_url": "https://github.com/ghost99",
    "repos": [],
}


# --- Failure / edge-case paths ---

def test_malformed_json_returns_empty():
    assert extract_github("{broken") == []

def test_empty_string_returns_empty():
    assert extract_github("") == []

def test_no_email_falls_back_to_login_hash():
    groups = extract_github(json.dumps(NO_EMAIL_PROFILE))
    assert len(groups) == 1
    hint = groups[0][0].candidate_hint
    expected = content_hint("github", "ghost99")
    assert hint == expected

def test_login_hash_differs_from_notes_hash_for_same_text():
    # Salt test: same login string from different sources must not collide.
    hint_gh = content_hint("github", "ghost99")
    hint_notes = content_hint("notes", "ghost99")
    assert hint_gh != hint_notes

def test_duplicate_language_emitted_only_once():
    # "Python" appears in two repos — only one skill fragment should come out.
    groups = extract_github(json.dumps(VALID_PROFILE))
    skill_frags = [f for f in groups[0] if f.field == "skills"]
    skill_values = [f.raw_value for f in skill_frags]
    assert skill_values.count("Python") == 1

def test_repo_with_null_language_skipped():
    profile = dict(VALID_PROFILE, repos=[{"name": "misc", "language": None}])
    groups = extract_github(json.dumps(profile))
    skill_frags = [f for f in groups[0] if f.field == "skills"]
    assert skill_frags == []

def test_non_dict_profile_in_array_skipped():
    data = json.dumps([VALID_PROFILE, "not a profile"])
    groups = extract_github(data)
    assert len(groups) == 1


# --- Correctness ---

def test_single_profile_object_accepted():
    groups = extract_github(json.dumps(VALID_PROFILE))
    assert len(groups) == 1

def test_all_expected_fields_emitted():
    groups = extract_github(json.dumps(VALID_PROFILE))
    fields = {f.field for f in groups[0]}
    assert {"name", "emails", "bio", "location", "github_url", "skills"}.issubset(fields)

def test_email_is_hint():
    groups = extract_github(json.dumps(VALID_PROFILE))
    hints = {f.candidate_hint for f in groups[0]}
    assert hints == {"alice@example.com"}

def test_skill_language_order_stable():
    # Fixture output must be deterministic — same JSON always produces same order.
    groups1 = extract_github(json.dumps(VALID_PROFILE))
    groups2 = extract_github(json.dumps(VALID_PROFILE))
    skills1 = [f.raw_value for f in groups1[0] if f.field == "skills"]
    skills2 = [f.raw_value for f in groups2[0] if f.field == "skills"]
    assert skills1 == skills2

def test_provenance_method_is_api_field():
    groups = extract_github(json.dumps(VALID_PROFILE))
    for frag in groups[0]:
        assert frag.provenance.source == "github"
        assert frag.provenance.method == "api_field"

def test_all_fragments_share_one_hint():
    groups = extract_github(json.dumps(VALID_PROFILE))
    for group in groups:
        assert len({f.candidate_hint for f in group}) == 1
