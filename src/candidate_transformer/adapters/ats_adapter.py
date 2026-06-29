import json
import logging
from ..models.fragment import Fragment, Provenance
from ._hint import content_hint

log = logging.getLogger(__name__)

SOURCE = "ats"

# ATS field names → canonical field names. These differ from our schema
# deliberately — the ATS uses its own vocabulary.
_ATS_TO_FIELD: dict[str, str] = {
    "candidate_name": "name",
    "contact_email": "emails",
    "contact_phone": "phones",
    "employer": "current_company",
    "position": "title",
    "country": "location",
    "summary": "bio",
    "profile_url": "github_url",
    # "tags" is a list field handled separately below
}


def extract_ats(content: str) -> list[list[Fragment]]:
    """Parse ATS JSON into per-candidate fragment groups.

    Accepts either a JSON array of records or a single record object.
    Malformed JSON or unrecognised structure is logged and returns empty.
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        log.warning("ats: JSON parse failed: %s", exc)
        return []

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        log.warning("ats: expected list or object at root, got %s", type(data).__name__)
        return []

    result: list[list[Fragment]] = []
    for i, record in enumerate(data):
        if not isinstance(record, dict):
            log.warning("ats: record %d is not an object, skipped", i)
            continue
        try:
            group = _record_to_fragments(record)
            if group:
                result.append(group)
        except Exception as exc:
            log.warning("ats: record %d skipped: %s", i, exc)
    return result


def _record_to_fragments(record: dict) -> list[Fragment]:
    raw_email = (record.get("contact_email") or "").strip().lower()
    raw_phone = (record.get("contact_phone") or "").strip()

    if raw_email:
        hint = raw_email
    elif raw_phone:
        hint = raw_phone
    else:
        hint = content_hint(SOURCE, json.dumps(record, sort_keys=True))

    fragments: list[Fragment] = []

    # Scalar string fields
    for ats_field, canonical_field in _ATS_TO_FIELD.items():
        val = record.get(ats_field)
        if not isinstance(val, str):
            continue
        raw = val.strip()
        if not raw:
            continue
        # Normalise email hint key consistently
        stored = raw.lower() if canonical_field == "emails" else raw
        fragments.append(Fragment(
            field=canonical_field,
            raw_value=stored,
            provenance=Provenance(source=SOURCE, method="direct", raw_value=raw),
            candidate_hint=hint,
        ))

    # "tags" is a JSON array → one skill fragment per entry
    for tag in (record.get("tags") or []):
        if isinstance(tag, str) and tag.strip():
            fragments.append(Fragment(
                field="skills",
                raw_value=tag.strip(),
                provenance=Provenance(source=SOURCE, method="direct", raw_value=tag.strip()),
                candidate_hint=hint,
            ))

    return fragments
