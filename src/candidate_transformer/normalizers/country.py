from __future__ import annotations
import pycountry

# Informal names and abbreviations that pycountry doesn't resolve reliably.
# Keys are lowercase; values are ISO-3166 alpha-2.
_ALIAS_MAP: dict[str, str] = {
    "usa": "US",
    "united states": "US",
    "united states of america": "US",
    "us": "US",
    "uk": "GB",
    "united kingdom": "GB",
    "england": "GB",
    "great britain": "GB",
    "uae": "AE",
    "united arab emirates": "AE",
    "south korea": "KR",
    "korea": "KR",
    "czechia": "CZ",
    "czech republic": "CZ",
    "russia": "RU",
    "iran": "IR",
    "taiwan": "TW",
    "vietnam": "VN",
    "laos": "LA",
    "bolivia": "BO",
    "tanzania": "TZ",
    "syria": "SY",
    "venezuela": "VE",
    "moldova": "MD",
    "macedonia": "MK",
}


def normalize_country(raw: str) -> tuple[str | None, str]:
    """Resolve a raw country string to an ISO-3166 alpha-2 code.

    Returns (alpha_2, method) on success.
    Returns (None, "unknown_country") if the string cannot be resolved —
    never guesses.

    Resolution order:
        1. Alias map  — handles informal names ("USA", "UK", "United States")
        2. Direct alpha-2 lookup via pycountry (two uppercase letters)
        3. Direct alpha-3 lookup via pycountry (three uppercase letters)
        4. pycountry fuzzy search as a last resort
    """
    stripped = raw.strip()
    if not stripped:
        return None, "unknown_country"

    lower = stripped.lower()

    if lower in _ALIAS_MAP:
        return _ALIAS_MAP[lower], "alias_map"

    # alpha-2 direct: "US", "GB"
    if len(stripped) == 2:
        country = pycountry.countries.get(alpha_2=stripped.upper())
        if country:
            return country.alpha_2, "iso3166_direct"
        return None, "unknown_country"

    # alpha-3 direct: "USA", "GBR"
    if len(stripped) == 3 and stripped.isalpha():
        country = pycountry.countries.get(alpha_3=stripped.upper())
        if country:
            return country.alpha_2, "iso3166_alpha3"
        return None, "unknown_country"

    # pycountry fuzzy (handles most official country names)
    try:
        results = pycountry.countries.search_fuzzy(stripped)
        if results:
            return results[0].alpha_2, "pycountry_fuzzy"
    except LookupError:
        pass

    return None, "unknown_country"
