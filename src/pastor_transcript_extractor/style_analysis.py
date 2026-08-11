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
    build_semantic_blocks,
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
STYLE_ANALYZER_VERSION = "3"
STYLE_PROMPT_VERSION = "sermon-style-runs-v1"
STYLE_BLOCK_VERSION = "nonoverlapping-75s-3600chars-v1"
STYLE_ACCEPTANCE_VERSION = "observable-dimension-gates-v2"
STYLE_RUN_MERGE_VERSION = "boundary-touching-continuation-v1"
STYLE_ANALYSIS_SCHEMA_VERSION = 2
STYLE_OUTPUT_TOKEN_BUDGET = 512

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


@dataclass(frozen=True, slots=True)
class AcceptedStyleProposal:
    dimension: str
    supporting_evidence: AcceptedSemanticProposal
    style_run: AcceptedSemanticProposal


@dataclass(frozen=True, slots=True)
class StyleProposalValidationResult:
    accepted: tuple[AcceptedStyleProposal, ...]
    proposed_count: int
    rejection_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class _AcceptedBlockStyleProposal:
    proposal: AcceptedStyleProposal
    block: SemanticBlock
    response_sha256: str


@dataclass(frozen=True, slots=True)
class _DerivedStyleRun:
    dimension: str
    start_segment: SemanticSegment
    end_segment: SemanticSegment
    supporting_proposals: tuple[_AcceptedBlockStyleProposal, ...]


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

Return at most one proposal per dimension and no more than four proposals total. For each proposal, STYLE RUN boundaries must cover the full contiguous portion of CURRENT in which that semantic mode remains active. SUPPORT boundaries must identify the smallest strong excerpt inside that run that proves the category. Do not shorten STYLE RUN to the proof excerpt. Multiple dimensions may overlap. Propose nothing for ambiguous material. Do not return quotations, timestamps, explanations, confidence scores, or categories outside the supplied schema. PREVIOUS and FOLLOWING are context only and may never be cited.

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
                r"write|schedule|confess|apologize|forgive)\b",
                text,
            )
        )
    return False


def style_proposal_schema(block: SemanticBlock) -> dict[str, Any]:
    segment_ids = [segment.evidence_id for segment in block.segments]
    properties = {
        "dimension": {"type": "string", "enum": list(STYLE_DIMENSIONS)},
        "run_start_segment_id": {"type": "string", "enum": segment_ids},
        "run_end_segment_id": {"type": "string", "enum": segment_ids},
        "support_start_segment_id": {"type": "string", "enum": segment_ids},
        "support_end_segment_id": {"type": "string", "enum": segment_ids},
    }
    return {
        "type": "object",
        "properties": {
            "proposals": {
                "type": "array",
                "maxItems": len(STYLE_DIMENSIONS),
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                },
            }
        },
        "required": ["proposals"],
        "additionalProperties": False,
    }


