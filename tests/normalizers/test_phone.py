import pytest
from candidate_transformer.normalizers.phone import normalize_phone


# --- Failure paths (the point of this normalizer) ---

def test_garbage_string_returns_unparseable():
    value, method = normalize_phone("not a phone number")
    assert value is None
    assert method == "unparseable"

def test_empty_string_returns_unparseable():
    value, method = normalize_phone("")
    assert value is None
    assert method == "unparseable"

def test_bare_national_number_without_region_returns_unparseable():
    # "4155552671" has no country prefix — without a region hint we must
    # not guess. The spec says: Phone with no country code → null + method unparseable.
    value, method = normalize_phone("4155552671")
    assert value is None
    assert method == "unparseable"

def test_invalid_number_too_short():
    # Syntactically parseable as a US number but libphonenumber rejects it.
    value, method = normalize_phone("+1415555")
    assert value is None
    assert method == "invalid"

def test_letters_in_number_returns_unparseable():
    value, method = normalize_phone("+1-800-FLOWERS")
    # libphonenumber actually handles vanity numbers — if it resolves, fine;
    # if not, we must get None. Either way, never a crash.
    value2, method2 = normalize_phone("+1abc")
    assert value2 is None
    assert method2 == "unparseable"


# --- Happy paths ---

def test_e164_input_roundtrips():
    value, method = normalize_phone("+14155552671")
    assert value is not None
    assert value.e164 == "+14155552671"
    assert value.country_code == 1
    assert value.national_number == 4155552671
    assert method == "e164"

def test_national_number_with_region_hint_parses():
    # Bare national number is fine when the adapter supplies a region hint.
    value, method = normalize_phone("4155552671", region="US")
    assert value is not None
    assert value.e164 == "+14155552671"
    assert method == "e164"

def test_international_format_with_spaces():
    value, method = normalize_phone("+44 20 7946 0958")
    assert value is not None
    assert value.country_code == 44
    assert method == "e164"

def test_indian_number():
    value, method = normalize_phone("+919876543210")
    assert value is not None
    assert value.country_code == 91
    assert method == "e164"

def test_output_fields_are_primitives():
    # Guards against libphonenumber objects leaking into the model.
    value, _ = normalize_phone("+14155552671")
    assert isinstance(value.e164, str)
    assert isinstance(value.country_code, int)
    assert isinstance(value.national_number, int)
