from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from pastor_transcript_extractor.caption_normalization import normalize_caption_text
from pastor_transcript_extractor.local_llm import LocalLlmClient, LocalLlmResponse
from pastor_transcript_extractor.storage import Database


PROMPT_VERSION = "recording-sermon-verifier-v2"
POLICY_VERSION = "recording-sermon-verifier-policy-v3"
ARTIFACT_SCHEMA_VERSION = 1
DECISIONS = (
    "worship_service_sermon",
    "religious_education_or_bible_class",
    "multi_speaker_or_student_program",
    "non_sermon_event",
    "unclear",
)
CONFIDENCE_LEVELS = ("high", "medium", "low")
REASON_CODES = (
    "single_sustained_message",
    "sermon_title_or_introduction",
    "lesson_or_curriculum_structure",
    "facilitated_group_structure",
    "multiple_short_speakers_or_sermonettes",
    "ceremony_concert_or_technical_event",
    "insufficient_recording_context",
)


@dataclass(frozen=True, slots=True)
class RecordingVerifierCase:
    video_id: str
    title: str
    expected_outcome: str
    evaluation_partition: str
    evidence_packet: str


def verifier_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": list(DECISIONS)},
            "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
            "reason_codes": {
                "type": "array",
                "items": {"type": "string", "enum": list(REASON_CODES)},
                "uniqueItems": True,
            },
        },
        "required": ["decision", "confidence", "reason_codes"],
        "additionalProperties": False,
    }


def _selected_candidate(proposed: dict[str, Any]) -> tuple[float, float]:
    classification = proposed.get("classification")
    search = classification.get("search") if isinstance(classification, dict) else None
    candidates = search.get("candidates") if isinstance(search, dict) else None
    selected_rank = search.get("selected_rank") if isinstance(search, dict) else None
    if not isinstance(candidates, list) or not isinstance(selected_rank, int):
        raise ValueError("proposed extraction has no selected sermon candidate")
    selected = next(
        (
            candidate
            for candidate in candidates
            if isinstance(candidate, dict) and candidate.get("rank") == selected_rank
        ),
        None,
    )
    if not isinstance(selected, dict):
        raise ValueError("selected sermon candidate is missing")
    start = selected.get("start_seconds")
    end = selected.get("end_seconds")
    if (
        not isinstance(start, (int, float))
        or not isinstance(end, (int, float))
        or float(end) <= float(start)
    ):
        raise ValueError("selected sermon candidate has invalid boundaries")
    return float(start), float(end)


def _excerpt(
    segments: list[dict[str, Any]],
    *,
    center_seconds: float,
    radius_seconds: float = 75.0,
    max_chars: int = 2200,
) -> str:
    start = max(0.0, center_seconds - radius_seconds)
    end = center_seconds + radius_seconds
    text = "\n".join(
        str(segment["text"])
        for segment in segments
        if isinstance(segment.get("text"), str)
        and isinstance(segment.get("start_seconds"), (int, float))
        and isinstance(segment.get("end_seconds"), (int, float))
        and float(segment["end_seconds"]) > start
        and float(segment["start_seconds"]) < end
    )
    normalized = normalize_caption_text(text).text.strip()
    if len(normalized) <= max_chars:
        return normalized or "(no usable transcript text)"
    return normalized[:max_chars].rsplit(" ", 1)[0] + " …"


def build_evidence_packet(title: str, proposed: dict[str, Any]) -> str:
    start, end = _selected_candidate(proposed)
    segments_raw = proposed.get("segments")
    if not isinstance(segments_raw, list):
        raise ValueError("proposed extraction has no transcript segments")
    segments = [segment for segment in segments_raw if isinstance(segment, dict)]
    midpoint = start + (end - start) / 2.0
    near_end = max(start, end - 75.0)
    recording_open = _excerpt(segments, center_seconds=75.0)
    candidate_open = _excerpt(segments, center_seconds=start + 75.0)
    candidate_middle = _excerpt(segments, center_seconds=midpoint)
    candidate_end = _excerpt(segments, center_seconds=near_end)
    return "\n\n".join(
        (
            f"RECORDING TITLE:\n{title}",
            f"RECORDING OPENING (around 00:00-02:30):\n{recording_open}",
            f"CANDIDATE OPENING (around {start:.0f}s):\n{candidate_open}",
            f"CANDIDATE MIDDLE (around {midpoint:.0f}s):\n{candidate_middle}",
            f"CANDIDATE END (around {end:.0f}s):\n{candidate_end}",
        )
    )


