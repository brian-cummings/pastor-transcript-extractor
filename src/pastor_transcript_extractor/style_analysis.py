from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from pastor_transcript_extractor.local_llm import LocalLlmClient
from pastor_transcript_extractor.models import SermonAnalysisRun, Video
from pastor_transcript_extractor.semantic_evidence import (
    SEMANTIC_VALIDATION_VERSION,
    AcceptedSemanticProposal,
    SemanticBlock,
    SemanticSegment,
    SemanticValidationResult,
    build_semantic_blocks,
    semantic_proposal_schema,
    validate_semantic_proposals,
)
from pastor_transcript_extractor.sermon_analysis import (
    ANALYZER_KEY as SCRIPTURE_ANALYZER_KEY,
    ANALYZER_VERSION as SCRIPTURE_ANALYZER_VERSION,
    canonical_sermon_source,
    load_identified_sermon_source,
)
from pastor_transcript_extractor.storage import Database


STYLE_ANALYZER_KEY = "sermon-style-evidence"
STYLE_ANALYZER_VERSION = "1"
STYLE_PROMPT_VERSION = "sermon-style-evidence-v2"
STYLE_BLOCK_VERSION = "nonoverlapping-75s-3600chars-v1"
STYLE_ACCEPTANCE_VERSION = "observable-dimension-gates-v1"
STYLE_ANALYSIS_SCHEMA_VERSION = 1

STYLE_DIMENSIONS: dict[str, str] = {
    "exegetical_exposition": (
        "Explains the meaning, context, wording, structure, or implications of a "
        "biblical text. A quotation or reference without explanation is insufficient."
    ),
    "narrative_illustration": (
        "Recounts a concrete personal experience, observed event, or developed story "
        "to illuminate a sermon's point. A passing example or hypothetical is insufficient."
    ),
    "doctrinal_argument": (
        "Develops a reasoned claim about Christian belief using premises, distinctions, "
        "support, consequences, or responses to alternatives. A bare assertion is insufficient."
    ),
    "practical_application": (
        "Directs listeners toward a concrete action, practice, decision, relationship, "
        "or lived response. Generic encouragement without a specific response is insufficient."
    ),
}


@dataclass(frozen=True, slots=True)
class StyleAnalysisOutcome:
    run: SermonAnalysisRun
    created: bool


def _sha256(value: object) -> str:
    if isinstance(value, bytes):
        payload = value
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def style_prompt(
    block: SemanticBlock,
    previous: SemanticBlock | None,
    following: SemanticBlock | None,
    *,
    prompt_version: str = STYLE_PROMPT_VERSION,
) -> str:
    definitions = "\n".join(
        f"{key.upper()}: {definition}" for key, definition in STYLE_DIMENSIONS.items()
    )
    previous_text = (
        " ".join(segment.text for segment in previous.segments[-2:])
        if previous is not None
        else "(none)"
    )
    following_text = (
        " ".join(segment.text for segment in following.segments[:2])
        if following is not None
        else "(none)"
    )
    return f"""You propose high-confidence preaching-style evidence from the CURRENT sermon transcript only. Evaluate each of the four dimensions independently and include every dimension that clearly qualifies; overlap is expected.
Prompt version: {prompt_version}

{definitions}

EXEGETICAL requires actual explanation of a biblical text's language, context, structure, or meaning; a quotation, named verse, or doctrinal claim alone is not exegesis. NARRATIVE requires a recounted event with actors and actions; a hypothetical, passing example, announcement, or generic encouragement is not narrative. DOCTRINAL requires reasoning about Christian belief, not merely mentioning Scripture or asserting a belief. PRACTICAL APPLICATION requires a specific lived response, not a slogan or vague encouragement.

Return the smallest contiguous CURRENT segment span that provides clear evidence. Multiple dimensions may use the same span. Propose nothing for ambiguous material. Do not classify the whole sermon. Do not return quotations, timestamps, explanations, confidence scores, or categories outside the supplied schema. PREVIOUS and FOLLOWING are context only and may never be cited.

PREVIOUS CONTEXT:
{previous_text}

CURRENT SEGMENTS:
{block.numbered_text()}

FOLLOWING CONTEXT:
{following_text}
"""


