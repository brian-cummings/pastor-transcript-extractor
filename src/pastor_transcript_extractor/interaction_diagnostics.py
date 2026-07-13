from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from pastor_transcript_extractor.local_llm import LocalLlmClient, LocalLlmResponse
from pastor_transcript_extractor.storage import Database


PROMPT_VERSION = "interaction-diagnostic-v1"
BLOCK_BUILDER_VERSION = "deduplicated-caption-blocks-v1"
DEFAULT_SENTINELS = ("WaNsL05AX3A", "l6mZEQvArkE", "qny7TUqNkQU")
INTERACTION_MODES = (
    "sermon_monologue",
    "participatory_sermon",
    "facilitated_group_discussion",
    "mixed_or_unclear",
)
INTERACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "interaction_mode": {"type": "string", "enum": list(INTERACTION_MODES)},
        "audience_turn_taking": {"type": "boolean"},
        "audience_turn_taking_evidence": {"type": "string"},
        "lesson_material_references": {"type": "boolean"},
        "lesson_material_references_evidence": {"type": "string"},
        "multiple_sustained_speakers": {"type": "boolean"},
        "multiple_sustained_speakers_evidence": {"type": "string"},
    },
    "required": [
        "interaction_mode",
        "audience_turn_taking",
        "audience_turn_taking_evidence",
        "lesson_material_references",
        "lesson_material_references_evidence",
        "multiple_sustained_speakers",
        "multiple_sustained_speakers_evidence",
    ],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class DiagnosticBlock:
    block_id: int
    segment_indexes: list[int]
    start_seconds: float
    end_seconds: float
    raw_text: str
    deduplicated_text: str


def _normalized_line(value: str) -> str:
    return " ".join(value.lower().split())


def deduplicate_caption_text(text: str) -> str:
    """Collapse repeated and incrementally growing adjacent caption lines."""
    kept: list[str] = []
    normalized: list[str] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        current = _normalized_line(line)
        if not current:
            continue
        if normalized and current == normalized[-1]:
            continue
        if normalized and len(current) >= 12 and current in normalized[-1]:
            continue
        if normalized and len(normalized[-1]) >= 12 and normalized[-1] in current:
            kept[-1] = line
            normalized[-1] = current
            continue
        kept.append(line)
        normalized.append(current)
    return "\n".join(kept)


def _selected_candidate(classification: dict[str, Any]) -> dict[str, Any]:
    search = classification.get("search")
    if not isinstance(search, dict):
        raise ValueError("classification has no candidate search artifact")
    candidates = search.get("candidates")
    selected_rank = search.get("selected_rank")
    if not isinstance(candidates, list) or not isinstance(selected_rank, int):
        raise ValueError("classification has no selected sermon candidate")
    selected = next(
        (item for item in candidates if isinstance(item, dict) and item.get("rank") == selected_rank),
        None,
    )
    if not isinstance(selected, dict):
        raise ValueError("selected sermon candidate is missing")
    return selected


def build_diagnostic_blocks(
    proposed: dict[str, Any], *, target_seconds: float = 180.0, max_chars: int = 6000
) -> list[DiagnosticBlock]:
    classification = proposed.get("classification")
    if not isinstance(classification, dict):
        raise ValueError("proposed extraction has no classification")
    candidate = _selected_candidate(classification)
    start = candidate.get("start_seconds")
    end = candidate.get("end_seconds")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        raise ValueError("selected candidate has invalid boundaries")
    segments = proposed.get("segments")
    if not isinstance(segments, list):
        raise ValueError("proposed extraction has no transcript segments")

    blocks: list[DiagnosticBlock] = []
    indexes: list[int] = []
    texts: list[str] = []
    block_start: float | None = None
    block_end: float | None = None

    def flush() -> None:
        nonlocal indexes, texts, block_start, block_end
        if indexes and block_start is not None and block_end is not None:
            raw_text = "\n".join(texts)
            blocks.append(DiagnosticBlock(
                len(blocks), list(indexes), block_start, block_end,
                raw_text, deduplicate_caption_text(raw_text),
            ))
        indexes, texts, block_start, block_end = [], [], None, None

    for index, segment in enumerate(segments):
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
            continue
        segment_start = segment.get("start_seconds")
        segment_end = segment.get("end_seconds")
        if not isinstance(segment_start, (int, float)) or not isinstance(segment_end, (int, float)):
            continue
        if float(segment_end) <= float(start) or float(segment_start) >= float(end):
            continue
        next_text = segment["text"]
        if block_start is not None and (
            float(segment_end) - block_start > target_seconds
            or len("\n".join([*texts, next_text])) > max_chars
        ):
            flush()
        if block_start is None:
            block_start = float(segment_start)
        block_end = float(segment_end)
        indexes.append(index)
        texts.append(next_text)
    flush()
    return blocks


