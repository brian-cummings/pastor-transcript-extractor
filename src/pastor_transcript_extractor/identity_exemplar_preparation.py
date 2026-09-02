from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


EXEMPLAR_PREPARATION_STATE_VERSION = "identity_exemplar_preparation_state_v1"


@dataclass(frozen=True, slots=True)
class ExemplarPreparationState:
    profile_id: int
    observation_id: int
    observation_fingerprint: str
    video_id: int
    youtube_video_id: str
    evidence_fingerprint: str
    stage: str
    outcome: str
    reason_code: str
    retry_policy: str
    repair_action: str | None
    automatic_retry_allowed: bool
    created_at: str


def exemplar_failure_policy(
    stage: str,
    reason_code: str,
) -> tuple[str, str | None, bool]:
    """Return retry policy, repair action, and automatic-retry permission."""
    if stage in {"media_registration", "media_verification"}:
        return "when_evidence_changes", "prepare_canonical_audio", True
    if stage in {"extraction_lookup", "transcript_span_selection"}:
        return "when_evidence_changes", "regenerate_extraction", False
    if stage == "activity_span_selection" and reason_code in {
        "too_few_activity_qualified_spans",
        "speech_grounded_spans_unavailable",
    }:
        return "human_review_required", "review_exemplar_spans", False
    if stage in {"observation_consistency", "profile_membership"}:
        return "human_review_required", "review_profile_evidence", False
    return "each_run", None, True