def _passes_style_acceptance_gate(
    dimension: str, proposal: AcceptedSemanticProposal
) -> bool:
    text = proposal.excerpt.casefold().replace("’", "'")
    if dimension == "exegetical_exposition":
        return bool(
            re.search(
                r"\b(?:word|phrase|verb|subject|sentence|verse|passage|chapter|text)\b"
                r".{0,140}\b(?:mean|means|connect|connects|explain|explains|refer|refers|"
                r"support|supports|describe|describes|context|because|says)\b",
                text,
            )
            or re.search(r"\b(?:does not|doesn't) mean\b", text)
            or re.search(r"\bnotice (?:that|how)\b", text)
            or re.search(r"\btranslated\b", text)
            or re.search(
                r"\b(?:paul|john|jesus|moses) says\b.{0,120}\b(?:because|connect|connects)\b",
                text,
            )
        )
    if dimension == "narrative_illustration":
        has_event_anchor = bool(
            re.search(
                r"\b(?:when i|when we|i was|i remember|i watched|i saw|we were|"
                r"last (?:week|month|year)|years ago|my (?:father|mother|friend|neighbor|family))\b",
                text,
            )
        )
        has_action = bool(
            re.search(
                r"\b(?:watched|saw|met|went|came|became|stopped|drove|refused|"
                r"carried|showed|taught|learned|happened|called|walked|found)\b",
                text,
            )
        )
        return has_event_anchor and has_action
    if dimension == "doctrinal_argument":
        has_reasoning = bool(
            re.search(
                r"\b(?:if|because|therefore|thus|rather than|must|would|"
                r"does not|cannot|consequently)\b",
                text,
            )
        )
        has_doctrine = bool(
            re.search(
                r"\b(?:god|christ|jesus|spirit|salvation|grace|faith|sin|gospel|"
                r"resurrection|atonement|justification|sanctification|deity|humanity|"
                r"image|eternal|church|scripture)\b",
                text,
            )
        )
        return has_reasoning and has_doctrine
    if dimension == "practical_application":
        return bool(
            re.search(
                r"\b(?:this week|before .{0,30} ends|call|ask forgiveness|choose|"
                r"put it on|make one|visit|learn .{0,30} name|listen|repair|"
                r"write|schedule|confess|apologize|forgive|stop|start)\b",
                text,
            )
        )
    return False


def validate_style_proposals(
    content: dict[str, Any], block: SemanticBlock
) -> SemanticValidationResult:
    grounded = validate_semantic_proposals(content, block, STYLE_DIMENSIONS)
    accepted = tuple(
        proposal
        for proposal in grounded.accepted
        if _passes_style_acceptance_gate(proposal.dimension, proposal)
    )
    rejected_by_gate = len(grounded.accepted) - len(accepted)
    rejection_counts = Counter(grounded.rejection_counts)
    if rejected_by_gate:
        rejection_counts["failed_dimension_acceptance_gate"] += rejected_by_gate
    return SemanticValidationResult(
        accepted=accepted,
        proposed_count=grounded.proposed_count,
        rejection_counts=dict(sorted(rejection_counts.items())),
    )


def _merged_intervals(
    intervals: list[tuple[float, float]], *, maximum_gap: float = 0.0
) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1] + maximum_gap:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _scripture_corroboration(
    database: Database,
    scripture_run_id: int,
    proposal: AcceptedSemanticProposal,
) -> list[dict[str, object]]:
    start_index = proposal.start_segment.index
    end_index = proposal.end_segment.index
    result: list[dict[str, object]] = []
    for evidence in database.list_sermon_analysis_evidence(scripture_run_id):
        if evidence.evidence_kind not in {
            "scripture_reference",
            "scripture_text_alignment",
        }:
            continue
        payload = json.loads(evidence.payload_json)
        evidence_start = payload.get("source_segment_start_index", evidence.segment_index)
        evidence_end = payload.get("source_segment_end_index", evidence.segment_index)
        if not isinstance(evidence_start, int) or not isinstance(evidence_end, int):
            continue
        if evidence_start <= end_index and start_index <= evidence_end:
            result.append(
                {
                    "evidence_key": evidence.evidence_key,
                    "evidence_kind": evidence.evidence_kind,
                    "canonical_reference": payload.get("canonical_reference"),
                }
            )
    return result


