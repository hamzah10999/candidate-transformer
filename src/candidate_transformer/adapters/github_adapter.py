import json
import logging
from ..models.fragment import Fragment, Provenance
from ._hint import content_hint

log = logging.getLogger(__name__)

SOURCE = "github"


def extract_github(content: str) -> list[list[Fragment]]:
    """Parse a GitHub API fixture JSON into per-candidate fragment groups.

    Accepts either a single profile object or a list of profile objects.
    In production the pipeline calls the live API; in tests it passes a
    cached fixture string so the pipeline stays deterministic.
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        log.warning("github: JSON parse failed: %s", exc)
        return []

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        log.warning("github: expected object or list, got %s", type(data).__name__)
        return []

    result: list[list[Fragment]] = []
    for i, profile in enumerate(data):
        if not isinstance(profile, dict):
            log.warning("github: profile %d is not an object, skipped", i)
            continue
        try:
            group = _profile_to_fragments(profile)
            if group:
                result.append(group)
        except Exception as exc:
            log.warning("github: profile %d skipped: %s", i, exc)
    return result


def _profile_to_fragments(profile: dict) -> list[Fragment]:
    raw_email = (profile.get("email") or "").strip().lower()
    login = (profile.get("login") or "").strip()
    html_url = (profile.get("html_url") or "").strip()

    # Hint priority: email > login-based hash > full-profile hash.
    # Login is not a strong identity key on its own (not globally unique across
    # real people), so we hash it rather than use it raw — but we still salt
    # with source so a notes fragment for the same text doesn't collide.
    if raw_email:
        hint = raw_email
    elif login:
        hint = content_hint(SOURCE, login)
    else:
        hint = content_hint(SOURCE, json.dumps(profile, sort_keys=True))

    fragments: list[Fragment] = []

    def _add(field: str, raw: str, method: str = "api_field") -> None:
        fragments.append(Fragment(
            field=field,
            raw_value=raw,
            provenance=Provenance(source=SOURCE, method=method, raw_value=raw),
            candidate_hint=hint,
        ))

    name = (profile.get("name") or "").strip()
    if name:
        _add("name", name)

    if raw_email:
        _add("emails", raw_email)

    bio = (profile.get("bio") or "").strip()
    if bio:
        _add("bio", bio)

    location = (profile.get("location") or "").strip()
    if location:
        _add("location", location)

    if html_url:
        _add("github_url", html_url)

    # Skills inferred from repository languages.
    # One fragment per unique language; order is repo order (stable for fixtures).
    seen: set[str] = set()
    for repo in (profile.get("repos") or []):
        if not isinstance(repo, dict):
            continue
        lang = (repo.get("language") or "").strip()
        if lang and lang not in seen:
            seen.add(lang)
            _add("skills", lang)

    return fragments
