"""Grounded TypeSafe/Jev speaker-profile metadata name attribution."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from pastor_transcript_extractor.identity_attribution import extract_person_name_spans
from pastor_transcript_extractor.speaker_profile_metadata_attribution import (
    ProfileMetadataAttribution,
    ProfileMetadataAttributionRun,
    ProfileMetadataFailure,
    ProfileMetadataInput,
    _load_artifact,
    _sha256,
    _valid_person_name,
    _write_artifact,
    build_profile_metadata_inputs,
)
from pastor_transcript_extractor.speaker_registry import normalize_person_name
from pastor_transcript_extractor.storage import Database


TYPESAFE_ATTRIBUTION_VERSION = "profile_metadata_attribution_typesafe_v2"
TYPESAFE_QUESTION_VERSION = "profile-metadata-role-choice-v2"
TYPESAFE_POLICY_VERSION = "profile-metadata-grounded-policy-v1"
DEFAULT_TYPESAFE_MODEL = "jev-1.13.0"
DEFAULT_CONFIDENCE_THRESHOLD = 0.70
DEFAULT_SPEAKER_PROBABILITY_THRESHOLD = 0.70
_CHOICES = frozenset({"sermon_speaker", "other_person", "ambiguous"})


def role_question(candidate_path: str) -> dict[str, Any]:
    return {
        "instructions": {
            "task": (
                f"Classify the role of the exact person-name occurrence at "
                f"`{candidate_path}` using only its supplied metadata context."
            ),
            "scope": (
                "Decide whether this occurrence explicitly credits the person as "
                "the principal sermon speaker for this recording. Do not decide "
                "whether recordings contain the same voice and do not infer or "
                "generate any name."
            ),
        },
        "criteria": {
            "sermon_speaker": (
                "The metadata explicitly credits this person as preaching, speaking, "
                "delivering, presenting, or giving the sermon/message in this recording."
            ),
            "other_person": (
                "The person is a subject, honoree, musician, host, quoted person, "
                "participant, or otherwise mentioned without being credited as the "
                "principal sermon speaker."
            ),
            "ambiguous": (
                "The context is insufficient, merely a bare name/byline of uncertain "
                "role, or supports more than one interpretation."
            ),
        },
    }


@dataclass(frozen=True, slots=True)
class ProfileNameCandidate:
    occurrence_id: str
    exact_text: str
    normalized_name: str
    youtube_video_id: str
    field_path: str
    field_text: str
    start: int
    end: int
    context: str

    def state_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TypeSafeNameJudgment:
    choice: str
    probabilities: Mapping[str, float]
    confidence: float
    resolved_model_id: str


class TypeSafeNameAttributionProvider(Protocol):
    model: str
    model_digest: str

    def classify(
        self,
        candidates: Sequence[ProfileNameCandidate],
    ) -> Mapping[str, TypeSafeNameJudgment]: ...


class TypeSafeSdkNameAttributionProvider:
    """Small SDK adapter; all extraction and policy remain in ordinary code."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_TYPESAFE_MODEL,
        timeout_seconds: float = 45.0,
    ) -> None:
        if not os.environ.get("TYPESAFE_API_KEY"):
            raise RuntimeError(
                "TYPESAFE_API_KEY is required for TypeSafe metadata attribution"
            )
        try:
            from typesafe_sdk import Choice, TypeSafeClient  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "Install the optional dependency: pip install -e '.[typesafe]'"
            ) from exc
        self.model = model
        # A pinned model id is its durable model identity. Callers with a separately
        # resolved deployment digest can provide their own provider implementation.
        self.model_digest = model
        self.timeout_seconds = timeout_seconds
        self._Choice = Choice
        self._client = TypeSafeClient(model=model, timeout=timeout_seconds)

    def classify(
        self,
        candidates: Sequence[ProfileNameCandidate],
    ) -> Mapping[str, TypeSafeNameJudgment]:
        state = {"candidate_occurrences": [item.state_payload() for item in candidates]}
        question_ids = {
            f"candidate_{index}": candidate.occurrence_id
            for index, candidate in enumerate(candidates)
        }
        questions = {
            question_id: self._Choice(
                **role_question(f"candidate_occurrences[{index}]")
            )
            for index, question_id in enumerate(question_ids)
        }
        response = self._client.system_one(
            state,
            questions,
            model=self.model,
            timeout=self.timeout_seconds,
        )
        resolved_model = str(getattr(response, "model", self.model))
        choices = getattr(response, "choices", None)
        if choices is None:
            choices = getattr(response, "answers", {})
        output: dict[str, TypeSafeNameJudgment] = {}
        for question_id, occurrence_id in question_ids.items():
            answer = choices[question_id]
            probabilities = dict(
                getattr(answer, "probabilities", getattr(answer, "distribution", {}))
            )
            output[occurrence_id] = TypeSafeNameJudgment(
                choice=str(answer.choice),
                probabilities={
                    str(key): float(value)
                    for key, value in probabilities.items()
                },
                confidence=float(answer.confidence),
                resolved_model_id=resolved_model,
            )
        return output