def analyze_sermon_style(
    database: Database,
    video: Video,
    client: LocalLlmClient,
    *,
    model_digest: str,
    context_size: int,
    analyzer_version: str = STYLE_ANALYZER_VERSION,
    prompt_version: str = STYLE_PROMPT_VERSION,
) -> StyleAnalysisOutcome:
    if not analyzer_version.strip() or not prompt_version.strip():
        raise ValueError("Style analyzer and prompt versions must not be blank")
    if not model_digest.strip():
        raise ValueError("Style analysis requires an exact model digest")
    extraction = database.get_latest_extraction_result_for_video(video.id)
    if extraction is None or extraction.proposed_json_path is None:
        raise ValueError(f"Video {video.youtube_video_id} has no identified sermon content")
    scripture_run = database.get_latest_sermon_analysis_run(
        video.id,
        SCRIPTURE_ANALYZER_KEY,
        analyzer_version=SCRIPTURE_ANALYZER_VERSION,
    )
    if scripture_run is None:
        raise ValueError(
            f"Video {video.youtube_video_id} needs {SCRIPTURE_ANALYZER_KEY}@"
            f"{SCRIPTURE_ANALYZER_VERSION} before style analysis"
        )

    source_path = Path(extraction.proposed_json_path)
    source_segments, sermon_start, sermon_duration = load_identified_sermon_source(
        source_path
    )
    source_content_sha256 = _sha256(
        canonical_sermon_source(source_segments, sermon_start, sermon_duration)
    )
    model_provenance = {
        "backend": "ollama_chat_json_schema",
        "model": client.model,
        "model_digest": model_digest,
        "context_size": context_size,
        "temperature": 0,
    }
    prompt_provenance = {
        "prompt_version": prompt_version,
        "prompt_template_sha256": _sha256(
            style_prompt(
                SemanticBlock(
                    0,
                    (SemanticSegment(0, "{CURRENT}", 0.0, 1.0),),
                ),
                None,
                None,
                prompt_version=prompt_version,
            )
        ),
        "block_version": STYLE_BLOCK_VERSION,
        "validation_version": SEMANTIC_VALIDATION_VERSION,
        "style_acceptance_version": STYLE_ACCEPTANCE_VERSION,
    }
    input_fingerprint = _sha256(
        {
            "analyzer_key": STYLE_ANALYZER_KEY,
            "analyzer_version": analyzer_version,
            "schema_version": STYLE_ANALYSIS_SCHEMA_VERSION,
            "source_content_sha256": source_content_sha256,
            "scripture_analysis_run_id": scripture_run.id,
            "scripture_analysis_input_fingerprint": scripture_run.input_fingerprint,
            "model_provenance": model_provenance,
            "prompt_provenance": prompt_provenance,
            "video_id": video.id,
        }
    )
    existing = database.get_sermon_analysis_run_by_fingerprint(input_fingerprint)
    if existing is not None:
        return StyleAnalysisOutcome(existing, False)

    semantic_segments = [
        SemanticSegment(
            segment.index,
            segment.text,
            segment.start_seconds,
            segment.end_seconds,
        )
        for segment in source_segments
    ]
    blocks = build_semantic_blocks(semantic_segments)
    if not blocks:
        raise ValueError("Identified sermon content has no timestamped semantic blocks")

    accepted: list[tuple[AcceptedSemanticProposal, int, str]] = []
    proposed_count = 0
    rejection_counts: Counter[str] = Counter()
    response_hashes: list[str] = []
    for index, block in enumerate(blocks):
        prompt = style_prompt(
            block,
            blocks[index - 1] if index > 0 else None,
            blocks[index + 1] if index + 1 < len(blocks) else None,
            prompt_version=prompt_version,
        )
        response = client.generate_json(
            prompt, semantic_proposal_schema(STYLE_DIMENSIONS, block)
        )
        if response.model != client.model:
            raise ValueError(
                f"Style model response changed identity: {client.model!r} -> "
                f"{response.model!r}"
            )
        response_sha = _sha256(response.raw_content)
        response_hashes.append(response_sha)
        validation = validate_style_proposals(response.content, block)
        proposed_count += validation.proposed_count
        rejection_counts.update(validation.rejection_counts)
        accepted.extend(
            (proposal, block.block_id, response_sha)
            for proposal in validation.accepted
        )

    by_dimension: dict[str, list[AcceptedSemanticProposal]] = defaultdict(list)
    evidence_rows = []
    for proposal, block_id, response_sha in accepted:
        by_dimension[proposal.dimension].append(proposal)
        corroboration = _scripture_corroboration(
            database, scripture_run.id, proposal
        )
        payload = {
            "dimension": proposal.dimension,
            "operational_definition": STYLE_DIMENSIONS[proposal.dimension],
            "evidence_source": "model_proposed_deterministically_validated",
            "source_segment_start_index": proposal.start_segment.index,
            "source_segment_end_index": proposal.end_segment.index,
            "source_word_count": proposal.word_count,
            "source_excerpt_sha256": _sha256(proposal.excerpt),
            "semantic_block_id": block_id,
            "model_response_sha256": response_sha,
            "model_provenance": model_provenance,
            "prompt_provenance": prompt_provenance,
            "validation_version": SEMANTIC_VALIDATION_VERSION,
            "style_acceptance_version": STYLE_ACCEPTANCE_VERSION,
            "scripture_corroboration": corroboration,
            "scripture_corroborated": bool(corroboration),
            "scripture_analysis_run_id": scripture_run.id,
        }
        evidence_key = _sha256(payload)
        evidence_rows.append(
            (
                "semantic_style_evidence",
                evidence_key,
                proposal.start_segment.index,
                proposal.start_seconds,
                proposal.end_seconds,
                None,
                None,
                proposal.excerpt,
                json.dumps(payload, sort_keys=True),
            )
        )

    dimension_measurements: dict[str, dict[str, object]] = {}
    for dimension in STYLE_DIMENSIONS:
        proposals = by_dimension[dimension]
        intervals = [(item.start_seconds, item.end_seconds) for item in proposals]
        merged = _merged_intervals(intervals)
        sustained = [
            interval
            for interval in _merged_intervals(intervals, maximum_gap=15.0)
            if interval[1] - interval[0] >= 60.0
        ]
        duration = sum(end - start for start, end in merged)
        dimension_measurements[dimension] = {
            "evidence_count": len(proposals),
            "duration_seconds": round(duration, 3),
            "sermon_duration_coverage_fraction": round(
                duration / sermon_duration, 6
            ),
            "sustained_run_count": len(sustained),
            "sustained_duration_seconds": round(
                sum(end - start for start, end in sustained), 3
            ),
            "scripture_corroborated_evidence_count": sum(
                bool(_scripture_corroboration(database, scripture_run.id, item))
                for item in proposals
            ),
        }
    analyzed_duration = sum(block.end_seconds - block.start_seconds for block in blocks)
    values: list[tuple[str, object, str | None]] = [
        ("semantic_dimensions", list(STYLE_DIMENSIONS), None),
        ("style_dimension_measurements", dimension_measurements, None),
        ("semantic_evidence_count", len(accepted), "evidence_spans"),
        ("model_proposal_count", proposed_count, "proposals"),
        ("rejected_proposal_count", sum(rejection_counts.values()), "proposals"),
        ("proposal_rejection_counts", dict(sorted(rejection_counts.items())), None),
        ("semantic_blocks_analyzed", len(blocks), "blocks"),
        ("semantic_analyzed_duration_seconds", round(analyzed_duration, 3), "seconds"),
        (
            "semantic_analysis_coverage_fraction",
            round(analyzed_duration / sermon_duration, 6),
            None,
        ),
        ("sermon_duration_seconds", sermon_duration, "seconds"),
        (
            "word_count",
            sum(
                len(re.findall(r"\b[\w]+(?:['’][\w]+)?\b", item.text))
                for item in semantic_segments
            ),
            "words",
        ),
        ("model_provenance", model_provenance, None),
        ("prompt_provenance", prompt_provenance, None),
        ("model_response_sha256", response_hashes, None),
        ("scripture_analysis_run_id", scripture_run.id, None),
    ]
    measurements = [
        (key, json.dumps(value, sort_keys=True), unit) for key, value, unit in values
    ]
    run, created = database.add_sermon_analysis_run(
        video_id=video.id,
        extraction_result_id=extraction.id,
        analyzer_key=STYLE_ANALYZER_KEY,
        analyzer_version=analyzer_version,
        source_kind="identified_sermon_semantic_blocks",
        source_path=str(source_path),
        source_content_sha256=source_content_sha256,
        input_fingerprint=input_fingerprint,
        measurements=measurements,
        evidence=evidence_rows,
    )
    return StyleAnalysisOutcome(run, created)
