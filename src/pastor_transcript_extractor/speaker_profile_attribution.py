from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
from typing import Any

from pastor_transcript_extractor.speaker_registry import (
    normalize_person_name,
    record_name_claim_review,
    record_profile_redirect,
)
from pastor_transcript_extractor.storage import Database


PROFILE_ATTRIBUTION_REVIEW_VERSION = "profile_attribution_review_v1"
_REVIEWABLE_PROFILE_REASONS = {
    "reviewed_anonymous_speaker",
    "shadow_discovery_candidate",
}


@dataclass(frozen=True, slots=True)
class ProfileAttributionEvidence:
    observation_id: int
    observation_fingerprint: str
    youtube_video_id: str
    title: str
    video_url: str
    timestamp_seconds: int


@dataclass(frozen=True, slots=True)
class ProfileAttributionCandidate:
    profile_id: int
    member_count: int
    evidence: tuple[ProfileAttributionEvidence, ...]
    membership_fingerprint: str


@dataclass(frozen=True, slots=True)
class ProfileAttributionResult:
    claim_id: int
    claim_event_id: int
    normalized_name: str
    link_status: str
    linked_pastor_slug: str | None
    redirect_event_id: int | None


def list_unnamed_profile_attribution_candidates(
    database: Database,
    *,
    representative_limit: int = 6,
) -> tuple[ProfileAttributionCandidate, ...]:
    candidates: list[ProfileAttributionCandidate] = []
    for profile in database.list_speaker_profiles():
        if (
            profile.created_reason not in _REVIEWABLE_PROFILE_REASONS
            or database.resolve_speaker_profile_id(profile.id) != profile.id
        ):
            continue
        member_ids = database.list_effective_observation_ids_for_profile(
            profile.id
        )
        if not member_ids or _profile_explicit_names(database, member_ids):
            continue
        evidence = _profile_evidence(
            database,
            member_ids,
            representative_limit=representative_limit,
        )
        if evidence:
            candidates.append(
                ProfileAttributionCandidate(
                    profile_id=profile.id,
                    member_count=len(member_ids),
                    evidence=evidence,
                    membership_fingerprint=_membership_fingerprint(
                        database,
                        profile.id,
                        member_ids,
                    ),
                )
            )
    return tuple(
        sorted(candidates, key=lambda item: (-item.member_count, item.profile_id))
    )


def get_profile_attribution_candidate(
    database: Database,
    profile_id: int,
    *,
    representative_limit: int = 6,
) -> ProfileAttributionCandidate:
    profile = database.get_speaker_profile(profile_id)
    if profile is None or profile.created_reason not in _REVIEWABLE_PROFILE_REASONS:
        raise ValueError(f"Profile {profile_id} is not a reviewable speaker profile")
    if database.resolve_speaker_profile_id(profile_id) != profile_id:
        raise ValueError(f"Profile {profile_id} redirects to another profile")
    member_ids = database.list_effective_observation_ids_for_profile(profile_id)
    if not member_ids:
        raise ValueError(f"Profile {profile_id} has no effective members")
    evidence = _profile_evidence(
        database,
        member_ids,
        representative_limit=representative_limit,
    )
    if not evidence:
        raise ValueError(f"Profile {profile_id} has no reviewable backing videos")
    return ProfileAttributionCandidate(
        profile_id,
        len(member_ids),
        evidence,
        _membership_fingerprint(database, profile_id, member_ids),
    )


