from __future__ import annotations
import hashlib
import logging
from collections import defaultdict
from itertools import combinations

from ..models.canonical import CandidateProfile, MergeState, ParsedPhone
from ..models.fragment import Fragment
from ..normalizers.phone import normalize_phone
from ._union_find import UnionFind
from ._resolve import (
    SOURCE_TRUST,
    email_confidence,
    noisy_or,
    phone_confidence,
    resolve_emails,
    resolve_phones,
    resolve_scalar,
    resolve_skills,
)

log = logging.getLogger(__name__)


def merge_fragments(groups: list[list[Fragment]]) -> list[CandidateProfile]:
    """Cluster adapter fragment groups into canonical CandidateProfiles.

    `groups` is the combined output of all adapters: one inner list per
    source record (one CSV row, one ATS object, one GitHub profile, one
    notes file).

    Algorithm
    ---------
    1. Extract normalised emails and E.164 phones from every group.
    2. Build hashed blocking indices (email, then phone).
       Not all-pairs — each index is O(k) lookups where k = matches per key.
    3. Email match  → strong Union-Find merge (confident).
       Phone match, no email conflict  → weak merge, cluster flagged NEEDS_REVIEW.
       Phone match, conflicting emails → do NOT merge; flag both NEEDS_REVIEW.
       This is the recycled-phone guard: a lone weak edge must never force a merge.
    4. Build one CandidateProfile per final cluster, including the phone retry pass.
    """
    if not groups:
        return []

    gids = [f"g{i}" for i in range(len(groups))]

    # ── Step 1: extract normalised identity keys ──────────────────────────
    group_emails: dict[str, set[str]] = {}   # gid → {lowercase emails}
    group_phones: dict[str, set[str]] = {}   # gid → {E.164 phones}

    for gid, group in zip(gids, groups):
        emails: set[str] = set()
        phones: set[str] = set()
        for f in group:
            if f.field == "emails":
                val = str(f.raw_value).strip().lower()
                if val:
                    emails.add(val)
            elif f.field == "phones":
                parsed, _ = normalize_phone(str(f.raw_value).strip())
                if parsed:
                    phones.add(parsed.e164)
        group_emails[gid] = emails
        group_phones[gid] = phones

    # ── Step 2: blocking indices ──────────────────────────────────────────
    email_index: dict[str, list[str]] = defaultdict(list)
    phone_index: dict[str, list[str]] = defaultdict(list)

    for gid in gids:
        for email in group_emails[gid]:
            email_index[email].append(gid)
        for phone in group_phones[gid]:
            phone_index[phone].append(gid)

    # ── Step 3a: strong merges via shared email ───────────────────────────
    uf = UnionFind()
    for gid in gids:
        uf.add(gid)

    for matching_gids in email_index.values():
        for a, b in combinations(matching_gids, 2):
            uf.union(a, b)

    # ── Step 3b: build cluster-level email sets after strong merges ───────
    # These are the sets we use to detect recycled-phone conflicts below.
    cluster_emails: dict[str, set[str]] = {}
    for root, members in uf.groups().items():
        merged: set[str] = set()
        for gid in members:
            merged.update(group_emails[gid])
        cluster_emails[root] = merged

    needs_review: set[str] = set()  # cluster roots that must not be auto-merged

    # ── Step 3c: weak links via shared phone ─────────────────────────────
    for matching_gids in phone_index.values():
        for a, b in combinations(matching_gids, 2):
            root_a, root_b = uf.find(a), uf.find(b)
            if root_a == root_b:
                continue  # already merged by email

            emails_a = cluster_emails.get(root_a, set())
            emails_b = cluster_emails.get(root_b, set())

            if emails_a and emails_b and not (emails_a & emails_b):
                # Recycled / shared phone: both clusters have emails but they
                # differ — this is almost certainly two different real people.
                # Do NOT merge. Flag both for human review.
                needs_review.add(root_a)
                needs_review.add(root_b)
            else:
                # Phone-only link: weak evidence, merge but mark NEEDS_REVIEW.
                if uf.union(a, b):
                    new_root = uf.find(a)
                    # Keep cluster_emails consistent so later iterations
                    # see the merged email set for this cluster.
                    merged = emails_a | emails_b
                    cluster_emails[new_root] = merged
                    if root_a != new_root:
                        cluster_emails.pop(root_a, None)
                    if root_b != new_root:
                        cluster_emails.pop(root_b, None)
                    needs_review.add(new_root)

    # ── Step 4: build a CandidateProfile for each cluster ────────────────
    profiles: list[CandidateProfile] = []
    for root, member_ids in uf.groups().items():
        indices = [int(mid[1:]) for mid in member_ids]
        all_fragments = [f for i in indices for f in groups[i]]
        is_nr = root in needs_review
        profiles.append(_build_profile(all_fragments, is_nr, len(member_ids)))

    return profiles


