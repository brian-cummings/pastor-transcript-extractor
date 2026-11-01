"""Human approval of fuzzy name variants; no acoustic or identity inference."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
import hashlib
import json

from pastor_transcript_extractor.speaker_registry import (
    NAME_VARIANT_REVIEW_PREFIX,
    approved_profile_name_variant_reviews,
    normalize_person_name,
    record_name_claim_review,
)
from pastor_transcript_extractor.storage import Database


@dataclass(frozen=True)
class NameVariantCandidate:
    profile_id: int
    names: tuple[str, ...]
    normalized_names: tuple[str, ...]
    claim_ids: tuple[int, ...]
    minimum_similarity: float


def list_name_variant_candidates(database: Database, profile_id: int | None = None):
    """Fuzzy similarity nominates review only; it never grants alias authority."""
    requested = database.resolve_speaker_profile_id(profile_id) if profile_id else None
    claims_by_profile = defaultdict(list)
    configured = defaultdict(list)
    for claim in database.list_speaker_name_claims():
        review = database.get_effective_name_claim_review(claim.id)
        if review and review[0] == "attach" and review[1] is not None:
            canonical = database.resolve_speaker_profile_id(review[1])
            if requested is None or canonical == requested:
                claims_by_profile[canonical].append(claim)
    for pastor in database.list_pastors():
        bound = database.get_pastor_speaker_profile_id(pastor.id)
        if bound is not None:
            configured[database.resolve_speaker_profile_id(bound)].append(pastor.display_name)
    approvals = approved_profile_name_variant_reviews(database)
    candidates = []
    for canonical, claims in sorted(claims_by_profile.items()):
        counts = Counter(c.display_name for c in claims)
        ordered = sorted(counts, key=lambda n: (-counts[n], n))
        ordered = list(dict.fromkeys([*configured[canonical], *ordered]))
        displays = {}
        for name in ordered:
            normalized = normalize_person_name(name)
            if normalized:
                displays.setdefault(normalized, name)
        names = tuple(displays)
        if len(names) < 2:
            continue
        approval = approvals.get(canonical)
        if approval and set(names).issubset(approval["normalized_names"]):
            continue
        similarity = min(SequenceMatcher(None, a, b).ratio()
                         for i, a in enumerate(names) for b in names[i + 1:])
        if similarity < 0.8:
            continue
        candidates.append(NameVariantCandidate(
            canonical, tuple(displays.values()), names,
            tuple(sorted(c.id for c in claims)), similarity,
        ))
    return tuple(candidates)


def approve_name_variants(database: Database, candidate: NameVariantCandidate,
                          preferred_name: str, reviewer: str):
    if not reviewer.strip() or reviewer.strip().lower().startswith("system"):
        raise ValueError("A human reviewer is required")
    if preferred_name not in candidate.names:
        raise ValueError("Choose one of the displayed names")
    with database.transaction():
        current = list_name_variant_candidates(database, candidate.profile_id)
        if candidate not in current:
            raise ValueError("Name evidence changed; rerun the review")
        receipt = {"version": "profile_name_variants_v1", **asdict(candidate),
                   "preferred_name": preferred_name, "reviewer": reviewer.strip(),
                   "voice_membership_changed": False, "profile_redirects_changed": False}
        reason = NAME_VARIANT_REVIEW_PREFIX + json.dumps(receipt, sort_keys=True)
        key = hashlib.sha256(reason.encode()).hexdigest()
        for claim_id in candidate.claim_ids:
            record_name_claim_review(
                database, claim_id=claim_id, profile_id=candidate.profile_id,
                attach=True, reviewer=reviewer.strip(), reason=reason,
                review_event_key=f"name-variants:{key}:{claim_id}",
            )
        # A presentation projection of the append-only approval above.
        with database.connect() as connection:
            connection.execute("UPDATE speaker_profiles SET display_label = ? WHERE id = ?",
                               (preferred_name, candidate.profile_id))
    return receipt
