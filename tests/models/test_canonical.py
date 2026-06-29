import json
import pytest
from candidate_transformer.models.canonical import (
    CandidateProfile,
    FieldValue,
    ParsedPhone,
    ParsedDate,
    DateRange,
    SkillRecord,
    MergeState,
)
from candidate_transformer.models.fragment import Fragment, Provenance
from candidate_transformer.models.config import (
    ProjectionConfig,
    FieldSpec,
    GlobalConfig,
    OnMissing,
    NormalizeAs,
)


def _make_profile() -> CandidateProfile:
    """Builds a fully-populated profile covering every field type."""
    prov = Provenance(source="csv", method="direct", raw_value="Alice Smith")
    return CandidateProfile(
        candidate_id="e3b0abc123",
        name=FieldValue(value="Alice Smith", confidence=0.9, provenance=[prov]),
        emails=["alice@example.com", "a.smith@work.com"],
        phones=[ParsedPhone(e164="+14155552671", country_code=1, national_number=4155552671)],
        current_company=FieldValue(value="Acme Corp", confidence=0.8, provenance=[prov]),
        title=FieldValue(value="Engineer", confidence=0.75, provenance=[prov]),
        location=FieldValue(value="US", confidence=0.6, provenance=[prov]),
        bio=FieldValue(value="Loves open source.", confidence=0.5, provenance=[prov]),
        github_url=FieldValue(value="https://github.com/alice", confidence=0.7, provenance=[prov]),
        skills=[
            SkillRecord(
                name="Python",
                sources=["csv", "github"],
                confidence=0.95,
                provenance=[prov],
            )
        ],
        merge_state=MergeState.MERGED,
        source_record_ids=["csv:0", "github:alice"],
        overall_confidence=0.8,
    )


def test_round_trip_json():
    """Serialize to JSON, deserialize back, assert structural equality.

    This matters because the whole pipeline output is JSON. If any field
    loses information through serialization (e.g. an Enum becomes an int,
    or a nested model drops a field), the output would be silently wrong.
    """
    original = _make_profile()
    as_json = original.model_dump_json()
    restored = CandidateProfile.model_validate_json(as_json)
    assert restored == original


def test_round_trip_dict():
    """model_dump -> model_validate round trip (the dict path used internally)."""
    original = _make_profile()
    as_dict = original.model_dump()
    restored = CandidateProfile.model_validate(as_dict)
    assert restored == original


def test_phone_fields_are_primitives():
    """ParsedPhone must serialize to plain JSON primitives, not opaque objects.

    If this fails it means libphonenumber objects leaked into the model,
    which would break any JSON dump without a custom serializer.
    """
    profile = _make_profile()
    data = json.loads(profile.model_dump_json())
    phone = data["phones"][0]
    assert isinstance(phone["e164"], str)
    assert isinstance(phone["country_code"], int)
    assert isinstance(phone["national_number"], int)


def test_field_value_type_enforcement():
    """FieldValue[str] must reject a non-string value.

    This is the concrete benefit of Generic[T] over value: Any.
    With Any, this assignment would silently succeed and a ParsedPhone
    would flow into a field that consumers expect to be a string.
    """
    with pytest.raises(Exception):  # pydantic ValidationError
        FieldValue[str](value=ParsedPhone(e164="+1415", country_code=1, national_number=415))


def test_merge_state_serializes_as_string():
    """MergeState is a str Enum — it must round-trip as its string value,
    not as an integer ordinal."""
    profile = _make_profile()
    data = json.loads(profile.model_dump_json())
    assert data["merge_state"] == "merged"


def test_projection_config_round_trip():
    """ProjectionConfig must parse from a JSON dict (simulates loading a .json file)
    and the 'from' alias must map correctly to from_path."""
    raw = {
        "fields": [
            {"path": "email", "from": "emails[0]", "type": "string"},
            {"path": "phone", "from": "phones[0].e164", "type": "string", "normalize": "e164"},
        ],
        "globals": {
            "include_confidence": True,
            "include_provenance": False,
            "on_missing": "omit",
        },
    }
    cfg = ProjectionConfig.model_validate(raw)
    assert cfg.fields[0].from_path == "emails[0]"
    assert cfg.fields[1].normalize == NormalizeAs.E164
    assert cfg.globals.on_missing == OnMissing.OMIT

    # Re-serialize and re-parse to confirm the alias survives
    restored = ProjectionConfig.model_validate(json.loads(cfg.model_dump_json(by_alias=True)))
    assert restored == cfg


def test_fragment_requires_candidate_hint():
    """Fragment.candidate_hint is now a required str (not optional).
    Adapters must always provide a grouping key — None is not allowed.
    """
    prov = Provenance(source="github", method="api_field")
    with pytest.raises(Exception):  # ValidationError: missing required field
        Fragment(field="bio", raw_value="loves open source", provenance=prov)
