import pytest
from candidate_transformer.normalizers.date import normalize_date


# --- Failure paths and edge cases (the point of this normalizer) ---

def test_garbage_returns_unparseable():
    value, method = normalize_date("not a date at all!!!")
    assert value is None
    assert method == "unparseable"

def test_empty_string_returns_unparseable():
    value, method = normalize_date("")
    assert value is None
    assert method == "unparseable"

def test_present_returns_intentional_null():
    # "Present" is NOT a parse failure — it's a meaningful sentinel encoding
    # "ongoing." The caller uses (None, "present") to set DateRange.end = None.
    value, method = normalize_date("Present")
    assert value is None
    assert method == "present"

def test_present_case_insensitive():
    for raw in ("present", "PRESENT", "Current", "current", "Now", "ongoing"):
        value, method = normalize_date(raw)
        assert value is None, f"Expected None for {raw!r}"
        assert method == "present", f"Expected 'present' for {raw!r}"

def test_season_year_keeps_year_only_never_invents_month():
    # "Summer 2021" — we know the year, but inventing June/July/August would
    # be wrong-but-confident. Month must stay None.
    value, method = normalize_date("Summer 2021")
    assert value is not None
    assert value.year == 2021
    assert value.month is None
    assert method == "year_only"

def test_all_seasons_strip_correctly():
    for season in ("Spring", "Fall", "Autumn", "Winter"):
        value, method = normalize_date(f"{season} 2019")
        assert value is not None and value.year == 2019 and value.month is None, season

def test_year_only_string():
    value, method = normalize_date("2021")
    assert value is not None
    assert value.year == 2021
    assert value.month is None
    assert method == "year_only"

def test_dateutil_does_not_inject_month_for_bare_year():
    # dateutil.parse("2018") fills in the current month by default.
    # Our normalizer must not let that leak — only "2018-06" or "June 2018"
    # should produce a month.
    value, method = normalize_date("2018")
    assert value.month is None

def test_season_without_year_returns_unparseable():
    value, method = normalize_date("Summer")
    assert value is None
    assert method == "unparseable"


# --- Happy paths ---

def test_yyyy_mm_format():
    value, method = normalize_date("2021-06")
    assert value.year == 2021
    assert value.month == 6
    assert value.day is None
    assert method == "yyyy_mm"

def test_month_name_year():
    value, method = normalize_date("June 2021")
    assert value.year == 2021
    assert value.month == 6
    assert method == "yyyy_mm"

def test_abbreviated_month_name():
    value, method = normalize_date("Jan 2020")
    assert value.year == 2020
    assert value.month == 1
    assert method == "yyyy_mm"

def test_month_boundary_december():
    value, method = normalize_date("2023-12")
    assert value.year == 2023
    assert value.month == 12
