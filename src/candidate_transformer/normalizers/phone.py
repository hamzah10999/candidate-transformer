from __future__ import annotations
import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat
from ..models.canonical import ParsedPhone


def normalize_phone(
    raw: str,
    region: str | None = None,
) -> tuple[ParsedPhone | None, str]:
    """Parse a raw phone string into a structured ParsedPhone.

    Returns (ParsedPhone, "e164") on success.
    Returns (None, reason) on any failure — never guesses a country code.

    region: ISO-3166 alpha-2 hint used only when the raw string has no
    country prefix (e.g. "4155552671" needs region="US" to parse).
    Without a hint, a bare national number returns (None, "unparseable")
    rather than silently assuming a country.
    """
    try:
        parsed = phonenumbers.parse(raw, region)
    except NumberParseException:
        return None, "unparseable"

    if not phonenumbers.is_valid_number(parsed):
        return None, "invalid"

    e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
    return (
        ParsedPhone(
            e164=e164,
            country_code=parsed.country_code,
            national_number=parsed.national_number,
        ),
        "e164",
    )