def interaction_prompt(
    block: DiagnosticBlock,
    previous: DiagnosticBlock | None,
    following: DiagnosticBlock | None,
) -> str:
    return f"""Analyze interaction structure in only the CURRENT deduplicated transcript excerpt. Do not decide whether the overall video is a sermon.
SERMON_MONOLOGUE: one primary speaker gives sustained teaching. Rhetorical questions, quoted dialogue, Bible-story characters, and brief responses such as amen do not change this.
PARTICIPATORY_SERMON: one primary preacher remains in control but the excerpt contains explicit meaningful audience answers or another sustained participant.
FACILITATED_GROUP_DISCUSSION: a leader solicits answers and at least two real participants make substantive alternating contributions.
MIXED_OR_UNCLEAR: the interaction structure cannot be established from the text.
Set lesson_material_references only for explicit curriculum material such as a quarterly, study guide, numbered lesson, or memory text; a Bible passage or generic use of the word lesson is insufficient.
For every true boolean, provide a short exact excerpt from CURRENT proving it. Return an empty evidence string for false. If exact evidence is absent, use false.
Do not infer turns from repeated ideas, punctuation, religious vocabulary, church names, service titles, or topic keywords. Return only the required JSON.

PREVIOUS:
{previous.deduplicated_text if previous else '(none)'}

CURRENT:
{block.deduplicated_text}

FOLLOWING:
{following.deduplicated_text if following else '(none)'}"""


def validate_interaction_evidence(content: dict[str, Any], block_text: str) -> list[str]:
    errors: list[str] = []
    normalized_text = _normalized_line(block_text)
    mode = content.get("interaction_mode")
    if mode not in INTERACTION_MODES:
        errors.append("invalid_interaction_mode")
    for field in (
        "audience_turn_taking",
        "lesson_material_references",
        "multiple_sustained_speakers",
    ):
        evidence_field = f"{field}_evidence"
        enabled = content.get(field)
        evidence = content.get(evidence_field)
        if not isinstance(enabled, bool):
            errors.append(f"invalid_{field}")
            continue
        if not isinstance(evidence, str):
            errors.append(f"invalid_{evidence_field}")
            continue
        normalized_evidence = _normalized_line(evidence)
        if enabled and (not normalized_evidence or normalized_evidence not in normalized_text):
            errors.append(f"ungrounded_{field}")
        if not enabled and normalized_evidence:
            errors.append(f"evidence_present_for_false_{field}")
    if mode == "facilitated_group_discussion" and not (
        content.get("audience_turn_taking") is True
        and content.get("multiple_sustained_speakers") is True
    ):
        errors.append("inconsistent_facilitated_group_discussion")
    return errors


class DiagnosticInferenceCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def generate(
        self,
        client: LocalLlmClient,
        *,
        model_digest: str,
        prompt: str,
    ) -> tuple[LocalLlmResponse, bool]:
        identity = {
            "prompt_version": PROMPT_VERSION,
            "block_builder_version": BLOCK_BUILDER_VERSION,
            "model": client.model,
            "model_digest": model_digest,
            "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "schema_hash": hashlib.sha256(
                json.dumps(INTERACTION_SCHEMA, sort_keys=True).encode("utf-8")
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
                if isinstance(content, dict) and isinstance(raw_content, str) and isinstance(model, str):
                    return LocalLlmResponse(content, raw_content, model), True
            except (OSError, json.JSONDecodeError, KeyError):
                pass
        response = client.generate_json(prompt, INTERACTION_SCHEMA)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "identity": identity,
            "content": response.content,
            "raw_content": response.raw_content,
            "model": response.model,
        }, indent=2, sort_keys=True), encoding="utf-8")
        return response, False


def load_sentinel_blocks(database: Database, video_id: str) -> tuple[str, list[DiagnosticBlock]]:
    video = database.get_video_by_youtube_id(video_id)
    if video is None:
        raise ValueError(f"sentinel {video_id} is not in the database")
    extraction = database.get_latest_extraction_result_for_video(video.id)
    if extraction is None or not extraction.proposed_json_path:
        raise ValueError(f"sentinel {video_id} has no proposed extraction")
    proposed_path = Path(extraction.proposed_json_path)
    proposed = json.loads(proposed_path.read_text(encoding="utf-8"))
    if not isinstance(proposed, dict):
        raise ValueError(f"sentinel {video_id} proposed extraction is invalid")
    return video.title, build_diagnostic_blocks(proposed)


