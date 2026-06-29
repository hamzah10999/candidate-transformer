import re
import logging
from ..models.fragment import Fragment, Provenance
from ._hint import content_hint

log = logging.getLogger(__name__)

SOURCE = "notes"

# Patterns are intentionally conservative — it's better to miss a value
# (returns None, logged) than to extract a wrong one (wrong-but-confident).
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# Phone: optional leading +, then digits/spaces/dashes/dots/parens, min 7 digits total.
# We don't validate format here — that's normalize_phone's job.
_PHONE_RE = re.compile(r"(?<!\d)(\+?[\d][\d\s\-().]{5,}\d)(?!\d)")

# ISO date guard: YYYY-MM-DD looks like a phone to _PHONE_RE because it has
# digits and dashes, but it's not a phone number.
_DATE_LIKE_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}$")

# Labelled fields — colon-separated, rest of line is the value.
_NAME_RE = re.compile(r"^(?:Candidate|Name)\s*:\s*(.+)", re.IGNORECASE | re.MULTILINE)
_TITLE_RE = re.compile(r"^(?:Title|Role|Position)\s*:\s*(.+)", re.IGNORECASE | re.MULTILINE)
_COMPANY_RE = re.compile(r"^(?:Company|Employer)\s*:\s*(.+)", re.IGNORECASE | re.MULTILINE)
_SKILLS_RE = re.compile(r"^Skills?\s*:\s*(.+)", re.IGNORECASE | re.MULTILINE)

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")


def extract_notes(content: str) -> list[list[Fragment]]:
    """Extract candidate fragments from a recruiter notes .txt file.

    Splits on blank lines so different candidates in the same file don't bleed
    into each other — each paragraph becomes its own candidate group.
    Empty file → logged, returns [].
    Partial extraction is fine — whatever regex matches come through.
    """
    if not content.strip():
        log.warning("notes: file is empty")
        return []

    groups: list[list[Fragment]] = []
    for paragraph in _PARAGRAPH_SPLIT_RE.split(content):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        try:
            frags = _text_to_fragments(paragraph)
            if frags:
                groups.append(frags)
        except Exception as exc:
            log.warning("notes: paragraph extraction failed: %s", exc)
    return groups


def _text_to_fragments(text: str) -> list[Fragment]:
    emails = [m.lower() for m in _EMAIL_RE.findall(text)]
    # Filter out ISO dates (YYYY-MM-DD) that _PHONE_RE greedily matches.
    phones = [
        m.strip() for m in _PHONE_RE.findall(text)
        if not _DATE_LIKE_RE.match(m.strip())
    ]

    if emails:
        hint = emails[0]
    elif phones:
        hint = phones[0]
    else:
        # No strong identity key — content hash salted with source name.
        hint = content_hint(SOURCE, text)

    fragments: list[Fragment] = []

    def _add(field: str, raw: str) -> None:
        fragments.append(Fragment(
            field=field,
            raw_value=raw,
            provenance=Provenance(source=SOURCE, method="regex", raw_value=raw),
            candidate_hint=hint,
        ))

    m = _NAME_RE.search(text)
    if m:
        _add("name", m.group(1).strip())

    for email in emails:
        _add("emails", email)

    # Only emit the first phone — later ones are more likely to be company
    # numbers or noise. The merge stage deduplicates anyway.
    if phones:
        _add("phones", phones[0])

    m = _TITLE_RE.search(text)
    if m:
        _add("title", m.group(1).strip())

    m = _COMPANY_RE.search(text)
    if m:
        _add("current_company", m.group(1).strip())

    m = _SKILLS_RE.search(text)
    if m:
        for skill in re.split(r",\s*", m.group(1)):
            skill = skill.strip()
            if skill:
                _add("skills", skill)

    return fragments