def verifier_prompt(case: RecordingVerifierCase) -> str:
    return f"""Decide whether this recording contains one sustained Christian worship-service sermon.

WORSHIP_SERVICE_SERMON means one principal message is developed through sustained preaching or biblical exposition. A guest preacher still counts. Normal service elements before or after the message do not disqualify it.
RELIGIOUS_EDUCATION_OR_BIBLE_CLASS means Sabbath school, Bible class, lesson study, or facilitated religious education rather than a worship-service sermon.
MULTI_SPEAKER_OR_STUDENT_PROGRAM means a ceremony, school program, or sequence of short talks or sermonettes without one principal sustained sermon.
NON_SERMON_EVENT means a concert, graduation, technical test, announcements-only recording, or another event without a sustained sermon.
UNCLEAR means the supplied evidence cannot reliably distinguish these outcomes.

The title is useful context but may be stale or misleading. Give transcript structure priority. Do not call rhetorical questions, quoted dialogue, or brief congregational responses multiple speakers. Return only the required JSON.
An explicit Bible Class or Sabbath School title is religious education, even when one teacher gives a long monologue, unless the evidence clearly contains a separate worship-service sermon. A sermon-like title or introduction is never sufficient by itself: WORSHIP_SERVICE_SERMON requires single_sustained_message.

{case.evidence_packet}"""


def title_program_decision(title: str) -> str | None:
    normalized = " ".join(title.casefold().replace("’", "'").split())
    if any(
        marker in normalized
        for marker in ("graduation", "concert", "sound test", "technical test")
    ):
        return "non_sermon_event"
    if (
        "super sabbath" in normalized
        and any(marker in normalized for marker in ("student", "chaplain"))
    ):
        return "multi_speaker_or_student_program"
    if "bible class" in normalized:
        return "religious_education_or_bible_class"
    if "sabbath school" not in normalized:
        return None
    combined_service_markers = (
        "sabbath school & church",
        "sabbath school and church",
        "sabbath school & worship",
        "sabbath school and worship",
        "sabbath school & divine",
        "sabbath school and divine",
    )
    if any(marker in normalized for marker in combined_service_markers):
        return None
    return "religious_education_or_bible_class"


def title_supports_worship_service(title: str) -> bool:
    normalized = " ".join(title.casefold().replace("’", "'").split())
    return any(
        marker in normalized
        for marker in ("church", "pastor", "sermon", "service", "worship")
    )


def validate_partition_access(partition: str, *, confirm_frozen_policy: bool) -> None:
    if partition not in {"development", "legacy", "held_out"}:
        raise ValueError("partition must be development, legacy, or held_out")
    if partition == "held_out" and not confirm_frozen_policy:
        raise ValueError(
            "held-out validation requires confirmation that the prompt and policy are frozen"
        )


def validate_verdict(content: dict[str, Any]) -> None:
    decision = content.get("decision")
    confidence = content.get("confidence")
    reason_codes = content.get("reason_codes")
    if (
        decision not in DECISIONS
        or confidence not in CONFIDENCE_LEVELS
        or not isinstance(reason_codes, list)
        or any(reason not in REASON_CODES for reason in reason_codes)
        or len(reason_codes) != len(set(reason_codes))
    ):
        raise ValueError("verifier returned unsupported structured evidence")
    if (
        decision == "worship_service_sermon"
        and "single_sustained_message" not in reason_codes
    ):
        raise ValueError("worship-service sermon lacks sustained-message evidence")


class RecordingVerifierCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def generate(
        self,
        client: LocalLlmClient,
        *,
        model_digest: str,
        prompt: str,
        schema: dict[str, Any],
    ) -> tuple[LocalLlmResponse, bool]:
        identity = {
            "prompt_version": PROMPT_VERSION,
            "model": client.model,
            "model_digest": model_digest,
            "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "schema_hash": hashlib.sha256(
                json.dumps(schema, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "temperature": 0,
        }
        key = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "_", client.model)
        path = self.root / safe_model / f"{key}.json"
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                content = payload["content"]
                raw_content = payload["raw_content"]
                model = payload["model"]
                if (
                    isinstance(content, dict)
                    and isinstance(raw_content, str)
                    and isinstance(model, str)
                ):
                    return LocalLlmResponse(content, raw_content, model), True
            except (OSError, json.JSONDecodeError, KeyError):
                pass
        response = client.generate_json(prompt, schema)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "identity": identity,
                    "content": response.content,
                    "raw_content": response.raw_content,
                    "model": response.model,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return response, False