# ── Profile construction ──────────────────────────────────────────────────

def _build_profile(
    fragments: list[Fragment],
    is_needs_review: bool,
    cluster_size: int,
) -> CandidateProfile:
    by_field: dict[str, list[Fragment]] = defaultdict(list)
    for f in fragments:
        by_field[f.field].append(f)

    # Resolve location first — it may supply the region hint for the phone retry.
    location = resolve_scalar(by_field.get("location", []))
    resolved_country: str | None = None
    if location.value and len(location.value) == 2 and location.value.isupper():
        resolved_country = location.value

    # List fields: union + dedup across all sources.
    emails = resolve_emails(by_field.get("emails", []))
    phones = resolve_phones(by_field.get("phones", []), resolved_country)
    skills = resolve_skills(by_field.get("skills", []))

    # Scalar fields: winner + confidence.
    name = resolve_scalar(by_field.get("name", []))
    current_company = resolve_scalar(by_field.get("current_company", []))
    title = resolve_scalar(by_field.get("title", []))
    bio = resolve_scalar(by_field.get("bio", []))
    github_url = resolve_scalar(by_field.get("github_url", []))

    # overall_confidence = mean of the three core identity field confidences.
    e_conf = email_confidence(by_field.get("emails", []))
    p_conf = phone_confidence(by_field.get("phones", []), resolved_country)
    overall = round((name.confidence + e_conf + p_conf) / 3, 6)

    if is_needs_review:
        overall = min(overall, 0.4)
        merge_state = MergeState.NEEDS_REVIEW
    elif cluster_size > 1:
        merge_state = MergeState.MERGED
    else:
        merge_state = MergeState.SINGLE

    candidate_id = _candidate_id(emails, phones, fragments)
    source_record_ids = sorted({f.candidate_hint for f in fragments})

    return CandidateProfile(
        candidate_id=candidate_id,
        name=name,
        emails=emails,
        phones=phones,
        current_company=current_company,
        title=title,
        location=location,
        bio=bio,
        github_url=github_url,
        skills=skills,
        merge_state=merge_state,
        source_record_ids=source_record_ids,
        overall_confidence=overall,
    )


def _candidate_id(
    emails: list[str],
    phones: list[ParsedPhone],
    fragments: list[Fragment],
) -> str:
    """Deterministic candidate ID: hash the strongest available identity key.

    Fallback chain: email → E.164 phone → content hash of all fragment values.
    Sorting before hashing ensures the same inputs always yield the same ID
    regardless of the order fragments were processed.
    """
    if emails:
        key = sorted(emails)[0]
        return hashlib.sha256(f"email:{key}".encode()).hexdigest()[:16]
    if phones:
        key = sorted(p.e164 for p in phones)[0]
        return hashlib.sha256(f"phone:{key}".encode()).hexdigest()[:16]
    content = "|".join(sorted(str(f.raw_value) for f in fragments))
    return hashlib.sha256(f"content:{content}".encode()).hexdigest()[:16]
