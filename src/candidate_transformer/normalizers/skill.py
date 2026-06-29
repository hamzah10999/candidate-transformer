from __future__ import annotations

# canonical name → set of lowercase aliases
_SKILL_ALIASES: dict[str, set[str]] = {
    "JavaScript": {"js", "javascript", "java script"},
    "TypeScript": {"ts", "typescript", "type script"},
    "Python": {"py", "python", "python3"},
    "Java": {"java"},
    "C++": {"c++", "cpp", "c plus plus"},
    "C#": {"c#", "csharp", "c sharp"},
    "Go": {"go", "golang"},
    "Rust": {"rust"},
    "Ruby": {"rb", "ruby"},
    "PHP": {"php"},
    "Swift": {"swift"},
    "Kotlin": {"kotlin"},
    "Scala": {"scala"},
    "SQL": {"sql"},
    "React": {"react", "reactjs", "react.js"},
    "Vue": {"vue", "vuejs", "vue.js"},
    "Angular": {"angular", "angularjs"},
    "Node.js": {"node", "nodejs", "node.js"},
    "Django": {"django"},
    "Flask": {"flask"},
    "FastAPI": {"fastapi", "fast api"},
    "Spring": {"spring", "spring boot", "springboot"},
    "Docker": {"docker"},
    "Kubernetes": {"k8s", "kubernetes"},
    "AWS": {"aws", "amazon web services"},
    "GCP": {"gcp", "google cloud", "google cloud platform"},
    "Azure": {"azure", "microsoft azure"},
    "TensorFlow": {"tensorflow", "tf"},
    "PyTorch": {"pytorch", "torch"},
    "Machine Learning": {"ml", "machine learning"},
    "Deep Learning": {"dl", "deep learning"},
    "PostgreSQL": {"postgres", "postgresql"},
    "MySQL": {"mysql"},
    "MongoDB": {"mongo", "mongodb"},
    "Redis": {"redis"},
    "Git": {"git"},
    "Linux": {"linux"},
}

# reverse lookup built once at import: lowercase alias → canonical name
_ALIAS_TO_CANONICAL: dict[str, str] = {
    alias: canonical
    for canonical, aliases in _SKILL_ALIASES.items()
    for alias in aliases
}

# Also index canonical names themselves (lowercase → canonical), so passing
# "JavaScript" or "javascript" both resolve the same way.
_CANONICAL_LOWER: dict[str, str] = {c.lower(): c for c in _SKILL_ALIASES}

_KNOWN_CONFIDENCE: float = 0.9
_VERBATIM_CONFIDENCE: float = 0.5


def normalize_skill(raw: str) -> tuple[str, float, str]:
    """Resolve a raw skill string to its canonical form and a confidence score.

    Unlike other normalizers, skill NEVER returns None — the spec says unknown
    skills are kept verbatim at lower confidence, so the caller always gets a
    usable name.

    Returns: (canonical_name, confidence, method)
        method = "alias_map"  — resolved via the curated map (confidence 0.9)
        method = "verbatim"   — unrecognized, kept as-is  (confidence 0.5)
    """
    key = raw.strip().lower()

    if key in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[key], _KNOWN_CONFIDENCE, "alias_map"

    if key in _CANONICAL_LOWER:
        return _CANONICAL_LOWER[key], _KNOWN_CONFIDENCE, "alias_map"

    return raw.strip(), _VERBATIM_CONFIDENCE, "verbatim"