def verify_recording(
    *,
    title: str,
    proposed: dict[str, Any],
    client: LocalLlmClient,
    model_digest: str,
    cache_dir: Path,
) -> dict[str, Any]:
    evidence_packet = build_evidence_packet(title, proposed)
    title_decision = title_program_decision(title)
    if title_decision is not None:
        decision = title_decision
        confidence = "high"
        reason_codes = {
            "religious_education_or_bible_class": [
                "lesson_or_curriculum_structure"
            ],
            "multi_speaker_or_student_program": [
                "multiple_short_speakers_or_sermonettes"
            ],
            "non_sermon_event": ["ceremony_concert_or_technical_event"],
        }[title_decision]
        source = "deterministic_title_gate"
        cache_hit = False
        raw_response = None
        error = None
    else:
        case = RecordingVerifierCase(
            video_id=str(proposed.get("youtube_video_id") or proposed.get("video_id") or ""),
            title=title,
            expected_outcome="unknown",
            evaluation_partition="production",
            evidence_packet=evidence_packet,
        )
        try:
            response, cache_hit = RecordingVerifierCache(cache_dir).generate(
                client,
                model_digest=model_digest,
                prompt=verifier_prompt(case),
                schema=verifier_schema(),
            )
            decision = response.content.get("decision")
            confidence = response.content.get("confidence")
            reason_codes = response.content.get("reason_codes")
            validate_verdict(response.content)
            if (
                decision == "worship_service_sermon"
                and "ceremony_concert_or_technical_event" in reason_codes
                and not title_supports_worship_service(title)
            ):
                raise ValueError(
                    "worship-service sermon has unsupported contradictory event evidence"
                )
            source = "llm_recording_verifier"
            raw_response = response.raw_content
            error = None
        except Exception as caught:
            decision = "unclear"
            confidence = "low"
            reason_codes = ["insufficient_recording_context"]
            source = "unresolved"
            cache_hit = False
            raw_response = None
            error = f"{type(caught).__name__}: {caught}"
    predicted_outcome = (
        "sermon"
        if decision == "worship_service_sermon" and confidence == "high"
        else "no_sermon"
        if decision in {
            "religious_education_or_bible_class",
            "multi_speaker_or_student_program",
            "non_sermon_event",
        }
        and confidence == "high"
        else None
    )
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "policy_version": POLICY_VERSION,
        "model": client.model if source != "deterministic_title_gate" else None,
        "model_digest": model_digest if source != "deterministic_title_gate" else None,
        "source": source,
        "decision": decision,
        "confidence": confidence,
        "reason_codes": reason_codes,
        "predicted_outcome": predicted_outcome,
        "cache_hit": cache_hit,
        "evidence_packet_hash": hashlib.sha256(
            evidence_packet.encode("utf-8")
        ).hexdigest(),
        "raw_response": raw_response,
        "error": error,
    }


def load_cases(
    database: Database,
    fixture_dir: Path,
    *,
    partition: str,
) -> list[RecordingVerifierCase]:
    cases: list[RecordingVerifierCase] = []
    for fixture_path in sorted(fixture_dir.glob("*.json")):
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        manifest = fixture.get("selection_manifest")
        fixture_partition = (
            str(manifest.get("evaluation_partition"))
            if isinstance(manifest, dict) and manifest.get("evaluation_partition")
            else "legacy"
        )
        if fixture_partition != partition:
            continue
        video_id = str(fixture.get("video_id"))
        video = database.get_video_by_youtube_id(video_id)
        if video is None:
            raise ValueError(f"fixture video {video_id} is not in the database")
        extraction = database.get_latest_extraction_result_for_video(video.id)
        if extraction is None or not extraction.proposed_json_path:
            raise ValueError(f"fixture video {video_id} has no proposed extraction")
        proposed = json.loads(Path(extraction.proposed_json_path).read_text(encoding="utf-8"))
        disposition = proposed.get("final_disposition")
        if (
            not isinstance(disposition, dict)
            or disposition.get("status") != "review_required"
        ):
            continue
        cases.append(
            RecordingVerifierCase(
                video_id=video_id,
                title=video.title,
                expected_outcome=str(fixture.get("expected_outcome")),
                evaluation_partition=fixture_partition,
                evidence_packet=build_evidence_packet(video.title, proposed),
            )
        )
    return cases


