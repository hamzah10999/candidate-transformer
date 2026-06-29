import pytest
from candidate_transformer.normalizers.country import normalize_country


# --- Failure paths ---

def test_fictional_country_returns_unknown():
    value, method = normalize_country("Narnia")
    assert value is None
    assert method == "unknown_country"

def test_invalid_alpha2_returns_unknown():
    # "ZZ" is not an assigned ISO-3166 code.
    value, method = normalize_country("ZZ")
    assert value is None
    assert method == "unknown_country"

def test_empty_string_returns_unknown():
    value, method = normalize_country("")
    assert value is None
    assert method == "unknown_country"

def test_random_gibberish_returns_unknown():
    value, method = normalize_country("xyzzy123")
    assert value is None
    assert method == "unknown_country"

def test_partial_name_that_could_be_ambiguous():
    # "New" alone is not enough to pick New Zealand vs New Caledonia etc.
    # Expect either a resolution or unknown — but NEVER a crash.
    value, method = normalize_country("New")
    # We don't assert a specific value here because pycountry fuzzy may or may
    # not resolve it; we only assert it doesn't raise and method is a string.
    assert isinstance(method, str)


# --- Happy paths ---

def test_alias_usa_resolves():
    value, method = normalize_country("USA")
    assert value == "US"
    assert method == "alias_map"

def test_alias_united_states_resolves():
    value, method = normalize_country("United States")
    assert value == "US"
    assert method == "alias_map"

def test_alias_uk_resolves():
    value, method = normalize_country("UK")
    assert value == "GB"
    assert method == "alias_map"

def test_direct_alpha2():
    value, method = normalize_country("DE")
    assert value == "DE"
    assert method == "iso3166_direct"

def test_alpha3_gbr():
    value, method = normalize_country("GBR")
    assert value == "GB"
    assert method == "iso3166_alpha3"

def test_full_official_name_via_pycountry():
    value, method = normalize_country("Germany")
    assert value == "DE"

def test_case_insensitive_alias():
    value, method = normalize_country("united states")
    assert value == "US"
    assert method == "alias_map"

def test_returns_alpha2_not_alpha3():
    # Confirm we always return 2-letter codes, never 3.
    for raw in ("USA", "United States", "US"):
        value, _ = normalize_country(raw)
        assert value is not None and len(value) == 2, raw
