"""Human approval of fuzzy name variants; no acoustic or identity inference."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

from pastor_transcript_extractor.speaker_registry import (
    NAME_VARIANT_REVIEW_PREFIX,
    FUZZY_NAME_REVIEW_MIN_SIMILARITY,
    approved_profile_name_variant_reviews,
    normalize_person_name,
    fuzzy_name_similarity,
    profile_names_compatible,
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
    association_report: str | None = None
    association_result_sha256: str | None = None


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
        similarity = fuzzy_name_similarity(names)
        if similarity < FUZZY_NAME_REVIEW_MIN_SIMILARITY:
            continue
        candidates.append(NameVariantCandidate(
            canonical, tuple(displays.values()), names,
            tuple(sorted(c.id for c in claims)), similarity,
        ))
    return tuple(candidates)


def association_name_variant_candidate(database: Database, report_path: Path):
    """Review a saved unique voice match without moving its observation/claims."""
    from pastor_transcript_extractor.media_artifacts import get_registered_normalized_media_artifact
    from pastor_transcript_extractor.speaker_registry import reviewed_profile_name_alias_groups
    from pastor_transcript_extractor.speaker_shadow_association import verify_shadow_association_receipt
    report_path = report_path.expanduser().resolve()
    report = verify_shadow_association_receipt(json.loads(report_path.read_text()))
    receipt = report["result_sha256"]
    if report.get("artifact_kind") != "speaker_profile_shadow_association":
        raise ValueError("Association report failed verification")
    if report.get("outcome") != "conflicting_attribution":
        raise ValueError("Report does not contain a held name conflict")
    candidate = report["candidate"]
    observation = database.get_speaker_observation(candidate["observation_id"])
    if (observation is None or observation.input_fingerprint != candidate["input_fingerprint"]
            or database.get_latest_speaker_observation_for_video(observation.video_id).id != observation.id):
        raise ValueError("Candidate observation is stale")
    artifact = get_registered_normalized_media_artifact(database, observation.video_id)
    if artifact is None or artifact.content_sha256 != candidate["normalized_audio_sha256"]:
        raise ValueError("Candidate audio identity is stale")
    claims = database.list_speaker_name_claims()
    incoming = [c for c in claims if c.observation_id == observation.id
                and database.is_confirmed_speaker_name_claim(c)]
    if {c.normalized_name for c in incoming} != set(candidate["normalized_names"]):
        raise ValueError("Candidate name evidence changed")
    matches = [p for p in report["profiles"] if p.get("meets_multi_exemplar_match")]
    if len(matches) != 1:
        raise ValueError("A unique saved voice match is required")
    matched = matches[0]
    profile_id = database.resolve_speaker_profile_id(matched["profile_id"])
    members = {o for p in database.list_speaker_profiles()
               if database.resolve_speaker_profile_id(p.id) == profile_id
               for o in database.list_effective_observation_ids_for_profile(p.id)}
    differences = set(database.list_effective_observation_difference_pairs())
    if any(tuple(sorted((observation.id, member))) in differences for member in members):
        raise ValueError("A reviewed different-speaker constraint blocks this match")
    same = set()
    for comparison in matched["comparisons"]:
        if comparison.get("outcome") in {"different_speaker", "analysis_failed"}:
            raise ValueError("Saved voice evidence contains a different-speaker result or failure")
        exemplar = database.get_speaker_observation(comparison["exemplar_observation_id"])
        if exemplar is None or exemplar.id not in members or exemplar.input_fingerprint != comparison["exemplar_fingerprint"]:
            raise ValueError("Saved exemplar membership is stale")
        media = get_registered_normalized_media_artifact(database, exemplar.video_id)
        if media is None or media.content_sha256 != comparison["exemplar_normalized_audio_sha256"]:
            raise ValueError("Exemplar audio identity is stale")
        if comparison["outcome"] == "same_speaker":
            same.add(exemplar.input_fingerprint)
    if len(same) < max(2, report.get("minimum_same_exemplars", 2)):
        raise ValueError("Insufficient saved same-speaker evidence")
    attached = [c for c in claims if database.is_confirmed_speaker_name_claim(c)
                and (review := database.get_effective_name_claim_review(c.id))[1] is not None
                and database.resolve_speaker_profile_id(review[1]) == profile_id]
    configured = [p.display_name for p in database.list_pastors()
                  if (bound := database.get_pastor_speaker_profile_id(p.id)) is not None
                  and database.resolve_speaker_profile_id(bound) == profile_id]
    displays = {}
    for name in [*configured, *(c.display_name for c in attached), *(c.display_name for c in incoming)]:
        displays.setdefault(normalize_person_name(name), name)
    target_names = {normalize_person_name(n) for n in configured} | {c.normalized_name for c in attached}
    aliases = reviewed_profile_name_alias_groups(database).get(profile_id, ())
    if profile_names_compatible(candidate["normalized_names"], target_names, aliases):
        raise ValueError("These names are already compatible; no repeat review is needed")
    score = fuzzy_name_similarity(displays)
    if score < FUZZY_NAME_REVIEW_MIN_SIMILARITY:
        raise ValueError("Names are not close spelling variants; use attribution review")
    return NameVariantCandidate(profile_id, tuple(displays.values()), tuple(displays),
                                tuple(sorted(c.id for c in attached)), score,
                                str(report_path), receipt)


def approve_name_variants(database: Database, candidate: NameVariantCandidate,
                          preferred_name: str, reviewer: str):
    if not reviewer.strip() or reviewer.strip().lower().startswith("system"):
        raise ValueError("A human reviewer is required")
    if preferred_name not in candidate.names:
        raise ValueError("Choose one of the displayed names")
    with database.transaction():
        current = ((association_name_variant_candidate(database, Path(candidate.association_report)),)
                   if candidate.association_report else list_name_variant_candidates(database, candidate.profile_id))
        if candidate not in current:
            raise ValueError("Name evidence changed; rerun the review")
        receipt = {"version": "profile_name_variants_v1", **asdict(candidate),
                   "preferred_name": preferred_name, "reviewer": reviewer.strip(),
                   "voice_membership_changed": False, "profile_redirects_changed": False}
        previous = approved_profile_name_variant_reviews(database).get(candidate.profile_id)
        if previous:
            receipt["normalized_names"] = sorted(set(candidate.normalized_names) | set(previous["normalized_names"]))
            receipt["names"] = list(dict.fromkeys([*previous.get("names", ()), *candidate.names]))
        reason = NAME_VARIANT_REVIEW_PREFIX + json.dumps(receipt, sort_keys=True)
        key = hashlib.sha256(reason.encode()).hexdigest()
        claim_ids = candidate.claim_ids
        if not claim_ids:
            # Configured-only identities need an observation-bound review anchor.
            member_id = next(iter(database.list_effective_observation_ids_for_profile(candidate.profile_id)), None)
            if member_id is None:
                raise ValueError("Profile has no observation to anchor name approval")
            member = database.get_speaker_observation(member_id)
            claim = database.add_speaker_name_claim(
                video_id=member.video_id, observation_id=member.id,
                display_name=preferred_name, normalized_name=normalize_person_name(preferred_name),
                claim_kind="reviewed_profile_attribution", channel="manual_review",
                explicit_speaker_attribution=True, correlation_group_id=f"name-variants:{key}",
                provenance_json=json.dumps(receipt), artifact_path=candidate.association_report or "",
                claim_fingerprint=key, extractor_version="profile_name_variants_v1",
            )
            claim_ids = (claim.id,)
        for claim_id in claim_ids:
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
