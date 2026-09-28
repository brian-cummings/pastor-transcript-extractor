"""TypeSafe/Jev recording verification and its shadow benchmark."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
from threading import Lock
import time
from typing import Any, Mapping, Protocol

from pastor_transcript_extractor.recording_verifier import (
    ARTIFACT_SCHEMA_VERSION,
    _excerpt,
    _selected_candidate,
    title_program_decision,
    validate_partition_access,
)
from pastor_transcript_extractor.sermon_classifier_typesafe import (
    TypeSafeBoundaryAnswer,
    TypeSafeBoundaryCandidate,
    TypeSafeBoundarySelection,
    TypeSafeBlockAnswer,
    TypeSafeFirstPassSermonClassifier,
    role_question,
)
from pastor_transcript_extractor.sermon_classification import HybridSermonResult, TranscriptBlock
from pastor_transcript_extractor.sermon_detection import SermonWindowResult
from pastor_transcript_extractor.segmentation import SegmentDraft
from pastor_transcript_extractor.storage import Database


QUESTION_SET_VERSION = "recording-verifier-typesafe-questions-v5-choice-boundaries"
POLICY_VERSION = "recording-verifier-typesafe-policy-v5-choice-boundaries"
COST_RATE_VERSION = "typesafe-jev-rate-unconfigured-v1"
CHOICES = (
    "worship_service_sermon", "childrens_story_or_interactive_object_lesson",
    "religious_education_or_bible_class", "multi_speaker_or_student_program",
    "non_sermon_event", "unclear",
)


@dataclass(frozen=True, slots=True)
class TypeSafeRecordingState:
    recording_title: str
    candidate_opening: str
    candidate_middle: str
    candidate_ending: str

    def judgment_payload(self) -> dict[str, Any]:
        """Return only the evidence needed to classify the selected candidate."""
        return {
            "recording_title": self.recording_title,
            "candidate": {
                "opening": self.candidate_opening,
                "middle": self.candidate_middle,
                "ending": self.candidate_ending,
            },
        }


@dataclass(frozen=True, slots=True)
class TypeSafeCase:
    video_id: str
    title: str
    expected_outcome: str
    partition: str
    state: TypeSafeRecordingState
    existing_12b: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class TypeSafeAnswers:
    choice: str
    choice_probabilities: Mapping[str, float]
    choice_confidence: float | None
    resolved_model_id: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class TypeSafeRecordingVerifier(Protocol):
    def assess(self, state: TypeSafeRecordingState) -> TypeSafeAnswers: ...


def build_typesafe_state(title: str, proposed: Mapping[str, Any]) -> TypeSafeRecordingState:
    """Reproduce ``build_evidence_packet`` sampling, retaining named fields."""
    start, end = _selected_candidate(dict(proposed))
    raw = proposed.get("segments")
    if not isinstance(raw, list):
        raise ValueError("proposed extraction has no transcript segments")
    segments = [item for item in raw if isinstance(item, dict)]
    midpoint, near_end = start + (end - start) / 2, max(start, end - 75)
    return TypeSafeRecordingState(
        recording_title=title,
        candidate_opening=_excerpt(segments, center_seconds=start + 75),
        candidate_middle=_excerpt(segments, center_seconds=midpoint),
        candidate_ending=_excerpt(segments, center_seconds=near_end),
    )


def question_inventory() -> dict[str, dict[str, Any]]:
    return {
        "recording_type": {
            "kind": "choice",
            "instructions": {
                "task": "Choose exactly one type for the selected `candidate` excerpts.",
                "scope": "Classify the candidate itself. Use `recording_title` only as supporting context.",
                "boundary": (
                    "A coherent Christian message is not automatically a sermon. Distinguish a worship-service "
                    "sermon from a children's story, interactive illustration, classroom lesson, or sequence of talks. "
                    "A preacher asking the congregation questions, receiving brief answers, inviting listeners to turn "
                    "to Bible passages, or assigning a practical exercise does not by itself make the message a class."
                ),
                "artifacts": (
                    "Do not infer speaker changes from rhetorical questions, quoted dialogue, duplicated captions, "
                    "or brief congregation responses."
                ),
            },
            "criteria": {
                "worship_service_sermon": {
                    "choose_when": (
                        "The candidate itself is one principal worship-service sermon: a preacher sustains and develops "
                        "biblical exposition, a theological theme, and/or pastoral application for the congregation."
                    ),
                    "still_choose_when": (
                        "The same principal preacher asks rhetorical or audience-address questions, receives brief "
                        "congregational answers, says to turn to passages, gives a step-by-step application exercise, "
                        "uses illustrations, makes an appeal, or closes with prayer."
                    ),
                },
                "childrens_story_or_interactive_object_lesson": (
                    "The candidate is a children's story, children's feature, interactive skit, dramatized parable, "
                    "or object lesson. Choose this even when it ends with Scripture, prayer, moral application, or a "
                    "short gospel message; those features do not turn the children's segment into the principal sermon."
                ),
                "religious_education_or_bible_class": {
                    "choose_when": (
                        "The candidate's dominant structure is an explicit lesson study, Bible class, Sabbath school "
                        "discussion, curriculum segment, or facilitated group study with substantive participant contributions."
                    ),
                    "do_not_choose_when": (
                        "One principal preacher sustains exposition and application while merely asking questions, "
                        "receiving short answers, directing listeners to Bible passages, or suggesting a practical exercise."
                    ),
                },
                "multi_speaker_or_student_program": (
                    "The candidate is a sequence of independent short talks or sermonettes, a student program, "
                    "or sustained speaker alternation/translation with no single principal sermon."
                ),
                "non_sermon_event": (
                    "The candidate is a concert, ceremony, graduation, technical test, announcements-only segment, "
                    "or another event segment without a principal sermon."
                ),
                "unclear": "The candidate excerpts conflict or do not contain enough evidence to choose another type.",
            },
        },
    }


@dataclass(frozen=True, slots=True)
class TypeSafeRecordingPolicy:
    version: str = POLICY_VERSION
    choice_probability_threshold: float = 0.85
    choice_confidence_threshold: float = 0.75

    def decide(
        self,
        choice: str,
        probabilities: Mapping[str, float],
        confidence: float | None,
        *,
        title_gate: str | None = None,
    ) -> tuple[str, list[str]]:
        if title_gate is not None:
            return "no_sermon", ["deterministic_negative_title_gate", title_gate]
        probability = probabilities.get(choice)
        if choice not in CHOICES or not isinstance(probability, (int, float)) or not 0 <= probability <= 1:
            return "abstain", ["invalid_or_incomplete_inference"]
        if choice == "unclear":
            return "abstain", ["model_selected_unclear"]
        if confidence is None or not 0 <= confidence <= 1:
            return "abstain", ["missing_or_invalid_choice_confidence"]
        if probability < self.choice_probability_threshold or confidence < self.choice_confidence_threshold:
            return "abstain", ["choice_below_automatic_threshold", choice]
        if choice == "worship_service_sermon":
            return "sermon", ["high_confidence_recording_type", choice]
        return "no_sermon", ["high_confidence_recording_type", choice]


@dataclass(frozen=True, slots=True)
class CostRate:
    """USD per million tokens; None explicitly means no published estimate."""
    version: str = COST_RATE_VERSION
    input_usd_per_million: float | None = None
    output_usd_per_million: float | None = None

    def estimate(self, input_tokens: int | None, output_tokens: int | None) -> float | None:
        if self.input_usd_per_million is None or self.output_usd_per_million is None:
            return None
        return ((input_tokens or 0) * self.input_usd_per_million + (output_tokens or 0) * self.output_usd_per_million) / 1_000_000


class TypeSafeSdkAdapter:
    """Thin optional-SDK adapter; isolated for inexpensive mocked tests."""
    def __init__(self, *, model: str, timeout_seconds: float = 45.0) -> None:
        if not os.environ.get("TYPESAFE_API_KEY"):
            raise RuntimeError("TYPESAFE_API_KEY is required for the TypeSafe recording verifier")
        try:
            from typesafe_sdk import Choice, Noul, TypeSafeClient  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("Install the optional dependency: pip install -e '.[typesafe]'") from exc
        self.model, self.timeout_seconds = model, timeout_seconds
        self._client, self._Choice, self._Noul = (
            TypeSafeClient(model=model, timeout=timeout_seconds), Choice, Noul
        )

    def assess(self, state: TypeSafeRecordingState) -> TypeSafeAnswers:
        choice = question_inventory()["recording_type"]
        questions = {
            "recording_type": self._Choice(
                instructions=choice["instructions"],
                criteria=choice["criteria"],
            )
        }
        result = self._client.system_one(
            state.judgment_payload(), questions, model=self.model, timeout=self.timeout_seconds
        )
        answer = result.choices["recording_type"]
        probabilities = getattr(answer, "probabilities", getattr(answer, "distribution", {}))
        probabilities = dict(probabilities)
        usage = getattr(result, "usage", None)
        return TypeSafeAnswers(str(answer.choice), {str(k): float(v) for k, v in probabilities.items()}, getattr(answer, "confidence", None), str(getattr(result, "model", self.model)), getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None))

    def assess_blocks(
        self,
        title: str,
        blocks: list[TranscriptBlock],
    ) -> Mapping[int, TypeSafeBlockAnswer]:
        question = role_question()
        state = {
            "recording_title": title,
            "blocks": [
                {
                    "block_id": block.block_id,
                    "text": block.text,
                }
                for block in blocks
            ],
        }
        questions = {
            f"block_{position}": self._Choice(
                instructions={
                    **question["instructions"],
                    "target": f"Classify only `blocks[{position}].text`.",
                },
                criteria=question["criteria"],
            )
            for position in range(len(blocks))
        }
        result = self._client.system_one(
            state,
            questions,
            model=self.model,
            timeout=self.timeout_seconds,
        )
        resolved_model = str(getattr(result, "model", self.model))
        return {
            block.block_id: TypeSafeBlockAnswer(
                choice=str(result.choices[f"block_{position}"].choice),
                probabilities={
                    str(key): float(value)
                    for key, value in dict(
                        getattr(
                            result.choices[f"block_{position}"],
                            "probabilities",
                            getattr(
                                result.choices[f"block_{position}"],
                                "distribution",
                                {},
                            ),
                        )
                    ).items()
                },
                confidence=getattr(
                    result.choices[f"block_{position}"], "confidence", None
                ),
                resolved_model_id=resolved_model,
            )
            for position, block in enumerate(blocks)
        }

    @staticmethod
    def _boundary_order(edge: str) -> str:
        return (
            "outside the principal sermon before the boundary and inside it after"
            if edge == "start"
            else "inside the principal sermon before the boundary and outside it after"
        )

    def select_boundary_candidate(
        self,
        title: str,
        edge: str,
        candidates: list[TypeSafeBoundaryCandidate],
    ) -> TypeSafeBoundarySelection:
        expected_order = self._boundary_order(edge)
        state = {
            "recording_title": title,
            "edge": edge,
        }
        criteria = {
            candidate.candidate_id: {
                "before_boundary_ends": candidate.before_text[-160:],
                "after_boundary_begins": candidate.after_text[:160],
            }
            for candidate in candidates
        }
        criteria["no_clear_boundary"] = (
            "None of the candidate cuts clearly shows the required semantic transition."
        )
        result = self._client.system_one(
            state,
            {
                "boundary": self._Choice(
                    instructions={
                        "task": (
                            f"Choose the single best {edge} boundary for the principal "
                            "worship-service sermon, or `no_clear_boundary`."
                        ),
                        "expected_order": expected_order,
                        "caption_handling": (
                            "Caption fragments may overlap or repeat. Choose by the "
                            "semantic handoff, not a duplicated fragment."
                        ),
                        "sermon_scope": (
                            "Keep closing or opening prayer, Scripture, appeal, and "
                            "benediction when integrated into the preacher's message."
                        ),
                    },
                    criteria=criteria,
                )
            },
            model=self.model,
            timeout=self.timeout_seconds,
        )
        resolved_model = str(getattr(result, "model", self.model))
        answer = result.choices["boundary"]
        probabilities = dict(
            getattr(answer, "probabilities", getattr(answer, "distribution", {}))
        )
        return TypeSafeBoundarySelection(
            choice=str(answer.choice),
            probabilities={str(key): float(value) for key, value in probabilities.items()},
            confidence=getattr(answer, "confidence", None),
            resolved_model_id=resolved_model,
        )

    def validate_boundary_candidate(
        self,
        title: str,
        edge: str,
        candidate: TypeSafeBoundaryCandidate,
    ) -> TypeSafeBoundaryAnswer:
        if edge == "start":
            statement = (
                "`before_boundary` is still a pre-sermon service element, and "
                "`after_boundary` begins the principal preacher's sustained message "
                "or its integrated opening Scripture or prayer."
            )
            true_criteria = (
                "The cut keeps welcomes, announcements, music, separate prayer, and "
                "speaker introduction before the sermon while retaining the beginning "
                "of the principal message after it."
            )
            false_criteria = (
                "The principal message already begins before the cut, does not begin "
                "after it, or both excerpts remain the same service element."
            )
        else:
            statement = (
                "`before_boundary` continues or completes the principal message's "
                "concluding material, and `after_boundary` begins a distinct service "
                "activity that is no longer part of that message."
            )
            true_criteria = (
                "The cut retains the complete integrated conclusion before it, whether "
                "that conclusion is preaching, appeal, prayer, Scripture, or benediction, "
                "and places a genuinely new service element after it."
            )
            false_criteria = (
                "The same message or its integrated conclusion continues materially after "
                "the cut; a distinct service activity begins before it; or no semantic "
                "handoff occurs."
            )
        result = self._client.system_one(
            {
                "recording_title": title,
                "edge": edge,
                "before_boundary": candidate.before_text,
                "after_boundary": candidate.after_text,
            },
            {
                "valid_boundary": self._Noul(
                    instructions={
                        "statement_to_evaluate": statement,
                        "caption_handling": (
                            "Ignore repeated or overlapping caption fragments and judge "
                            "the semantic handoff between the named excerpts."
                        ),
                    },
                    criteria={
                        "true": true_criteria,
                        "false": false_criteria,
                    },
                )
            },
            model=self.model,
            timeout=self.timeout_seconds,
        )
        return TypeSafeBoundaryAnswer(
            transition_probability=float(result.nouls["valid_boundary"].noul),
            resolved_model_id=str(getattr(result, "model", self.model)),
        )


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class TypeSafeCache:
    def __init__(self, root: Path) -> None: self.root = root
    def identity(self, state: TypeSafeRecordingState, model: str, configuration: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return {"state": state.judgment_payload(), "question_set_version": QUESTION_SET_VERSION, "questions": question_inventory(), "model": model, "configuration": dict(configuration or {})}
    def get_or_assess(self, client: TypeSafeRecordingVerifier, state: TypeSafeRecordingState, model: str) -> tuple[TypeSafeAnswers, bool, str]:
        identity = self.identity(state, model)
        key = _hash(identity); path = self.root / re.sub(r"[^A-Za-z0-9_.-]+", "_", model) / f"{key}.json"
        if path.exists():
            data = json.loads(path.read_text())
            return TypeSafeAnswers(**data["answers"]), True, key
        answer = client.assess(state)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"identity": identity, "answers": asdict(answer)}, indent=2, sort_keys=True))
        return answer, False, key


class TypeSafeProductionRecordingVerifier:
    """Adapt the frozen Jev policy to the production verification artifact."""

    prompt_version = QUESTION_SET_VERSION
    policy_version = POLICY_VERSION
    source = "typesafe_recording_verifier"

    def __init__(
        self,
        *,
        model: str = "jev-1.13.0",
        timeout_seconds: float = 45.0,
        client: TypeSafeRecordingVerifier | None = None,
        policy: TypeSafeRecordingPolicy = TypeSafeRecordingPolicy(),
    ) -> None:
        self.model = model
        self.client = client or TypeSafeSdkAdapter(
            model=model,
            timeout_seconds=timeout_seconds,
        )
        self.policy = policy
        self._lock = Lock()
        self.first_pass = (
            TypeSafeFirstPassSermonClassifier(
                model=model,
                client=self.client,
                lock=self._lock,
            )
            if callable(getattr(self.client, "assess_blocks", None))
            else None
        )

    def classify_sermon(
        self,
        drafts: list[SegmentDraft],
        rule_window: SermonWindowResult,
        *,
        title: str,
        cache_dir: Path,
        progress: Any | None = None,
    ) -> HybridSermonResult | None:
        """Run the cached Jev-first locator when the client supports block judgments."""
        if self.first_pass is None:
            return None
        return self.first_pass.classify_sermon(
            drafts,
            rule_window,
            title=title,
            cache_dir=cache_dir,
            progress=progress,
        )

    def verify(
        self,
        *,
        title: str,
        proposed: dict[str, Any],
        cache_dir: Path,
    ) -> dict[str, Any]:
        state = build_typesafe_state(title, proposed)
        state_hash = _hash(state.judgment_payload())
        title_gate = title_program_decision(title)
        if title_gate is not None:
            return _production_artifact(
                state_hash=state_hash,
                model=None,
                source="deterministic_title_gate",
                decision=title_gate,
                predicted_outcome="no_sermon",
                confidence="high",
                reason_codes=_negative_reason_codes(title_gate),
                policy_reason_codes=["deterministic_negative_title_gate", title_gate],
                cache_hit=False,
            )
        try:
            with self._lock:
                answers, cache_hit, _ = TypeSafeCache(cache_dir).get_or_assess(
                    self.client,
                    state,
                    self.model,
                )
            verdict, policy_reasons = self.policy.decide(
                answers.choice,
                answers.choice_probabilities,
                answers.choice_confidence,
            )
            automatic = verdict in {"sermon", "no_sermon"}
            decision = (
                "worship_service_sermon"
                if verdict == "sermon"
                else _production_negative_decision(answers.choice)
                if verdict == "no_sermon"
                else "unclear"
            )
            reason_codes = (
                ["single_sustained_message"]
                if verdict == "sermon"
                else _negative_reason_codes(answers.choice)
                if verdict == "no_sermon"
                else ["insufficient_recording_context"]
            )
            return _production_artifact(
                state_hash=state_hash,
                model=answers.resolved_model_id,
                source=self.source,
                decision=decision,
                predicted_outcome=verdict if automatic else None,
                confidence="high" if automatic else "low",
                reason_codes=reason_codes,
                policy_reason_codes=policy_reasons,
                cache_hit=cache_hit,
                model_verdict={
                    "choice": answers.choice,
                    "probabilities": dict(answers.choice_probabilities),
                    "confidence": answers.choice_confidence,
                },
                input_tokens=answers.input_tokens,
                output_tokens=answers.output_tokens,
            )
        except Exception as error:
            return _production_artifact(
                state_hash=state_hash,
                model=self.model,
                source="unresolved",
                decision="unclear",
                predicted_outcome=None,
                confidence="low",
                reason_codes=["insufficient_recording_context"],
                policy_reason_codes=["invalid_or_failed_inference"],
                cache_hit=False,
                error=f"{type(error).__name__}: {error}",
            )

    def reuse_local_artifact(
        self,
        *,
        title: str,
        proposed: Mapping[str, Any],
        artifact: object,
    ) -> dict[str, Any] | None:
        """Return a compatible persisted result without making a Jev request."""
        if not isinstance(artifact, dict):
            return None
        state = build_typesafe_state(title, proposed)
        if (
            artifact.get("source") != self.source
            or artifact.get("model_digest") != self.model
            or artifact.get("prompt_version") != self.prompt_version
            or artifact.get("policy_version") != self.policy_version
            or artifact.get("evidence_packet_hash") != _hash(state.judgment_payload())
            or artifact.get("error") is not None
        ):
            return None
        cached = dict(artifact)
        cached["cache_hit"] = True
        return cached


def _production_negative_decision(choice: str) -> str:
    if choice == "childrens_story_or_interactive_object_lesson":
        return "non_sermon_event"
    return choice


def _negative_reason_codes(choice: str) -> list[str]:
    return {
        "religious_education_or_bible_class": ["lesson_or_curriculum_structure"],
        "multi_speaker_or_student_program": ["multiple_short_speakers_or_sermonettes"],
        "non_sermon_event": ["ceremony_concert_or_technical_event"],
        "childrens_story_or_interactive_object_lesson": [
            "childrens_story_or_interactive_object_lesson"
        ],
    }.get(choice, ["insufficient_recording_context"])


def _production_artifact(
    *,
    state_hash: str,
    model: str | None,
    source: str,
    decision: str,
    predicted_outcome: str | None,
    confidence: str,
    reason_codes: list[str],
    policy_reason_codes: list[str],
    cache_hit: bool,
    model_verdict: Mapping[str, Any] | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "prompt_version": QUESTION_SET_VERSION,
        "policy_version": POLICY_VERSION,
        "model": model,
        "model_digest": model,
        "source": source,
        "decision": decision,
        "confidence": confidence,
        "reason_codes": reason_codes,
        "model_verdict": dict(model_verdict) if model_verdict is not None else None,
        "continuity_follow_up": None,
        "sermon_specific_reason_codes": [],
        "contradictory_reason_codes": (
            reason_codes if predicted_outcome == "no_sermon" else []
        ),
        "policy_reason_codes": policy_reason_codes,
        "predicted_outcome": predicted_outcome,
        "cache_hit": cache_hit,
        "evidence_packet_hash": state_hash,
        "raw_response": None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "error": error,
    }


def load_frozen_12b_baseline(root: Path) -> dict[str, Mapping[str, Any]]:
    """Use persisted reports, selecting the latest run for each partition."""
    reports: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for path in root.glob("*/results.json"):
        data = json.loads(path.read_text()); partition = data.get("evaluation_partition")
        if isinstance(partition, str) and (previous := reports.get(partition)) is None or (isinstance(partition, str) and str(data.get("run_id", "")) > previous[0]): reports[partition] = (str(data.get("run_id", "")), data)
    return {str(item["video_id"]): item for _, report in reports.values() for item in report.get("model_result", {}).get("results", []) if isinstance(item, dict) and isinstance(item.get("video_id"), str)}


def load_typesafe_cases(database: Database, fixture_dir: Path, *, partition: str, baseline_root: Path) -> list[TypeSafeCase]:
    baseline = load_frozen_12b_baseline(baseline_root); cases: list[TypeSafeCase] = []
    for path in sorted(fixture_dir.glob("*.json")):
        fixture = json.loads(path.read_text()); manifest = fixture.get("selection_manifest")
        fixture_partition = str(manifest.get("evaluation_partition")) if isinstance(manifest, dict) and manifest.get("evaluation_partition") else "legacy"
        if fixture_partition != partition: continue
        video_id = str(fixture.get("video_id")); video = database.get_video_by_youtube_id(video_id)
        if video is None: raise ValueError(f"fixture video {video_id} is not in the database")
        extraction = database.get_latest_extraction_result_for_video(video.id)
        if extraction is None or not extraction.proposed_json_path: raise ValueError(f"fixture video {video_id} has no proposed extraction")
        proposed = json.loads(Path(extraction.proposed_json_path).read_text())
        if not isinstance(proposed.get("final_disposition"), dict) or proposed["final_disposition"].get("status") != "review_required": continue
        cases.append(TypeSafeCase(video_id, video.title, str(fixture.get("expected_outcome")), partition, build_typesafe_state(video.title, proposed), baseline.get(video_id)))
    return cases


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values: return None
    rank = math.ceil(percentile * len(values)) - 1
    return sorted(values)[min(len(values) - 1, max(0, rank))]


def run_benchmark(cases: list[TypeSafeCase], client: TypeSafeRecordingVerifier, *, model: str, cache: TypeSafeCache, policy: TypeSafeRecordingPolicy = TypeSafeRecordingPolicy(), cost_rate: CostRate = CostRate()) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for case in cases:
        title_gate = title_program_decision(case.title); started = time.perf_counter()
        try:
            answers, hit, state_key = cache.get_or_assess(client, case.state, model)
            verdict, reasons = policy.decide(
                answers.choice,
                answers.choice_probabilities,
                answers.choice_confidence,
                title_gate=title_gate,
            )
            choice_outcome = "sermon" if answers.choice == "worship_service_sermon" else "no_sermon"
            choice_agrees = choice_outcome == verdict
            error = None
        except Exception as exc:
            answers = None; hit = False; state_key = _hash(case.state.judgment_payload()); verdict, reasons = "abstain", ["inference_failure"]
            choice_agrees = None; error = f"{type(exc).__name__}: {exc}"
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        automatic = verdict in {"sermon", "no_sermon"}; correct = verdict == case.expected_outcome if automatic else None
        results.append({"video_id": case.video_id, "title": case.title, "partition": case.partition, "expected_outcome": case.expected_outcome, "existing_12b": case.existing_12b, "title_gate": title_gate, "jev_policy_verdict": verdict, "automatic": automatic, "correct": correct, "policy_reason_codes": reasons, "recording_type_choice": answers.choice if answers else None, "recording_type_probabilities": dict(answers.choice_probabilities) if answers else None, "recording_type_confidence": answers.choice_confidence if answers else None, "choice_agrees_with_policy": choice_agrees, "requested_model_id": model, "resolved_model_id": answers.resolved_model_id if answers else None, "question_set_version": QUESTION_SET_VERSION, "policy_version": policy.version, "structured_state_hash": state_key, "cache_hit": hit, "latency_ms": latency_ms, "input_tokens": answers.input_tokens if answers else None, "output_tokens": answers.output_tokens if answers else None, "estimated_cost": cost_rate.estimate(answers.input_tokens, answers.output_tokens) if answers else None, "cost_rate_version": cost_rate.version, "inference_error": error})
    return {"schema_version": 2, "generated_at": datetime.now(timezone.utc).isoformat(), "question_set_version": QUESTION_SET_VERSION, "policy": asdict(policy), "cost_rate": asdict(cost_rate), "requested_model_id": model, "production_artifacts_modified": False, "results": results, "summary": benchmark_summary(results), "disagreements": disagreement_sets(results)}


def benchmark_summary(results: list[Mapping[str, Any]]) -> dict[str, Any]:
    def metrics(
        items: list[Mapping[str, Any]],
        decision_key: str,
        automatic_fn: Any,
        *,
        latency_key: str | None,
        input_tokens_key: str | None,
        output_tokens_key: str | None,
        cost_key: str | None,
    ) -> dict[str, Any]:
        automatic = [r for r in items if automatic_fn(r)]; correct = [r for r in automatic if r.get("expected_outcome") == r.get(decision_key)]
        latencies = [float(r[latency_key]) for r in items if latency_key and isinstance(r.get(latency_key), (int, float))]
        def total(key: str | None) -> int | float | None:
            values = [r.get(key) for r in items if key and isinstance(r.get(key), (int, float))]
            return sum(values) if values else None
        return {"eligible_fixtures": len(items), "automatic_decisions": len(automatic), "correct_decisions": len(correct), "incorrect_decisions": len(automatic) - len(correct), "abstentions": len(items) - len(automatic), "automatic_accuracy": len(correct) / len(automatic) if automatic else None, "coverage": len(automatic) / len(items) if items else None, "median_latency_ms": statistics.median(latencies) if latencies else None, "p95_latency_ms": _percentile(latencies, .95), "input_tokens": total(input_tokens_key), "output_tokens": total(output_tokens_key), "estimated_cost": total(cost_key)}
    jev = metrics(results, "jev_policy_verdict", lambda r: bool(r.get("automatic")), latency_key="latency_ms", input_tokens_key="input_tokens", output_tokens_key="output_tokens", cost_key="estimated_cost")
    baseline_items = [r for r in results if isinstance(r.get("existing_12b"), Mapping)]
    for r in baseline_items: r["existing_predicted"] = r["existing_12b"].get("predicted_outcome")
    existing = metrics(baseline_items, "existing_predicted", lambda r: r["existing_predicted"] in {"sermon", "no_sermon"}, latency_key=None, input_tokens_key=None, output_tokens_key=None, cost_key=None)
    return {"jev": jev, "existing_12b": existing}


def disagreement_sets(results: list[Mapping[str, Any]]) -> dict[str, list[str]]:
    return {
        "jev_vs_12b": [str(r["video_id"]) for r in results if isinstance(r.get("existing_12b"), Mapping) and r["existing_12b"].get("predicted_outcome") != r.get("jev_policy_verdict")],
        "jev_vs_recording_type_choice": [str(r["video_id"]) for r in results if r.get("choice_agrees_with_policy") is False],
        "incorrect_automatic": [str(r["video_id"]) for r in results if r.get("correct") is False],
        "low_confidence_choices": [str(r["video_id"]) for r in results if "choice_below_automatic_threshold" in r.get("policy_reason_codes", [])],
        "differing_abstentions": [str(r["video_id"]) for r in results if isinstance(r.get("existing_12b"), Mapping) and (r["existing_12b"].get("predicted_outcome") is None) != (not r.get("automatic"))],
        "inference_failures": [str(r["video_id"]) for r in results if r.get("inference_error")],
    }


def write_reports(run: Mapping[str, Any], output_dir: Path) -> tuple[Path, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"); target = output_dir / stamp; target.mkdir(parents=True, exist_ok=False)
    json_path = target / "results.json"; json_path.write_text(json.dumps(run, indent=2, sort_keys=True))
    summary = run["summary"]; lines = ["# TypeSafe/Jev Recording Verifier Shadow Benchmark", "", "- Production artifacts modified: no", f"- Question set: `{run['question_set_version']}`", f"- Policy: `{run['policy']['version']}`", f"- Model: `{run['requested_model_id']}`", "", "| System | Eligible | Automatic | Correct | Incorrect | Abstain | Accuracy | Coverage | Median / p95 ms |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, data in summary.items(): lines.append(f"| {name} | {data['eligible_fixtures']} | {data['automatic_decisions']} | {data['correct_decisions']} | {data['incorrect_decisions']} | {data['abstentions']} | {data['automatic_accuracy']} | {data['coverage']} | {data['median_latency_ms']} / {data['p95_latency_ms']} |")
    lines += ["", "## Disagreements", ""] + [f"- {name}: {', '.join(items) or 'none'}" for name, items in run["disagreements"].items()]
    markdown_path = target / "report.md"; markdown_path.write_text("\n".join(lines) + "\n")
    for name, ids in run["disagreements"].items(): (target / f"{name}.json").write_text(json.dumps([r for r in run["results"] if r["video_id"] in ids], indent=2))
    return json_path, markdown_path
