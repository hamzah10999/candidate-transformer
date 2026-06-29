from __future__ import annotations
import re
from dateutil import parser as dateutil_parser
from ..models.canonical import ParsedDate

_PRESENT_TOKENS = frozenset({"present", "current", "now", "ongoing"})

_SEASON_RE = re.compile(
    r"\b(spring|summer|fall|autumn|winter)\b", re.IGNORECASE
)
_MONTH_NAME_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
    re.IGNORECASE,
)
_YEAR_ONLY_RE = re.compile(r"^\d{4}$")
_YYYY_MM_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def normalize_date(raw: str) -> tuple[ParsedDate | None, str]:
    """Parse a raw date string into a structured ParsedDate.

    Returns:
        (ParsedDate, method)   — parsed successfully
        (None, "present")      — string means "ongoing / no end date" (intentional null)
        (None, "unparseable")  — string is garbage (failure null)

    Rules applied in order:
        "Present" / "Current"  → (None, "present")
        "2021"                 → (ParsedDate(year=2021), "year_only")
        "2021-06"              → (ParsedDate(year=2021, month=6), "yyyy_mm")
        "Summer 2021"          → (ParsedDate(year=2021), "year_only")
            Season stripped; month is NOT invented — spec forbids it.
        "June 2021"            → (ParsedDate(year=2021, month=6), "yyyy_mm")
        Anything else          → dateutil fallback, then (None, "unparseable")
    """
    s = raw.strip()
    lower = s.lower()

    if lower in _PRESENT_TOKENS:
        return None, "present"

    if _YEAR_ONLY_RE.match(s):
        return ParsedDate(year=int(s)), "year_only"

    m = _YYYY_MM_RE.match(s)
    if m:
        return ParsedDate(year=int(m.group(1)), month=int(m.group(2))), "yyyy_mm"

    # Season strings: extract year, never invent a month.
    if _SEASON_RE.search(s):
        year_m = re.search(r"\b(\d{4})\b", s)
        if year_m:
            return ParsedDate(year=int(year_m.group(1))), "year_only"
        return None, "unparseable"

    # For everything else, delegate to dateutil but only trust the month
    # if the raw string actually contains a month name. dateutil fills in
    # the current month as a default — we must not let that leak through.
    try:
        parsed = dateutil_parser.parse(s, dayfirst=False)
    except (ValueError, OverflowError, TypeError):
        return None, "unparseable"

    if _MONTH_NAME_RE.search(s):
        return ParsedDate(year=parsed.year, month=parsed.month), "yyyy_mm"

    # Month name absent — trust only the year.
    return ParsedDate(year=parsed.year), "year_only"