def extract_profile_name_candidates(
    candidate: ProfileMetadataInput,
) -> tuple[ProfileNameCandidate, ...]:
    occurrences: list[ProfileNameCandidate] = []
    for field in candidate.fields:
        # A channel name identifies the publisher, not the sermon speaker.
        if field.field_path == "video.channel_name":
            continue
        for span in extract_person_name_spans(
            field.text,
            include_bare=field.field_path == "raw_metadata.description",
        ):
            if not _valid_person_name(
                span.normalized_name,
                raw_name=span.exact_text,
            ):
                continue
            occurrence_id = _sha256(
                {
                    "youtube_video_id": field.youtube_video_id,
                    "field_path": field.field_path,
                    "field_text": field.text,
                    "start": span.start,
                    "end": span.end,
                    "exact_text": span.exact_text,
                }
            )[:24]
            occurrences.append(
                ProfileNameCandidate(
                    occurrence_id=occurrence_id,
                    exact_text=span.exact_text,
                    normalized_name=span.normalized_name,
                    youtube_video_id=field.youtube_video_id,
                    field_path=field.field_path,
                    field_text=field.text,
                    start=span.start,
                    end=span.end,
                    context=span.context,
                )
            )
    return tuple(occurrences)


def _candidate_key(normalized_name: str) -> str:
    """Merge harmless middle-initial variants without inventing any text."""
    tokens = normalized_name.split()
    if len(tokens) > 2:
        tokens = [
            token
            for index, token in enumerate(tokens)
            if index in {0, len(tokens) - 1} or len(token) > 1
        ]
    return " ".join(tokens)


def _cache_identity(
    profile: ProfileMetadataInput,
    occurrence: ProfileNameCandidate,
    provider: TypeSafeNameAttributionProvider,
) -> dict[str, Any]:
    return {
        "model": provider.model,
        "model_digest": provider.model_digest,
        "question_version": TYPESAFE_QUESTION_VERSION,
        "question": role_question("candidate_occurrence"),
        "policy_version": TYPESAFE_POLICY_VERSION,
        "membership_fingerprint": profile.membership_fingerprint,
        "metadata_input_fingerprint": profile.input_fingerprint,
        "candidate_state": occurrence.state_payload(),
    }


def _read_cached_judgment(
    path: Path,
    identity: Mapping[str, Any],
) -> TypeSafeNameJudgment | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("identity") != identity:
            return None
        answer = TypeSafeNameJudgment(**payload["answer"])
        _validate_judgment(answer)
        return answer
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ):
        return None


