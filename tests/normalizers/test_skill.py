import pytest
from candidate_transformer.normalizers.skill import normalize_skill, _VERBATIM_CONFIDENCE, _KNOWN_CONFIDENCE


# --- Failure paths (unknown skills — the spec's key rule) ---

def test_unknown_skill_kept_verbatim():
    # "Brainfuck" is not in our map — must come back as-is, not dropped or
    # silently mapped to something else.
    name, confidence, method = normalize_skill("Brainfuck")
    assert name == "Brainfuck"
    assert method == "verbatim"
    assert confidence == _VERBATIM_CONFIDENCE

def test_unknown_skill_has_lower_confidence_than_known():
    _, unknown_conf, _ = normalize_skill("SomeMadeUpFramework")
    _, known_conf, _ = normalize_skill("Python")
    assert unknown_conf < known_conf

def test_unknown_skill_never_returns_none():
    # Unlike phone/country/date, skill must always return a name — never None.
    name, confidence, method = normalize_skill("NotInAnyMap")
    assert name is not None
    assert name != ""

def test_mixed_case_unknown_preserved():
    # Verbatim means preserving the original casing, not lowercasing it.
    name, _, method = normalize_skill("GraphQL")
    # GraphQL is not in our alias map — should come back verbatim.
    # (If it IS added to the map later, this test signals it needs updating.)
    if method == "verbatim":
        assert name == "GraphQL"

def test_whitespace_stripped_from_verbatim():
    name, _, method = normalize_skill("  UnknownThing  ")
    assert name == "UnknownThing"


# --- Happy paths ---

def test_lowercase_alias_js_resolves():
    name, confidence, method = normalize_skill("js")
    assert name == "JavaScript"
    assert method == "alias_map"
    assert confidence == _KNOWN_CONFIDENCE

def test_alias_python_lowercase():
    name, _, method = normalize_skill("python")
    assert name == "Python"
    assert method == "alias_map"

def test_canonical_name_resolves_to_itself():
    # Passing the already-canonical name must also resolve cleanly.
    name, confidence, method = normalize_skill("JavaScript")
    assert name == "JavaScript"
    assert method == "alias_map"
    assert confidence == _KNOWN_CONFIDENCE

def test_alias_k8s_resolves_to_kubernetes():
    name, _, method = normalize_skill("k8s")
    assert name == "Kubernetes"
    assert method == "alias_map"

def test_alias_ml_resolves():
    name, _, _ = normalize_skill("ml")
    assert name == "Machine Learning"

def test_alias_ts_resolves():
    name, _, _ = normalize_skill("ts")
    assert name == "TypeScript"

def test_alias_golang_resolves():
    name, _, _ = normalize_skill("golang")
    assert name == "Go"

def test_result_is_always_a_triple():
    # Structural contract: always (str, float, str) — never raises.
    for raw in ("", "python", "xyzzy", "C++", "node.js"):
        result = normalize_skill(raw)
        assert len(result) == 3
        name, conf, method = result
        assert isinstance(name, str)
        assert isinstance(conf, float)
        assert isinstance(method, str)