def validate_style_proposals(
    content: dict[str, Any], block: SemanticBlock
) -> StyleProposalValidationResult:
    raw = content.get("proposals")
    if not isinstance(raw, list):
        return StyleProposalValidationResult((), 0, {"invalid_proposals_container": 1})
    accepted: list[AcceptedStyleProposal] = []
    rejected: Counter[str] = Counter()
    seen_dimensions: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            rejected["invalid_proposal_shape"] += 1
            continue
        dimension = item.get("dimension")
        if not isinstance(dimension, str) or dimension not in STYLE_DIMENSIONS:
            rejected["unknown_dimension"] += 1
            continue
        if dimension in seen_dimensions:
            rejected["duplicate_dimension_in_block"] += 1
            continue
        seen_dimensions.add(dimension)
        support = validate_semantic_proposals(
            {
                "proposals": [
                    {
                        "dimension": dimension,
                        "start_segment_id": item.get("support_start_segment_id"),
                        "end_segment_id": item.get("support_end_segment_id"),
                    }
                ]
            },
            block,
            STYLE_DIMENSIONS,
        )
        run = validate_semantic_proposals(
            {
                "proposals": [
                    {
                        "dimension": dimension,
                        "start_segment_id": item.get("run_start_segment_id"),
                        "end_segment_id": item.get("run_end_segment_id"),
                    }
                ]
            },
            block,
            STYLE_DIMENSIONS,
        )
        if not support.accepted:
            rejected.update(
                {f"support_{key}": value for key, value in support.rejection_counts.items()}
            )
            continue
        if not run.accepted:
            rejected.update(
                {f"run_{key}": value for key, value in run.rejection_counts.items()}
            )
            continue
        supporting_evidence = support.accepted[0]
        style_run = run.accepted[0]
        if (
            style_run.start_segment.index > supporting_evidence.start_segment.index
            or style_run.end_segment.index < supporting_evidence.end_segment.index
        ):
            rejected["support_outside_run"] += 1
            continue
        if not _passes_style_acceptance_gate(dimension, supporting_evidence):
            rejected["failed_dimension_acceptance_gate"] += 1
            continue
        accepted.append(
            AcceptedStyleProposal(dimension, supporting_evidence, style_run)
        )
    return StyleProposalValidationResult(
        tuple(accepted), len(raw), dict(sorted(rejected.items()))
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


def _derive_style_runs(
    proposals: list[_AcceptedBlockStyleProposal],
) -> list[_DerivedStyleRun]:
    """Merge only explicit boundary-to-boundary continuation across adjacent blocks."""
    result: list[_DerivedStyleRun] = []
    for item in sorted(
        proposals,
        key=lambda value: (
            value.proposal.dimension,
            value.proposal.style_run.start_segment.index,
        ),
    ):
        candidate = _DerivedStyleRun(
            item.proposal.dimension,
            item.proposal.style_run.start_segment,
            item.proposal.style_run.end_segment,
            (item,),
        )
        if not result or result[-1].dimension != candidate.dimension:
            result.append(candidate)
            continue
        previous = result[-1]
        previous_item = previous.supporting_proposals[-1]
        previous_touches_boundary = (
            previous.end_segment.index
            == previous_item.block.segments[-1].index
        )
        current_touches_boundary = (
            candidate.start_segment.index == item.block.segments[0].index
        )
        adjacent_blocks = item.block.block_id == previous_item.block.block_id + 1
        gap = candidate.start_segment.start_seconds - previous.end_segment.end_seconds
        if (
            adjacent_blocks
            and previous_touches_boundary
            and current_touches_boundary
            and gap <= 15.0
        ):
            result[-1] = _DerivedStyleRun(
                previous.dimension,
                previous.start_segment,
                candidate.end_segment,
                (*previous.supporting_proposals, item),
            )
        else:
            result.append(candidate)
    return result


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
        "output_token_budget": STYLE_OUTPUT_TOKEN_BUDGET,
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
        "style_run_merge_version": STYLE_RUN_MERGE_VERSION,
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

    accepted: list[_AcceptedBlockStyleProposal] = []
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
            prompt,
            style_proposal_schema(block),
            max_tokens=STYLE_OUTPUT_TOKEN_BUDGET,
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
            _AcceptedBlockStyleProposal(proposal, block, response_sha)
            for proposal in validation.accepted
        )

    by_dimension: dict[str, list[_AcceptedBlockStyleProposal]] = defaultdict(list)
    evidence_rows: list[tuple[object, ...]] = []
    support_keys: dict[int, str] = {}
    for item in accepted:
        proposal = item.proposal
        support = proposal.supporting_evidence
        by_dimension[proposal.dimension].append(item)
        corroboration = _scripture_corroboration(
            database, scripture_run.id, support
        )
        payload = {
            "dimension": proposal.dimension,
            "operational_definition": STYLE_DIMENSIONS[proposal.dimension],
            "semantic_role": "supporting_evidence",
            "evidence_source": "model_proposed_deterministically_validated",
            "source_segment_start_index": support.start_segment.index,
            "source_segment_end_index": support.end_segment.index,
            "source_word_count": support.word_count,
            "source_excerpt_sha256": _sha256(support.excerpt),
            "proposed_run_segment_start_index": proposal.style_run.start_segment.index,
            "proposed_run_segment_end_index": proposal.style_run.end_segment.index,
            "semantic_block_id": item.block.block_id,
            "model_response_sha256": item.response_sha256,
            "model_provenance": model_provenance,
            "prompt_provenance": prompt_provenance,
            "validation_version": SEMANTIC_VALIDATION_VERSION,
            "style_acceptance_version": STYLE_ACCEPTANCE_VERSION,
            "scripture_corroboration": corroboration,
            "scripture_corroborated": bool(corroboration),
            "scripture_analysis_run_id": scripture_run.id,
        }
        evidence_key = _sha256(payload)
        support_keys[id(item)] = evidence_key
        evidence_rows.append(
            (
                "semantic_style_evidence",
                evidence_key,
                support.start_segment.index,
                support.start_seconds,
                support.end_seconds,
                None,
                None,
                support.excerpt,
                json.dumps(payload, sort_keys=True),
            )
        )

    style_runs = _derive_style_runs(accepted)
    for run in style_runs:
        supporting_keys = [support_keys[id(item)] for item in run.supporting_proposals]
        run_segments = tuple(
            segment
            for item in run.supporting_proposals
            for segment in item.proposal.style_run.segments
        )
        unique_segments = {
            segment.index: segment for segment in run_segments
        }
        excerpt = " ".join(
            unique_segments[index].text for index in sorted(unique_segments)
        )
        payload = {
            "dimension": run.dimension,
            "operational_definition": STYLE_DIMENSIONS[run.dimension],
            "semantic_role": "candidate_representative_run",
            "boundary_status": "unreviewed",
            "source_segment_start_index": run.start_segment.index,
            "source_segment_end_index": run.end_segment.index,
            "source_excerpt_sha256": _sha256(excerpt),
            "supporting_evidence_keys": supporting_keys,
            "continuation_piece_count": len(run.supporting_proposals),
            "merge_version": STYLE_RUN_MERGE_VERSION,
            "model_provenance": model_provenance,
            "prompt_provenance": prompt_provenance,
        }
        evidence_rows.append(
            (
                "semantic_style_run",
                _sha256(payload),
                run.start_segment.index,
                run.start_segment.start_seconds,
                run.end_segment.end_seconds,
                None,
                None,
                excerpt,
                json.dumps(payload, sort_keys=True),
            )
        )

    dimension_measurements: dict[str, dict[str, object]] = {}
    for dimension in STYLE_DIMENSIONS:
        proposals = by_dimension[dimension]
        support_intervals = [
            (
                item.proposal.supporting_evidence.start_seconds,
                item.proposal.supporting_evidence.end_seconds,
            )
            for item in proposals
        ]
        dimension_runs = [run for run in style_runs if run.dimension == dimension]
        run_intervals = [
            (run.start_segment.start_seconds, run.end_segment.end_seconds)
            for run in dimension_runs
        ]
        accepted_evidence_duration = sum(
            end - start for start, end in _merged_intervals(support_intervals)
        )
        candidate_run_duration = sum(
            end - start for start, end in _merged_intervals(run_intervals)
        )
        dimension_measurements[dimension] = {
            "evidence_count": len(proposals),
            "accepted_evidence_duration_seconds": round(
                accepted_evidence_duration, 3
            ),
            "accepted_evidence_coverage_fraction": round(
                accepted_evidence_duration / sermon_duration, 6
            ),
            "candidate_style_run_count": len(dimension_runs),
            "candidate_style_run_duration_seconds": round(
                candidate_run_duration, 3
            ),
            "candidate_style_run_coverage_fraction": round(
                candidate_run_duration / sermon_duration, 6
            ),
            "candidate_style_run_boundary_status": "unreviewed",
            "scripture_corroborated_evidence_count": sum(
                bool(
                    _scripture_corroboration(
                        database,
                        scripture_run.id,
                        item.proposal.supporting_evidence,
                    )
                )
                for item in proposals
            ),
        }
    analyzed_duration = sum(block.end_seconds - block.start_seconds for block in blocks)
    values: list[tuple[str, object, str | None]] = [
        ("semantic_dimensions", list(STYLE_DIMENSIONS), None),
        ("style_dimension_measurements", dimension_measurements, None),
        ("semantic_evidence_count", len(accepted), "evidence_spans"),
        ("candidate_style_run_count", len(style_runs), "style_runs"),
        ("style_run_boundary_status", "unreviewed", None),
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