def run_model_diagnostics(
    client: LocalLlmClient,
    *,
    model_digest: str,
    sentinels: list[tuple[str, str, list[DiagnosticBlock]]],
    cache: DiagnosticInferenceCache,
    progress: Any | None = None,
) -> dict[str, Any]:
    sentinel_results: list[dict[str, Any]] = []
    hits = 0
    misses = 0
    failures = 0
    for video_id, title, blocks in sentinels:
        block_results: list[dict[str, Any]] = []
        for position, block in enumerate(blocks):
            if progress is not None:
                progress(client.model, video_id, position + 1, len(blocks))
            prompt = interaction_prompt(
                block,
                blocks[position - 1] if position else None,
                blocks[position + 1] if position + 1 < len(blocks) else None,
            )
            try:
                response, cached = cache.generate(
                    client, model_digest=model_digest, prompt=prompt
                )
                hits += int(cached)
                misses += int(not cached)
                content = response.content
                raw_response: str | None = response.raw_content
                inference_error: str | None = None
                validation_errors = validate_interaction_evidence(
                    content, block.deduplicated_text
                )
            except Exception as error:
                failures += 1
                cached = False
                content = {}
                raw_response = None
                inference_error = f"{type(error).__name__}: {error}"
                validation_errors = ["inference_failed"]
            block_results.append({
                "block_id": block.block_id,
                "start_seconds": block.start_seconds,
                "end_seconds": block.end_seconds,
                "segment_indexes": block.segment_indexes,
                "raw_text_hash": hashlib.sha256(block.raw_text.encode("utf-8")).hexdigest(),
                "deduplicated_text": block.deduplicated_text,
                "deduplication_ratio": len(block.deduplicated_text) / max(len(block.raw_text), 1),
                "content": content,
                "raw_response": raw_response,
                "inference_error": inference_error,
                "validation_errors": validation_errors,
                "cache_hit": cached,
            })
        valid = [item for item in block_results if not item["validation_errors"]]
        mode_counts = {
            mode: sum(item["content"].get("interaction_mode") == mode for item in valid)
            for mode in INTERACTION_MODES
        }
        sentinel_results.append({
            "video_id": video_id,
            "title": title,
            "block_count": len(block_results),
            "valid_block_count": len(valid),
            "interaction_mode_counts": {key: value for key, value in mode_counts.items() if value},
            "audience_turn_taking_block_ids": [
                item["block_id"] for item in valid if item["content"].get("audience_turn_taking") is True
            ],
            "lesson_material_references_block_ids": [
                item["block_id"] for item in valid if item["content"].get("lesson_material_references") is True
            ],
            "multiple_sustained_speakers_block_ids": [
                item["block_id"] for item in valid if item["content"].get("multiple_sustained_speakers") is True
            ],
            "blocks": block_results,
        })
    return {
        "model": client.model,
        "model_digest": model_digest,
        "cache_hits": hits,
        "cache_misses": misses,
        "inference_failures": failures,
        "sentinels": sentinel_results,
    }


def build_diagnostic_report(run: dict[str, Any]) -> str:
    lines = [
        "# Offline Interaction Diagnostic Comparison",
        "",
        f"- Run ID: {run['run_id']}",
        f"- Prompt: `{run['prompt_version']}`",
        f"- Block builder: `{run['block_builder_version']}`",
        "- Production artifacts modified: no",
        "",
        "| Model | Sentinel | Valid blocks | Monologue | Participatory | Group discussion | Mixed | Audience turns | Lesson refs | Multiple speakers | Cache H/M/F |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model_result in run["models"]:
        for sentinel in model_result["sentinels"]:
            counts = sentinel["interaction_mode_counts"]
            lines.append(
                f"| {model_result['model']} | {sentinel['video_id']} | "
                f"{sentinel['valid_block_count']}/{sentinel['block_count']} | "
                f"{counts.get('sermon_monologue', 0)} | {counts.get('participatory_sermon', 0)} | "
                f"{counts.get('facilitated_group_discussion', 0)} | {counts.get('mixed_or_unclear', 0)} | "
                f"{len(sentinel['audience_turn_taking_block_ids'])} | "
                f"{len(sentinel['lesson_material_references_block_ids'])} | "
                f"{len(sentinel['multiple_sustained_speakers_block_ids'])} | "
                f"{model_result['cache_hits']}/{model_result['cache_misses']}/{model_result['inference_failures']} |"
            )
    lines.extend([
        "",
        "## Review guidance",
        "",
        "Inspect block-level excerpts and exact evidence in `results.json`. A model passes only if it separates Sabbath School, a normal sermon, and the multi-speaker sermon without relying on topic keywords alone.",
        "",
    ])
    return "\n".join(lines)


def create_diagnostic_run(model_results: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "schema_version": 1,
        "run_id": now.strftime("%Y%m%dT%H%M%SZ"),
        "generated_at": now.isoformat(),
        "prompt_version": PROMPT_VERSION,
        "block_builder_version": BLOCK_BUILDER_VERSION,
        "sentinel_video_ids": list(DEFAULT_SENTINELS),
        "models": model_results,
    }