def run_diagnostics(
    client: LocalLlmClient,
    *,
    model_digest: str,
    cases: list[RecordingVerifierCase],
    cache: RecordingVerifierCache,
    progress: Any | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    hits = 0
    misses = 0
    failures = 0
    title_gate_decisions = 0
    schema = verifier_schema()
    for index, case in enumerate(cases, start=1):
        if progress is not None:
            progress(case.video_id, index, len(cases))
        prompt = verifier_prompt(case)
        title_decision = title_program_decision(case.title)
        if title_decision is not None:
            title_gate_decisions += 1
            cached = False
            decision = title_decision
            confidence = "high"
            reason_codes = {
                "religious_education_or_bible_class": [
                    "lesson_or_curriculum_structure"
                ],
                "multi_speaker_or_student_program": [
                    "multiple_short_speakers_or_sermonettes"
                ],
                "non_sermon_event": ["ceremony_concert_or_technical_event"],
            }[title_decision]
            predicted = "no_sermon"
            error = None
            raw_response = None
            inference_source = "deterministic_title_gate"
        else:
            inference_source = "llm_recording_verifier"
            try:
                response, cached = cache.generate(
                    client,
                    model_digest=model_digest,
                    prompt=prompt,
                    schema=schema,
                )
                hits += int(cached)
                misses += int(not cached)
                decision = response.content.get("decision")
                confidence = response.content.get("confidence")
                reason_codes = response.content.get("reason_codes")
                validate_verdict(response.content)
                if (
                    decision == "worship_service_sermon"
                    and "ceremony_concert_or_technical_event" in reason_codes
                    and not title_supports_worship_service(case.title)
                ):
                    raise ValueError(
                        "worship-service sermon has unsupported contradictory event evidence"
                    )
                predicted = (
                    "sermon"
                    if decision == "worship_service_sermon"
                    else None
                    if decision == "unclear"
                    else "no_sermon"
                )
                error = None
                raw_response = response.raw_content
            except Exception as caught:
                failures += 1
                cached = False
                decision = "invalid_or_failed_inference"
                confidence = None
                reason_codes = []
                predicted = None
                error = f"{type(caught).__name__}: {caught}"
                raw_response = None
        results.append(
            {
                "video_id": case.video_id,
                "title": case.title,
                "expected_outcome": case.expected_outcome,
                "decision": decision,
                "confidence": confidence,
                "reason_codes": reason_codes,
                "predicted_outcome": predicted,
                "correct": predicted == case.expected_outcome if predicted else None,
                "cache_hit": cached,
                "inference_source": inference_source,
                "inference_error": error,
                "raw_response": raw_response,
                "evidence_packet": case.evidence_packet,
            }
        )
    resolved = [result for result in results if result["predicted_outcome"] is not None]
    high = [result for result in resolved if result["confidence"] == "high"]
    return {
        "model": client.model,
        "model_digest": model_digest,
        "cache_hits": hits,
        "cache_misses": misses,
        "inference_failures": failures,
        "title_gate_decisions": title_gate_decisions,
        "case_count": len(results),
        "resolved_count": len(resolved),
        "correct_count": sum(result["correct"] is True for result in resolved),
        "high_confidence_count": len(high),
        "high_confidence_correct_count": sum(result["correct"] is True for result in high),
        "results": results,
    }


def create_run(model_result: dict[str, Any], *, partition: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "schema_version": 1,
        "run_id": now.strftime("%Y%m%dT%H%M%SZ"),
        "generated_at": now.isoformat(),
        "prompt_version": PROMPT_VERSION,
        "policy_version": POLICY_VERSION,
        "evaluation_partition": partition,
        "production_artifacts_modified": False,
        "model_result": model_result,
    }


def build_report(run: dict[str, Any]) -> str:
    result = run["model_result"]
    resolved = int(result["resolved_count"])
    high = int(result["high_confidence_count"])
    lines = [
        "# Recording-level Sermon Verifier Diagnostic",
        "",
        f"- Run ID: {run['run_id']}",
        f"- Partition: {run['evaluation_partition']}",
        f"- Prompt: `{run['prompt_version']}`",
        f"- Policy: `{run['policy_version']}`",
        f"- Model: `{result['model']}`",
        "- Production artifacts modified: no",
        f"- Cases: {result['case_count']}",
        f"- Resolved accuracy: {result['correct_count']}/{resolved}",
        f"- High-confidence accuracy: {result['high_confidence_correct_count']}/{high}",
        f"- Cache H/M/F: {result['cache_hits']}/{result['cache_misses']}/{result['inference_failures']}",
        f"- Deterministic title decisions: {result['title_gate_decisions']}",
        "",
        "| Video | Expected | Decision | Confidence | Correct | Reasons |",
        "|---|---|---|---:|---:|---|",
    ]
    for item in result["results"]:
        lines.append(
            f"| {item['video_id']} | {item['expected_outcome']} | {item['decision']} | "
            f"{item['confidence'] or '—'} | "
            f"{'yes' if item['correct'] is True else 'no' if item['correct'] is False else '—'} | "
            f"{', '.join(item['reason_codes']) or '—'} |"
        )
    lines.extend(
        [
            "",
            "Promotion gate: do not inspect or run the held-out partition until the prompt and policy are frozen. Production promotion additionally requires zero high-confidence errors on legacy regression fixtures and held-out fixtures.",
            "",
        ]
    )
    return "\n".join(lines)
