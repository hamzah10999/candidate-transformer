import csv
import io
import logging
from ..models.fragment import Fragment, Provenance
from ._hint import content_hint

log = logging.getLogger(__name__)

SOURCE = "csv"

# CSV column name → canonical field name.
# "email" → "emails" and "phone" → "phones" because the canonical profile
# stores these as lists (union across sources). The adapter emits one fragment
# per value; the merge stage handles dedup.
_COL_TO_FIELD: dict[str, str] = {
    "name": "name",
    "email": "emails",
    "phone": "phones",
    "current_company": "current_company",
    "title": "title",
}


def extract_csv(content: str) -> list[list[Fragment]]:
    """Parse recruiter CSV into per-candidate fragment groups.

    Returns one fragment group per CSV row. Rows that produce no fragments
    (e.g. entirely empty) are silently skipped. A malformed row is logged
    and skipped — never fatal to the batch.
    """
    try:
        reader = csv.DictReader(io.StringIO(content))
    except Exception as exc:
        log.warning("csv: failed to parse content: %s", exc)
        return []

    result: list[list[Fragment]] = []
    for i, row in enumerate(reader):
        try:
            group = _row_to_fragments(row)
            if group:
                result.append(group)
        except Exception as exc:
            log.warning("csv: row %d skipped: %s", i, exc)
    return result


def _row_to_fragments(row: dict[str, str]) -> list[Fragment]:
    raw_email = (row.get("email") or "").strip().lower()
    raw_phone = (row.get("phone") or "").strip()

    if raw_email:
        hint = raw_email
    elif raw_phone:
        hint = raw_phone
    else:
        # No strong identity key — hash the row so this candidate still
        # gets a deterministic slot in the merge index rather than being dropped.
        hint = content_hint(SOURCE, repr(sorted(row.items())))

    fragments: list[Fragment] = []
    for col, canonical_field in _COL_TO_FIELD.items():
        raw = (row.get(col) or "").strip()
        if not raw:
            continue
        fragments.append(Fragment(
            field=canonical_field,
            raw_value=raw,
            provenance=Provenance(source=SOURCE, method="direct", raw_value=raw),
            candidate_hint=hint,
        ))
    return fragments