def load_profile_attribution_deferrals(root: Path) -> frozenset[str]:
    """Load valid exact-membership deferrals; malformed events fail closed."""
    deferred: set[str] = set()
    if not root.is_dir():
        return frozenset()
    for path in sorted(root.glob("profile-*/*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        event_key = payload.get("event_key")
        stable = {
            key: payload.get(key)
            for key in (
                "version",
                "profile_id",
                "membership_fingerprint",
                "reviewer",
                "reason",
            )
        }
        if (
            payload.get("version") == PROFILE_ATTRIBUTION_REVIEW_VERSION
            and payload.get("decision") == "deferred_unverifiable"
            and isinstance(payload.get("membership_fingerprint"), str)
            and event_key == _sha256(stable)
        ):
            deferred.add(payload["membership_fingerprint"])
    return frozenset(deferred)


def record_profile_attribution_deferral(
    candidate: ProfileAttributionCandidate,
    *,
    reviewer: str,
    root: Path,
    reason: str = "identity_cannot_be_verified_from_current_evidence",
) -> Path:
    reviewer = reviewer.strip()
    reason = reason.strip()
    if not reviewer or not reason:
        raise ValueError("reviewer and deferral reason are required")
    stable = {
        "version": PROFILE_ATTRIBUTION_REVIEW_VERSION,
        "profile_id": candidate.profile_id,
        "membership_fingerprint": candidate.membership_fingerprint,
        "reviewer": reviewer,
        "reason": reason,
    }
    event_key = _sha256(stable)
    destination = (
        root.expanduser().resolve()
        / f"profile-{candidate.profile_id}"
        / f"{event_key}.json"
    )
    if destination.exists():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **stable,
        "decision": "deferred_unverifiable",
        "event_key": event_key,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    temporary = destination.with_suffix(".json.partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def write_profile_attribution_packet(
    candidate: ProfileAttributionCandidate,
    destination: Path,
) -> Path:
    path = destination.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    cards = []
    for index, evidence in enumerate(candidate.evidence, start=1):
        timestamp_url = (
            f"{evidence.video_url}&t={evidence.timestamp_seconds}s"
            if "?" in evidence.video_url
            else f"{evidence.video_url}?t={evidence.timestamp_seconds}s"
        )
        thumbnail = (
            "https://i.ytimg.com/vi/"
            f"{evidence.youtube_video_id}/hqdefault.jpg"
        )
        cards.append(
            "<section><h2>Evidence video "
            f"{index}: {html.escape(evidence.title)}</h2>"
            f'<a class="video" href="{html.escape(timestamp_url)}" '
            'target="_blank" rel="noopener">'
            f'<img src="{html.escape(thumbnail)}" '
            f'alt="Open {html.escape(evidence.title)} on YouTube">'
            '<span>Watch on YouTube at the sermon timestamp</span></a>'
            f'<p><a href="{html.escape(timestamp_url)}" target="_blank" '
            'rel="noopener">Open timestamped video</a>'
            f" · observation {evidence.observation_id}</p></section>"
        )
    document = """<!doctype html><html><head><meta charset="utf-8">
<title>Speaker profile attribution</title><style>
body{font-family:system-ui;margin:2rem auto;max-width:1100px;padding:0 1rem}
section{margin:2rem 0}.video{display:block;position:relative;background:#222}
.video img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover;opacity:.82}
.video span{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
background:#c00;color:#fff;padding:.8rem 1.1rem;border-radius:.5rem;font-weight:700}
</style></head><body>""" + (
        f"<h1>Name speaker profile {candidate.profile_id}</h1>"
        f"<p>{candidate.member_count} member recordings. Use the terminal prompt "
        "to choose the evidence video and enter the speaker name.</p>"
        + "".join(cards)
        + "</body></html>"
    )
    path.write_text(document, encoding="utf-8")
    return path


def apply_reviewed_profile_attribution(
    database: Database,
    *,
    profile_id: int,
    observation_id: int,
    display_name: str,
    reviewer: str,
    reason: str,
    packet_path: Path,
) -> ProfileAttributionResult:
    name = display_name.strip()
    normalized_name = normalize_person_name(name)
    reviewer = reviewer.strip()
    reason = reason.strip()
    if not name or not normalized_name or not reviewer or not reason:
        raise ValueError("name, reviewer, and reason are required")
    if database.resolve_speaker_profile_id(profile_id) != profile_id:
        raise ValueError(f"Profile {profile_id} is not canonical")
    member_ids = set(
        database.list_effective_observation_ids_for_profile(profile_id)
    )
    if observation_id not in member_ids:
        raise ValueError("attribution evidence must be a current profile member")
    existing_names = _profile_explicit_names(database, member_ids)
    if existing_names and existing_names != {normalized_name}:
        raise ValueError(
            "profile has conflicting explicit attribution: "
            + ", ".join(sorted(existing_names))
        )
    observation = database.get_speaker_observation(observation_id)
    if observation is None:
        raise ValueError(f"Unknown speaker observation: {observation_id}")
    provenance: dict[str, Any] = {
        "version": PROFILE_ATTRIBUTION_REVIEW_VERSION,
        "profile_id": profile_id,
        "observation_id": observation_id,
        "observation_fingerprint": observation.input_fingerprint,
        "reviewer": reviewer,
        "reason": reason,
        "packet_path": str(packet_path.expanduser().resolve()),
    }
    event_key = _sha256({**provenance, "normalized_name": normalized_name})
    claim = database.add_speaker_name_claim(
        video_id=observation.video_id,
        observation_id=observation.id,
        display_name=name,
        normalized_name=normalized_name,
        claim_kind="reviewed_profile_attribution",
        channel="manual_review",
        explicit_speaker_attribution=True,
        correlation_group_id=f"reviewed-profile:{profile_id}:{normalized_name}",
        provenance_json=json.dumps(provenance, sort_keys=True),
        artifact_path=str(packet_path.expanduser().resolve()),
        claim_fingerprint=_sha256(
            {"kind": "reviewed_profile_attribution_claim", "event_key": event_key}
        ),
        extractor_version=PROFILE_ATTRIBUTION_REVIEW_VERSION,
    )
    claim_event_id = record_name_claim_review(
        database,
        claim_id=claim.id,
        profile_id=profile_id,
        attach=True,
        reviewer=reviewer,
        reason=reason,
        review_event_key=f"{event_key}:claim-attach",
    )
    matching_pastors = [
        pastor
        for pastor in database.list_pastors()
        if normalize_person_name(pastor.display_name) == normalized_name
    ]
    link_status = "no_configured_pastor_match"
    linked_slug = None
    redirect_event_id = None
    if len(matching_pastors) > 1:
        link_status = "multiple_configured_pastor_matches"
    elif len(matching_pastors) == 1:
        pastor = matching_pastors[0]
        configured_id = database.get_pastor_speaker_profile_id(pastor.id)
        if configured_id is None:
            link_status = "configured_pastor_unbound"
        else:
            resolved = database.resolve_speaker_profile_id(configured_id)
            if resolved == profile_id:
                link_status = "already_linked"
                linked_slug = pastor.slug
            elif resolved != configured_id:
                link_status = "configured_pastor_linked_elsewhere"
            elif database.list_effective_observation_ids_for_profile(configured_id):
                link_status = "configured_profile_has_members"
            else:
                redirect_event_id = record_profile_redirect(
                    database,
                    from_profile_id=configured_id,
                    to_profile_id=profile_id,
                    reviewer=reviewer,
                    reason=reason,
                    review_event_key=f"{event_key}:configured-link",
                )
                link_status = "linked"
                linked_slug = pastor.slug
    return ProfileAttributionResult(
        claim_id=claim.id,
        claim_event_id=claim_event_id,
        normalized_name=normalized_name,
        link_status=link_status,
        linked_pastor_slug=linked_slug,
        redirect_event_id=redirect_event_id,
    )


def _profile_explicit_names(database: Database, member_ids: set[int] | list[int]) -> set[str]:
    members = set(member_ids)
    return {
        claim.normalized_name.strip()
        for claim in database.list_speaker_name_claims()
        if claim.observation_id in members
        and claim.explicit_speaker_attribution
        and claim.normalized_name.strip()
    }


def _profile_evidence(
    database: Database,
    member_ids: list[int],
    *,
    representative_limit: int,
) -> tuple[ProfileAttributionEvidence, ...]:
    evidence: list[ProfileAttributionEvidence] = []
    for observation_id in member_ids:
        observation = database.get_speaker_observation(observation_id)
        video = (
            database.get_video_by_id(observation.video_id)
            if observation is not None
            else None
        )
        if observation is None or video is None:
            continue
        evidence.append(
            ProfileAttributionEvidence(
                observation_id=observation.id,
                observation_fingerprint=observation.input_fingerprint,
                youtube_video_id=video.youtube_video_id,
                title=video.title,
                video_url=video.url,
                timestamp_seconds=max(0, int(observation.start_seconds)),
            )
        )
    return tuple(evidence[:representative_limit])


def _membership_fingerprint(
    database: Database,
    profile_id: int,
    member_ids: list[int],
) -> str:
    fingerprints = []
    for observation_id in sorted(member_ids):
        observation = database.get_speaker_observation(observation_id)
        if observation is not None:
            fingerprints.append(observation.input_fingerprint)
    return _sha256(
        {
            "profile_id": profile_id,
            "observation_fingerprints": fingerprints,
        }
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