def _validate_judgment(answer: TypeSafeNameJudgment) -> None:
    if answer.choice not in _CHOICES:
        raise ValueError("TypeSafe returned an unknown metadata role choice")
    probabilities = {str(key): float(value) for key, value in answer.probabilities.items()}
    if set(probabilities) != _CHOICES or any(
        value < 0.0 or value > 1.0 for value in probabilities.values()
    ):
        raise ValueError("TypeSafe returned invalid metadata role probabilities")
    if abs(sum(probabilities.values()) - 1.0) > 0.02:
        raise ValueError("TypeSafe metadata role probabilities do not sum to one")
    if not 0.0 <= float(answer.confidence) <= 1.0:
        raise ValueError("TypeSafe returned invalid metadata role confidence")


def _write_cached_judgment(
    path: Path,
    identity: Mapping[str, Any],
    answer: TypeSafeNameJudgment,
) -> None:
    _write_artifact(
        path,
        {
            "schema_version": 1,
            "artifact_kind": "profile_metadata_typesafe_judgment",
            "identity": dict(identity),
            "answer": asdict(answer),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _aggregate(
    occurrences: Sequence[ProfileNameCandidate],
    judgments: Mapping[str, TypeSafeNameJudgment],
    *,
    confidence_threshold: float,
    speaker_probability_threshold: float,
    model_failed: bool,
) -> tuple[dict[str, Any], int]:
    displays: dict[str, list[str]] = {}
    supporting_videos: dict[str, set[str]] = {}
    supporting_occurrences: dict[str, list[ProfileNameCandidate]] = {}
    abstentions = 0
    for occurrence in occurrences:
        key = _candidate_key(occurrence.normalized_name)
        displays.setdefault(key, []).append(occurrence.exact_text)
        answer = judgments.get(occurrence.occurrence_id)
        if answer is None:
            abstentions += 1
            continue
        speaker_probability = float(answer.probabilities.get("sermon_speaker", 0.0))
        if (
            answer.choice == "sermon_speaker"
            and answer.confidence >= confidence_threshold
            and speaker_probability >= speaker_probability_threshold
        ):
            supporting_videos.setdefault(key, set()).add(occurrence.youtube_video_id)
            supporting_occurrences.setdefault(key, []).append(occurrence)
        elif answer.choice == "ambiguous" or answer.confidence < confidence_threshold:
            abstentions += 1

    if model_failed:
        return {
            "decision": "insufficient_evidence",
            "routing": "human_review_required",
            "proposed_name": None,
            "normalized_name": None,
            "reason_codes": ["model_unavailable"],
            "evidence": [],
            "conflicting_names": [],
            "supporting_recording_count": 0,
        }, abstentions

    supported = {
        key: videos for key, videos in supporting_videos.items() if len(videos) >= 2
    }
    if len(supported) == 1:
        key = next(iter(supported))
        # Return a source span, never model-produced text. Prefer the most common
        # spelling, then the shortest stable display when counts tie.
        display = sorted(
            set(displays[key]),
            key=lambda item: (-displays[key].count(item), len(item), item.casefold()),
        )[0]
        evidence = _evidence(supporting_occurrences[key])
        return {
            "decision": "propose_name",
            "routing": "human_confirmation_available",
            "proposed_name": display,
            "normalized_name": normalize_person_name(display),
            "reason_codes": [
                "consistent_speaker_credit",
                "repeated_name_across_recordings",
            ],
            "evidence": evidence,
            "conflicting_names": [],
            "supporting_recording_count": len(supported[key]),
        }, abstentions
    if len(supported) > 1:
        conflict_displays = [
            sorted(set(displays[key]), key=lambda item: (len(item), item.casefold()))[0]
            for key in sorted(supported)
        ]
        evidence = _evidence(
            [item for key in supported for item in supporting_occurrences[key]]
        )
        return {
            "decision": "conflicting_evidence",
            "routing": "human_review_required",
            "proposed_name": None,
            "normalized_name": None,
            "reason_codes": ["multiple_candidate_names"],
            "evidence": evidence,
            "conflicting_names": conflict_displays,
            "supporting_recording_count": len(
                {
                    item.youtube_video_id
                    for key in supported
                    for item in supporting_occurrences[key]
                }
            ),
        }, abstentions

    one_recording = any(len(videos) == 1 for videos in supporting_videos.values())
    reason = (
        "no_extracted_candidates"
        if not occurrences
        else "single_recording_only"
        if one_recording
        else "low_confidence_or_ambiguous"
        if abstentions
        else "no_speaker_credit"
    )
    return {
        "decision": "insufficient_evidence",
        "routing": "human_review_required",
        "proposed_name": None,
        "normalized_name": None,
        "reason_codes": [reason],
        "evidence": [],
        "conflicting_names": [],
        "supporting_recording_count": max(
            (len(value) for value in supporting_videos.values()),
            default=0,
        ),
    }, abstentions


def _evidence(occurrences: Sequence[ProfileNameCandidate]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in occurrences:
        key = (item.normalized_name, item.youtube_video_id, item.field_path)
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "youtube_video_id": item.youtube_video_id,
                "field_path": item.field_path,
                "exact_excerpt": item.context,
            }
        )
    return output


def _result_path(root: Path, candidate: ProfileMetadataInput) -> Path:
    return (
        root.expanduser().resolve()
        / f"profile-{candidate.profile_id}"
        / f"{candidate.input_fingerprint}.json"
    )


def _load_cached_result(
    path: Path,
    candidate: ProfileMetadataInput,
) -> ProfileMetadataAttribution | None:
    result = _load_artifact(path, cache_hit=True)
    if result is None or result.input_fingerprint != candidate.input_fingerprint:
        return None
    return result


def run_typesafe_profile_metadata_attribution(
    database: Database,
    root: Path,
    provider: TypeSafeNameAttributionProvider,
    *,
    profile_ids: frozenset[int] | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    speaker_probability_threshold: float = DEFAULT_SPEAKER_PROBABILITY_THRESHOLD,
    progress_callback: Callable[[int, int, int, str], None] | None = None,
) -> ProfileMetadataAttributionRun:
    base_inputs = build_profile_metadata_inputs(
        database,
        profile_ids=profile_ids,
        model=provider.model,
        model_digest=provider.model_digest,
    )
    candidates = tuple(
        ProfileMetadataInput(
            item.profile_id,
            item.membership_fingerprint,
            item.fields,
            _sha256(
                {
                    "version": TYPESAFE_ATTRIBUTION_VERSION,
                    "question_version": TYPESAFE_QUESTION_VERSION,
                    "policy_version": TYPESAFE_POLICY_VERSION,
                    "model": provider.model,
                    "model_digest": provider.model_digest,
                    "membership_fingerprint": item.membership_fingerprint,
                    "metadata_state": [asdict(field) for field in item.fields],
                }
            ),
        )
        for item in base_inputs
    )
    results: list[ProfileMetadataAttribution] = []
    failures: list[ProfileMetadataFailure] = []
    cache_hits = cache_misses = model_calls = failed = abstentions = 0
    for index, candidate in enumerate(candidates, start=1):
        path = _result_path(root, candidate)
        cached_result = _load_cached_result(path, candidate)
        if cached_result is not None:
            cache_hits += 1
            results.append(cached_result)
            if progress_callback:
                progress_callback(
                    index,
                    len(candidates),
                    candidate.profile_id,
                    f"cached:{cached_result.decision}",
                )
            continue

        occurrences = extract_profile_name_candidates(candidate)
        judgments: dict[str, TypeSafeNameJudgment] = {}
        missing: list[tuple[ProfileNameCandidate, dict[str, Any], Path]] = []
        cache_root = path.parent / "typesafe-cache"
        for occurrence in occurrences:
            identity = _cache_identity(candidate, occurrence, provider)
            cache_path = cache_root / f"{_sha256(identity)}.json"
            cached = _read_cached_judgment(cache_path, identity)
            if cached is not None:
                judgments[occurrence.occurrence_id] = cached
                cache_hits += 1
            else:
                missing.append((occurrence, identity, cache_path))
                cache_misses += 1

        model_failed = False
        error: Exception | None = None
        if missing:
            model_calls += 1
            try:
                assessed = provider.classify([item[0] for item in missing])
                for occurrence, identity, cache_path in missing:
                    answer = assessed.get(occurrence.occurrence_id)
                    if answer is None:
                        raise ValueError(
                            "TypeSafe omitted candidate "
                            f"{occurrence.occurrence_id}"
                        )
                    _validate_judgment(answer)
                    _write_cached_judgment(cache_path, identity, answer)
                    judgments[occurrence.occurrence_id] = answer
            except Exception as exc:  # SDK/service failures must fail closed.
                model_failed = True
                error = exc
                failed += 1

        validated, profile_abstentions = _aggregate(
            occurrences,
            judgments,
            confidence_threshold=confidence_threshold,
            speaker_probability_threshold=speaker_probability_threshold,
            model_failed=model_failed,
        )
        abstentions += profile_abstentions
        payload = {
            "schema_version": 1,
            "version": TYPESAFE_ATTRIBUTION_VERSION,
            "backend": "typesafe",
            "question_version": TYPESAFE_QUESTION_VERSION,
            "policy_version": TYPESAFE_POLICY_VERSION,
            "profile_id": candidate.profile_id,
            "membership_fingerprint": candidate.membership_fingerprint,
            "input_fingerprint": candidate.input_fingerprint,
            "model": provider.model,
            "model_digest": provider.model_digest,
            "candidate_occurrences": [item.state_payload() for item in occurrences],
            "judgments": {key: asdict(value) for key, value in judgments.items()},
            "policy": {
                "confidence_threshold": confidence_threshold,
                "speaker_probability_threshold": speaker_probability_threshold,
                "minimum_distinct_recordings": 2,
            },
            "result": validated,
            "result_sha256": _sha256(validated),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_artifact(path, payload)
        loaded = _load_artifact(path, cache_hit=False)
        if loaded is None:
            raise ValueError(f"could not replay TypeSafe metadata attribution: {path}")
        results.append(loaded)
        if error is not None:
            failure_path = path.with_suffix(".attempt.json")
            _write_artifact(
                failure_path,
                {
                    "schema_version": 1,
                    "artifact_kind": "profile_metadata_typesafe_failure",
                    "version": TYPESAFE_ATTRIBUTION_VERSION,
                    "profile_id": candidate.profile_id,
                    "input_fingerprint": candidate.input_fingerprint,
                    "model": provider.model,
                    "model_digest": provider.model_digest,
                    "error": {"type": type(error).__name__, "message": str(error)},
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            failures.append(
                ProfileMetadataFailure(
                    candidate.profile_id,
                    candidate.input_fingerprint,
                    type(error).__name__,
                    str(error),
                    failure_path,
                    False,
                )
            )
        if progress_callback:
            progress_callback(
                index,
                len(candidates),
                candidate.profile_id,
                loaded.decision,
            )

    counts = {
        key: 0
        for key in (
            "propose_name",
            "insufficient_evidence",
            "conflicting_evidence",
            "invalid_metadata",
        )
    }
    for result in results:
        counts[result.decision] += 1
    return ProfileMetadataAttributionRun(
        eligible=len(candidates),
        proposed=counts["propose_name"],
        insufficient_evidence=counts["insufficient_evidence"],
        conflicting_evidence=counts["conflicting_evidence"],
        invalid_metadata=counts["invalid_metadata"],
        cache_hits=cache_hits,
        model_calls=model_calls,
        failed=failed,
        results=tuple(results),
        failures=tuple(failures),
        abstentions=abstentions,
        cache_misses=cache_misses,
    )
