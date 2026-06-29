"""Tests for the projection engine: path resolution, normalise, on_missing, schema."""
import inspect
import json
import pytest

from candidate_transformer.models.canonical import (
    CandidateProfile,
    FieldValue,
    MergeState,
    ParsedPhone,
    SkillRecord,
)
from candidate_transformer.models.config import (
    FieldSpec,
    FieldType,
    GlobalConfig,
    NormalizeAs,
    OnMissing,
    ProjectionConfig,
)
from candidate_transformer.models.fragment import Provenance
from candidate_transformer.projection.engine import (
    ProjectionError,
    ProjectionValidationError,
    project,
)
from candidate_transformer.projection._paths import (
    FIELD_VALUE_FIELDS,
    MissingFieldError,
    resolve_path,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

def _prov(source: str = "ats") -> Provenance:
    return Provenance(source=source, method="direct", raw_value="raw")


def _profile(
    name: str = "Alice Smith",
    emails: list[str] | None = None,
    phones: list[ParsedPhone] | None = None,
    location: str | None = "US",
    skills: list[SkillRecord] | None = None,
    company: str | None = "Acme Corp",
) -> CandidateProfile:
    return CandidateProfile(
        candidate_id="abc123",
        name=FieldValue(value=name, confidence=0.9, provenance=[_prov()]),
        emails=emails or ["alice@example.com"],
        phones=phones or [ParsedPhone(e164="+14155552671", country_code=1, national_number=4155552671)],
        current_company=FieldValue(value=company, confidence=0.8, provenance=[_prov()]),
        title=FieldValue(value="Engineer", confidence=0.75, provenance=[_prov()]),
        location=FieldValue(value=location, confidence=0.6, provenance=[_prov()]),
        skills=skills if skills is not None else [
            SkillRecord(name="Python", sources=["ats", "csv"], confidence=0.95),
            SkillRecord(name="SomeFramework", sources=["notes"], confidence=0.25),
        ],
        merge_state=MergeState.MERGED,
        overall_confidence=0.85,
    )


def _config(
    fields: list[dict],
    *,
    include_confidence: bool = False,
    include_provenance: bool = False,
    on_missing: str = "null",
) -> ProjectionConfig:
    return ProjectionConfig.model_validate({
        "fields": fields,
        "globals": {
            "include_confidence": include_confidence,
            "include_provenance": include_provenance,
            "on_missing": on_missing,
        },
    })


# ── FIELD_VALUE_FIELDS sync check ────────────────────────────────────────

def test_field_value_fields_matches_canonical_model():
    """FIELD_VALUE_FIELDS must equal every FieldValue-typed field on CandidateProfile.

    This test re-derives the expected set independently so that a bug in the
    derivation logic itself (wrong base class, wrong model) will cause a failure
    here rather than silently dropping _confidence/_provenance in production.
    If a new FieldValue field is added to CandidateProfile and the derivation
    is broken, this test catches it immediately.
    """
    expected = frozenset(
        name
        for name, field in CandidateProfile.model_fields.items()
        if inspect.isclass(field.annotation) and issubclass(field.annotation, FieldValue)
    )
    assert FIELD_VALUE_FIELDS == expected, (
        f"FIELD_VALUE_FIELDS is out of sync with CandidateProfile.\n"
        f"  Present in FIELD_VALUE_FIELDS but not in model : {FIELD_VALUE_FIELDS - expected}\n"
        f"  Present in model but missing from FIELD_VALUE_FIELDS: {expected - FIELD_VALUE_FIELDS}"
    )


# ── Path resolution unit tests ────────────────────────────────────────────

def test_simple_field_unwraps_field_value():
    p = _profile()
    assert resolve_path(p, "name") == "Alice Smith"

def test_indexed_email():
    p = _profile(emails=["alice@example.com", "a@work.com"])
    assert resolve_path(p, "emails[0]") == "alice@example.com"
    assert resolve_path(p, "emails[1]") == "a@work.com"

def test_indexed_out_of_range_raises():
    p = _profile(emails=["alice@example.com"])
    with pytest.raises(MissingFieldError):
        resolve_path(p, "emails[5]")

def test_indexed_phone_attribute():
    p = _profile()
    assert resolve_path(p, "phones[0].e164") == "+14155552671"
    assert resolve_path(p, "phones[0].country_code") == 1

def test_wildcard_skills_name():
    p = _profile()
    names = resolve_path(p, "skills[].name")
    assert names == ["Python", "SomeFramework"]

def test_wildcard_skills_confidence():
    p = _profile()
    confs = resolve_path(p, "skills[].confidence")
    assert confs[0] == pytest.approx(0.95)

def test_wildcard_on_empty_list():
    p = _profile(skills=[])
    assert resolve_path(p, "skills[].name") == []

def test_simple_scalar_field():
    p = _profile()
    assert resolve_path(p, "overall_confidence") == pytest.approx(0.85)


# ── Projection: happy path ────────────────────────────────────────────────

def test_simple_fields_projected():
    cfg = _config([
        {"path": "full_name", "from": "name"},
        {"path": "email", "from": "emails[0]"},
    ])
    out = project(_profile(), cfg)
    assert out["full_name"] == "Alice Smith"
    assert out["email"] == "alice@example.com"

def test_wildcard_produces_list():
    cfg = _config([{"path": "skill_names", "from": "skills[].name", "type": "array"}])
    out = project(_profile(), cfg)
    assert out["skill_names"] == ["Python", "SomeFramework"]

def test_from_path_defaults_to_path_key():
    # When "from" is omitted, the engine uses "path" as the field name.
    cfg = _config([{"path": "name"}])
    out = project(_profile(), cfg)
    assert out["name"] == "Alice Smith"


# ── Normalize overrides ───────────────────────────────────────────────────

def test_normalize_e164_on_parsed_phone():
    cfg = _config([{"path": "phone", "from": "phones[0]", "normalize": "e164"}])
    out = project(_profile(), cfg)
    assert out["phone"] == "+14155552671"

def test_normalize_national_on_parsed_phone():
    # The canonical record stores ParsedPhone components — this is the only
    # reason NATIONAL format is possible here without re-running the normalizer.
    cfg = _config([{"path": "phone", "from": "phones[0]", "normalize": "national"}])
    out = project(_profile(), cfg)
    assert out["phone"] == "(415) 555-2671"

def test_normalize_does_not_change_string_field():
    # Applying e164 to a non-phone field passes the value through unchanged.
    cfg = _config([{"path": "loc", "from": "location", "normalize": "e164"}])
    out = project(_profile(), cfg)
    assert out["loc"] == "US"


# ── on_missing ────────────────────────────────────────────────────────────

def test_on_missing_null_produces_none():
    cfg = _config(
        [{"path": "bio", "from": "bio"}],
        on_missing="null",
    )
    p = CandidateProfile(candidate_id="x", overall_confidence=0.0)
    out = project(p, cfg)
    assert "bio" in out
    assert out["bio"] is None

def test_on_missing_omit_drops_key():
    cfg = _config(
        [{"path": "bio", "from": "bio"}],
        on_missing="omit",
    )
    p = CandidateProfile(candidate_id="x", overall_confidence=0.0)
    out = project(p, cfg)
    assert "bio" not in out

def test_on_missing_error_raises():
    cfg = _config(
        [{"path": "bio", "from": "bio"}],
        on_missing="error",
    )
    p = CandidateProfile(candidate_id="x", overall_confidence=0.0)
    with pytest.raises(ProjectionError):
        project(p, cfg)

def test_out_of_range_index_treated_as_missing():
    # emails[9] on a profile with one email → on_missing applies.
    cfg = _config([{"path": "second_email", "from": "emails[9]"}], on_missing="null")
    out = project(_profile(), cfg)
    assert out["second_email"] is None


# ── include_confidence / include_provenance ───────────────────────────────

def test_include_confidence_attaches_to_field_value_fields():
    cfg = _config(
        [{"path": "full_name", "from": "name"}],
        include_confidence=True,
    )
    out = project(_profile(), cfg)
    assert "full_name_confidence" in out
    assert out["full_name_confidence"] == pytest.approx(0.9)

def test_include_confidence_not_attached_to_list_fields():
    # emails is list[str], not FieldValue — no _confidence attachment.
    cfg = _config(
        [{"path": "email", "from": "emails[0]"}],
        include_confidence=True,
    )
    out = project(_profile(), cfg)
    assert "email_confidence" not in out

def test_include_provenance_attaches_source_and_method():
    cfg = _config(
        [{"path": "full_name", "from": "name"}],
        include_provenance=True,
    )
    out = project(_profile(), cfg)
    assert "full_name_provenance" in out
    assert out["full_name_provenance"][0]["source"] == "ats"

def test_both_flags_attach_both_keys():
    cfg = _config(
        [{"path": "full_name", "from": "name"}],
        include_confidence=True,
        include_provenance=True,
    )
    out = project(_profile(), cfg)
    assert "full_name_confidence" in out
    assert "full_name_provenance" in out


# ── Schema validation ─────────────────────────────────────────────────────

def test_required_field_present_passes_validation():
    cfg = _config([{"path": "full_name", "from": "name", "required": True}])
    out = project(_profile(), cfg)
    assert out["full_name"] == "Alice Smith"

def test_required_field_missing_raises_validation_error():
    # "bio" is empty on this profile; required=True should fail schema validation.
    cfg = ProjectionConfig.model_validate({
        "fields": [{"path": "bio", "required": True, "type": "string"}],
        "globals": {"on_missing": "null"},
    })
    p = CandidateProfile(candidate_id="x", overall_confidence=0.0)
    with pytest.raises(ProjectionValidationError):
        project(p, cfg)

def test_output_is_valid_json():
    cfg = _config([
        {"path": "full_name", "from": "name"},
        {"path": "email", "from": "emails[0]"},
        {"path": "skills", "from": "skills[].name", "type": "array"},
        {"path": "phone", "from": "phones[0]", "normalize": "e164"},
    ])
    out = project(_profile(), cfg)
    serialised = json.dumps(out)
    restored = json.loads(serialised)
    assert restored["full_name"] == "Alice Smith"
    assert restored["phone"] == "+14155552671"
    assert "Python" in restored["skills"]


# ── CLI integration smoke test ────────────────────────────────────────────

def test_cli_end_to_end(tmp_path):
    """Run the full pipeline via main() using temp files."""
    import json as _json
    from candidate_transformer.__main__ import main

    # Minimal ATS JSON source
    ats = tmp_path / "ats.json"
    ats.write_text(_json.dumps([{
        "candidate_name": "Alice Smith",
        "contact_email": "alice@example.com",
        "contact_phone": "+14155552671",
        "employer": "Acme Corp",
        "position": "Engineer",
        "country": "US",
        "tags": ["Python", "AWS"],
    }]))

    # Minimal config
    cfg = tmp_path / "config.json"
    cfg.write_text(_json.dumps({
        "fields": [
            {"path": "full_name", "from": "name"},
            {"path": "email", "from": "emails[0]"},
            {"path": "phone", "from": "phones[0]", "normalize": "e164"},
            {"path": "skills", "from": "skills[].name", "type": "array"},
        ],
        "globals": {
            "include_confidence": False,
            "on_missing": "null",
        },
    }))

    out = tmp_path / "output" / "result.json"
    rc = main([
        "--sources", str(ats),
        "--config", str(cfg),
        "--output", str(out),
    ])
    assert rc == 0
    assert out.exists()
    results = _json.loads(out.read_text())
    assert len(results) == 1
    assert results[0]["full_name"] == "Alice Smith"
    assert results[0]["email"] == "alice@example.com"
    assert results[0]["phone"] == "+14155552671"
    assert "Python" in results[0]["skills"]

def test_cli_missing_config_returns_nonzero(tmp_path):
    from candidate_transformer.__main__ import main
    rc = main([
        "--sources", str(tmp_path / "nothing.csv"),
        "--config", str(tmp_path / "no_config.json"),
        "--output", str(tmp_path / "out.json"),
    ])
    assert rc == 1