class ExemplarPreparationStateCache:
    def __init__(self, cache_root: Path):
        self.root = (
            cache_root.expanduser().resolve() / "exemplar-preparation-state"
        )

    @staticmethod
    def evidence_fingerprint(evidence: Mapping[str, Any]) -> str:
        return _sha256_json(dict(evidence))

    def unchanged_deterministic_failure(
        self,
        *,
        profile_id: int,
        observation_fingerprint: str,
        evidence_fingerprint: str,
    ) -> ExemplarPreparationState | None:
        state = self.latest_for_observation(
            profile_id=profile_id,
            observation_fingerprint=observation_fingerprint,
        )
        if (
            state is None
            or state.evidence_fingerprint != evidence_fingerprint
            or state.outcome != "blocked"
            or state.retry_policy == "each_run"
        ):
            return None
        return state

    def record(
        self,
        *,
        profile_id: int,
        observation_id: int,
        observation_fingerprint: str,
        video_id: int,
        youtube_video_id: str,
        evidence: Mapping[str, Any],
        stage: str,
        outcome: str,
        reason_code: str,
    ) -> ExemplarPreparationState:
        if outcome not in {"eligible", "blocked"}:
            raise ValueError("exemplar preparation outcome must be eligible or blocked")
        evidence_fingerprint = self.evidence_fingerprint(evidence)
        if outcome == "eligible":
            retry_policy, repair_action, automatic_retry_allowed = (
                "not_applicable",
                None,
                False,
            )
        else:
            retry_policy, repair_action, automatic_retry_allowed = (
                exemplar_failure_policy(stage, reason_code)
            )
        state = ExemplarPreparationState(
            profile_id=profile_id,
            observation_id=observation_id,
            observation_fingerprint=observation_fingerprint,
            video_id=video_id,
            youtube_video_id=youtube_video_id,
            evidence_fingerprint=evidence_fingerprint,
            stage=stage,
            outcome=outcome,
            reason_code=reason_code,
            retry_policy=retry_policy,
            repair_action=repair_action,
            automatic_retry_allowed=automatic_retry_allowed,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        previous = self.latest_for_observation(
            profile_id=profile_id,
            observation_fingerprint=observation_fingerprint,
        )
        if previous is not None and all(
            getattr(previous, field) == getattr(state, field)
            for field in ExemplarPreparationState.__dataclass_fields__
            if field != "created_at"
        ):
            return previous
        stable_input = {
            "state_version": EXEMPLAR_PREPARATION_STATE_VERSION,
            "evidence": dict(evidence),
            **{
                key: value
                for key, value in asdict(state).items()
                if key != "created_at"
            },
            "previous_state": (
                {
                    "created_at": previous.created_at,
                    "evidence_fingerprint": previous.evidence_fingerprint,
                    "outcome": previous.outcome,
                    "stage": previous.stage,
                    "reason_code": previous.reason_code,
                }
                if previous is not None
                else None
            ),
        }
        result_fingerprint = _sha256_json(stable_input)
        destination = (
            self.root
            / f"profile-{profile_id}"
            / observation_fingerprint[:16]
            / f"{result_fingerprint}.json"
        )
        if destination.exists():
            return _load_state(destination) or state
        payload = {
            "schema_version": 1,
            "artifact_kind": "identity_exemplar_preparation_state",
            **stable_input,
            "created_at": state.created_at,
        }
        payload["result_sha256"] = _sha256_json(payload)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".json.partial")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
        return state

    def latest_for_observation(
        self,
        *,
        profile_id: int,
        observation_fingerprint: str,
    ) -> ExemplarPreparationState | None:
        directory = (
            self.root
            / f"profile-{profile_id}"
            / observation_fingerprint[:16]
        )
        return _latest_state(directory.glob("*.json"))

    def latest_states(self) -> tuple[ExemplarPreparationState, ...]:
        latest: dict[tuple[int, str], ExemplarPreparationState] = {}
        if not self.root.is_dir():
            return ()
        for path in self.root.glob("profile-*/*/*.json"):
            state = _load_state(path)
            if state is None:
                continue
            key = (state.profile_id, state.observation_fingerprint)
            existing = latest.get(key)
            if existing is None or state.created_at > existing.created_at:
                latest[key] = state
        return tuple(
            sorted(
                latest.values(),
                key=lambda state: (state.profile_id, state.observation_id),
            )
        )

    def pending_automatic_repairs(
        self,
    ) -> tuple[ExemplarPreparationState, ...]:
        return tuple(
            state
            for state in self.latest_states()
            if state.outcome == "blocked"
            and state.automatic_retry_allowed
            and state.repair_action is not None
            and not self._repair_attempt_path(state).exists()
        )

    def record_repair_attempt(
        self,
        state: ExemplarPreparationState,
        *,
        outcome: str,
        detail: str,
    ) -> Path:
        destination = self._repair_attempt_path(state)
        if destination.exists():
            return destination
        payload = {
            "schema_version": 1,
            "artifact_kind": "identity_exemplar_repair_attempt",
            "state_version": EXEMPLAR_PREPARATION_STATE_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "profile_id": state.profile_id,
            "observation_id": state.observation_id,
            "observation_fingerprint": state.observation_fingerprint,
            "evidence_fingerprint": state.evidence_fingerprint,
            "repair_action": state.repair_action,
            "outcome": outcome,
            "detail": detail,
        }
        payload["result_sha256"] = _sha256_json(payload)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".json.partial")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
        return destination

    def _repair_attempt_path(
        self,
        state: ExemplarPreparationState,
    ) -> Path:
        return (
            self.root
            / f"profile-{state.profile_id}"
            / state.observation_fingerprint[:16]
            / f"repair-{state.evidence_fingerprint}.json"
        )


def _latest_state(paths) -> ExemplarPreparationState | None:
    states = [state for path in paths if (state := _load_state(path)) is not None]
    return max(states, key=lambda state: state.created_at, default=None)


def _load_state(path: Path) -> ExemplarPreparationState | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected = payload.get("result_sha256")
        unhashed = dict(payload)
        unhashed.pop("result_sha256", None)
        if (
            payload.get("artifact_kind")
            != "identity_exemplar_preparation_state"
            or payload.get("state_version")
            != EXEMPLAR_PREPARATION_STATE_VERSION
            or not isinstance(expected, str)
            or _sha256_json(unhashed) != expected
        ):
            return None
        return ExemplarPreparationState(
            **{
                field: payload[field]
                for field in ExemplarPreparationState.__dataclass_fields__
            }
        )
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None


def _sha256_json(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
