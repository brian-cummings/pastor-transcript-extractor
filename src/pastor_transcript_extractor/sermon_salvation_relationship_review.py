"""Bounded review workflow for the first conditional salvation leaf pack."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.sermon_classification import TranscriptBlock
from pastor_transcript_extractor.sermon_classifier_typesafe import (
    SALVATION_RELATIONSHIPS_PACK,
    TypeSafeBlockCache,
    TypeSafeBlockClient,
)
from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIPS,
    SALVATION_RELATIONSHIPS_PACK_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
    SALVATION_ROUTE_POLICY_VERSION,
    salvation_relationship_pack_digest,
    salvation_route_decision,
)
from pastor_transcript_extractor.sermon_topic_profile_analysis import (
    read_topic_analysis_for_gate,
)
from pastor_transcript_extractor.sermon_topic_projection import (
    assess_topic_profile_projection,
)
from pastor_transcript_extractor.sermon_topic_stage4 import (
    assess_topic_stage4_readiness,
)
from pastor_transcript_extractor.sermon_topics import (
    TOPIC_PACK_VERSION,
    TopicBlockContext,
    resolve_topic_block_context,
)
from pastor_transcript_extractor.storage import Database


SALVATION_RELATIONSHIP_REVIEW_SCHEMA_VERSION = 1
SALVATION_RELATIONSHIP_REVIEW_POLICY_VERSION = (
    "salvation-relationships-out-of-sample-v3"
)
DEFAULT_SALVATION_RELATIONSHIP_REVIEW_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-relationships-review-v3.json"
)
DEFAULT_SALVATION_OBEDIENCE_CALIBRATION_OUTPUT = Path(
    "evaluation/sermon-topics/salvation-obedience-consequence-calibration-v1.json"
)
PRIOR_REVIEW_FINGERPRINT = (
    "e6ef7c6b8e8e6ee92588c3a7a045794694dac1941546043b1e0b0f6f92ce2980"
)
PRIOR_REVIEWED_CANDIDATE_KEYS = frozenset(
    {
        "281:124",
        "350:44",
        "1200:35",
        "3974:81",
        "4052:103",
        "4394:46",
        "4394:49",
        "4430:49",
        "4430:57",
        "4458:70",
        "4589:38",
        "4589:47",
    }
)
ALL_REVIEWED_CANDIDATE_KEYS = PRIOR_REVIEWED_CANDIDATE_KEYS | frozenset(
    {
        "281:123",
        "3973:81",
        "3974:91",
        "4394:44",
        "4394:45",
        "4430:27",
        "4430:31",
        "4430:48",
        "4458:66",
        "4458:68",
        "4589:30",
        "1200:44",
    }
)
OBEDIENCE_CONSEQUENCE_CALIBRATION_WINDOW = (0.55, 0.65)
OBEDIENCE_CONSEQUENCE_CALIBRATION_CANDIDATE_LIMIT = 12
OBEDIENCE_CONSEQUENCE_CALIBRATION_PER_PASTOR_LIMIT = 3
OBEDIENCE_CONSEQUENCE_CALIBRATION_CUES = (
    "works in you",
    "worketh in you",
    "living through",
    "lives through",
    "good works",
    "changed life",
    "righteousness",
    "obedience",
    "obey",
    "fruit",
    "evidence",
    "holy",
    "holiness",
    "transform",
    "born again",
)


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _routed_candidates(
    database: Database,
    cohort: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    readiness = assess_topic_stage4_readiness(database, cohort)
    if not readiness["ready"]:
        raise ValueError(
            "Salvation relationship review requires ready Stage 4 inputs: "
            + ", ".join(readiness["blockers"])
        )
    videos = {video.id: video for video in database.list_videos()}
    candidates: list[dict[str, Any]] = []
    for pastor in cohort["pastors"]:
        for sermon in pastor["sermons"]:
            video_id = int(sermon["video_id"])
            video = videos.get(video_id)
            if video is None:
                raise ValueError(f"Unknown salvation relationship video: {video_id}")
            gate = assess_topic_profile_projection(database, video)
            if (
                not gate.eligible
                or gate.source_path is None
                or gate.topic_analysis_fingerprint is None
            ):
                raise ValueError(
                    f"Video {video_id} is not eligible for salvation relationships"
                )
            analysis, _projection = read_topic_analysis_for_gate(gate)
            if analysis.get("question_pack_version") != TOPIC_PACK_VERSION:
                raise ValueError(
                    f"Video {video_id} uses a different broad topic pack"
                )
            raw_blocks = analysis.get("blocks")
            if not isinstance(raw_blocks, list):
                raise ValueError(f"Video {video_id} has no topic blocks")
            for raw_block in raw_blocks:
                if not isinstance(raw_block, Mapping):
                    continue
                route = salvation_route_decision(raw_block)
                if not route["route"]:
                    continue
                context = resolve_topic_block_context(raw_block)
                target = context.get("target_text")
                if not isinstance(target, str) or not target.strip():
                    raise ValueError(
                        f"Topic block {raw_block.get('block_id')} has no leaf target text"
                    )
                segment_indexes = raw_block.get("segment_indexes")
                if not isinstance(segment_indexes, list):
                    raise ValueError(
                        f"Topic block {raw_block.get('block_id')} has no segment indexes"
                    )
                candidates.append(
                    {
                        "candidate_key": f"{video_id}:{int(raw_block['block_id'])}",
                        "pastor": {
                            "display_name": pastor.get("display_name"),
                            "pastor_id": pastor.get("pastor_id"),
                            "slug": pastor.get("slug"),
                        },
                        "video_id": video_id,
                        "youtube_video_id": video.youtube_video_id,
                        "title": video.title,
                        "block_id": int(raw_block["block_id"]),
                        "start_seconds": float(raw_block["start_seconds"]),
                        "end_seconds": float(raw_block["end_seconds"]),
                        "segment_indexes": [int(value) for value in segment_indexes],
                        "leading_context": str(context.get("leading_context") or ""),
                        "target_text": target,
                        "trailing_context": str(context.get("trailing_context") or ""),
                        "context_diagnostics": dict(
                            context.get("diagnostics")
                            if isinstance(context.get("diagnostics"), Mapping)
                            else {}
                        ),
                        "route": route,
                        "topic_analysis_fingerprint": (
                            gate.topic_analysis_fingerprint
                        ),
                        "cache_dir": str(
                            Path(gate.source_path).parent / "inference-cache"
                        ),
                    }
                )
    if not candidates:
        raise ValueError("No blocks satisfy the reviewed salvation route")
    return candidates, str(readiness["input_fingerprint"])


def _select_review_candidates(
    candidates: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    fresh_candidates = [
        candidate
        for candidate in candidates
        if str(candidate["candidate_key"])
        not in PRIOR_REVIEWED_CANDIDATE_KEYS
    ]
    selected: list[dict[str, Any]] = []
    for pastor_slug in sorted(
        {
            str(candidate["pastor"].get("slug"))
            for candidate in fresh_candidates
        }
    ):
        pastor_candidates = sorted(
            (
                candidate
                for candidate in fresh_candidates
                if str(candidate["pastor"].get("slug")) == pastor_slug
            ),
            key=lambda candidate: (
                float(candidate["route"]["supporting_or_above_probability"]),
                int(candidate["video_id"]),
                int(candidate["block_id"]),
            ),
        )
        if len(pastor_candidates) < 3:
            raise ValueError(
                "Salvation relationship review requires at least three routed "
                f"blocks for pastor {pastor_slug}"
            )
        positions = (0, len(pastor_candidates) // 2, len(pastor_candidates) - 1)
        used: set[str] = set()
        for stratum, position in zip(
            ("threshold", "median", "strongest"),
            positions,
            strict=True,
        ):
            candidate = pastor_candidates[position]
            key = str(candidate["candidate_key"])
            if key in used:
                candidate = next(
                    (
                        item
                        for item in pastor_candidates
                        if str(item["candidate_key"]) not in used
                    ),
                    candidate,
                )
                key = str(candidate["candidate_key"])
            used.add(key)
            selected.append({**candidate, "review_stratum": stratum})
    return selected


def select_obedience_consequence_calibration_candidates(
    candidates: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Select a small fresh, diverse set using only deterministic text cues."""
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for candidate in candidates:
        key = str(candidate["candidate_key"])
        if key in ALL_REVIEWED_CANDIDATE_KEYS:
            continue
        text = str(candidate["target_text"]).lower()
        cue_score = sum(text.count(cue) for cue in OBEDIENCE_CONSEQUENCE_CALIBRATION_CUES)
        if cue_score:
            ranked.append((cue_score, key, candidate))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected: list[dict[str, Any]] = []
    pastor_counts: dict[str, int] = {}
    for cue_score, _key, candidate in ranked:
        pastor_slug = str(candidate["pastor"].get("slug"))
        if (
            pastor_counts.get(pastor_slug, 0)
            >= OBEDIENCE_CONSEQUENCE_CALIBRATION_PER_PASTOR_LIMIT
        ):
            continue
        selected.append({**candidate, "selection_cue_score": cue_score})
        pastor_counts[pastor_slug] = pastor_counts.get(pastor_slug, 0) + 1
        if len(selected) == OBEDIENCE_CONSEQUENCE_CALIBRATION_CANDIDATE_LIMIT:
            break
    if len(selected) < OBEDIENCE_CONSEQUENCE_CALIBRATION_CANDIDATE_LIMIT:
        raise ValueError(
            "Obedience-consequence calibration could not select twelve fresh "
            "cue-bearing routed blocks"
        )
    return selected


def evaluate_salvation_relationship_review(
    database: Database,
    cohort: Mapping[str, Any],
    *,
    model: str,
    client: TypeSafeBlockClient,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Run the bounded leaf sample through independent per-video caches."""
    candidates, readiness_fingerprint = _routed_candidates(database, cohort)
    selected = _select_review_candidates(candidates)
    evaluated, execution = evaluate_salvation_relationship_candidates(
        selected,
        model=model,
        client=client,
    )
    evaluated.sort(
        key=lambda item: (
            str(item["pastor"].get("slug")),
            ("threshold", "median", "strongest").index(item["review_stratum"]),
        )
    )
    identity = {
        "schema_version": SALVATION_RELATIONSHIP_REVIEW_SCHEMA_VERSION,
        "review_policy_version": SALVATION_RELATIONSHIP_REVIEW_POLICY_VERSION,
        "cohort_sha256": cohort.get("cohort_sha256"),
        "readiness_input_fingerprint": readiness_fingerprint,
        "broad_question_pack_version": TOPIC_PACK_VERSION,
        "route_policy_version": SALVATION_ROUTE_POLICY_VERSION,
        "leaf_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "leaf_pack_digest": salvation_relationship_pack_digest(),
        "requested_model_id": model,
        "routed_candidate_count": len(candidates),
        "prior_review": {
            "input_fingerprint": PRIOR_REVIEW_FINGERPRINT,
            "excluded_candidate_keys": sorted(
                PRIOR_REVIEWED_CANDIDATE_KEYS
            ),
        },
        "cases": evaluated,
    }
    packet = {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": "observations_pending_review",
        "policy_effect": "none",
        "cache": {
            "identity": "per_video_versioned_answer_pack",
            "location": "beside_source_classification",
        },
        "interpretation": (
            "This out-of-sample packet keeps the accepted leaf questions and route "
            "unchanged while excluding every development case. It does not activate "
            "leaf collection during ordinary reclassification or authorize "
            "profile-level theological claims."
        ),
    }
    return packet, execution


def evaluate_salvation_relationship_candidates(
    selected: Sequence[Mapping[str, Any]],
    *,
    model: str,
    client: TypeSafeBlockClient,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Evaluate selected candidates through the shared per-video leaf caches."""
    evaluated: list[dict[str, Any]] = []
    cache_hits = 0
    cache_misses = 0
    provider_requests = 0
    for video_id in sorted({int(item["video_id"]) for item in selected}):
        video_candidates = [
            item for item in selected if int(item["video_id"]) == video_id
        ]
        blocks = [
            TranscriptBlock(
                block_id=int(item["block_id"]),
                segment_indexes=list(item["segment_indexes"]),
                start_seconds=float(item["start_seconds"]),
                end_seconds=float(item["end_seconds"]),
                text=str(item["target_text"]),
            )
            for item in video_candidates
        ]
        contexts = {
            int(item["block_id"]): TopicBlockContext(
                leading_context=str(item["leading_context"]),
                target_text=str(item["target_text"]),
                trailing_context=str(item["trailing_context"]),
                diagnostics=dict(item["context_diagnostics"]),
            )
            for item in video_candidates
        }
        cache = TypeSafeBlockCache(
            Path(str(video_candidates[0]["cache_dir"])),
            model=model,
        )
        answers = cache.assess_packs(
            client,
            {},
            blocks,
            requested_packs=frozenset({SALVATION_RELATIONSHIPS_PACK}),
            topic_contexts=contexts,
        )
        cache_hits += cache.hits
        cache_misses += cache.misses
        provider_requests += cache.provider_requests
        for item in video_candidates:
            answer = answers[int(item["block_id"])]
            provenance = answer.request_provenance.get(
                SALVATION_RELATIONSHIPS_PACK, {}
            )
            evaluated.append(
                {
                    **{
                        key: value
                        for key, value in item.items()
                        if key not in {"cache_dir", "context_diagnostics"}
                    },
                    "leaf_probabilities": {
                        relationship: round(
                            float(
                                answer.salvation_relationship_probabilities[
                                    relationship
                                ]
                            ),
                            6,
                        )
                        for relationship in SALVATION_RELATIONSHIPS
                    },
                    "resolved_model_id": answer.resolved_model_id,
                    "source_request_key": (
                        provenance.get("request_key")
                        if isinstance(provenance, Mapping)
                        else None
                    ),
                }
            )
    return evaluated, {
        "hits": cache_hits,
        "misses": cache_misses,
        "provider_requests": provider_requests,
    }


def evaluate_obedience_consequence_calibration(
    database: Database,
    cohort: Mapping[str, Any],
    *,
    model: str,
    client: TypeSafeBlockClient,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Evaluate a final bounded sample for the unresolved consequence leaf."""
    candidates, readiness_fingerprint = _routed_candidates(database, cohort)
    selected = select_obedience_consequence_calibration_candidates(candidates)
    evaluated, execution = evaluate_salvation_relationship_candidates(
        selected,
        model=model,
        client=client,
    )
    relationship = "obedience_as_consequence_or_evidence"
    evaluated.sort(
        key=lambda item: (
            float(item["leaf_probabilities"][relationship]),
            str(item["candidate_key"]),
        )
    )
    lower, upper = OBEDIENCE_CONSEQUENCE_CALIBRATION_WINDOW
    in_window = [
        item
        for item in evaluated
        if lower <= float(item["leaf_probabilities"][relationship]) <= upper
    ]
    probes = sorted(
        sorted(
            in_window,
            key=lambda item: (
                abs(float(item["leaf_probabilities"][relationship]) - 0.60),
                str(item["candidate_key"]),
            ),
        )[:6],
        key=lambda item: (
            float(item["leaf_probabilities"][relationship]),
            str(item["candidate_key"]),
        ),
    )
    identity = {
        "schema_version": SALVATION_RELATIONSHIP_REVIEW_SCHEMA_VERSION,
        "review_policy_version": "salvation-obedience-consequence-calibration-v1",
        "cohort_sha256": cohort.get("cohort_sha256"),
        "readiness_input_fingerprint": readiness_fingerprint,
        "broad_question_pack_version": TOPIC_PACK_VERSION,
        "route_policy_version": SALVATION_ROUTE_POLICY_VERSION,
        "leaf_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
        "leaf_pack_digest": salvation_relationship_pack_digest(),
        "observation_policy_version": (
            SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION
        ),
        "settled_thresholds": dict(
            SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS
        ),
        "relationship": relationship,
        "calibration_window": [lower, upper],
        "prior_boundary_review_fingerprint": (
            "7f76957f5ff89fe010a943713c8092353ded4fe69e1ad501c149308b55ee4d2e"
        ),
        "excluded_candidate_keys": sorted(ALL_REVIEWED_CANDIDATE_KEYS),
        "selection": {
            "candidate_limit": OBEDIENCE_CONSEQUENCE_CALIBRATION_CANDIDATE_LIMIT,
            "per_pastor_limit": (
                OBEDIENCE_CONSEQUENCE_CALIBRATION_PER_PASTOR_LIMIT
            ),
            "cues": list(OBEDIENCE_CONSEQUENCE_CALIBRATION_CUES),
        },
        "attempted_cases": evaluated,
        "probes": probes,
    }
    enough_probes = len(probes) >= 4
    return {
        **identity,
        "input_fingerprint": _canonical_hash(identity),
        "status": (
            "observations_pending_review"
            if enough_probes
            else "insufficient_boundary_probes"
        ),
        "policy_effect": "none",
        "interpretation": (
            "This cache-first calibration evaluates twelve fresh, cue-bearing routed "
            "blocks but presents at most six whose obedience-as-consequence "
            "probability falls from 0.55 through 0.65. It changes no question, route, "
            "threshold, or production collection policy."
        ),
    }, execution


def render_obedience_consequence_calibration(packet: Mapping[str, Any]) -> str:
    relationship = str(packet["relationship"])
    lines = [
        "# Salvation obedience-as-consequence calibration",
        "",
        f"- Status: `{packet['status']}`",
        f"- Policy effect: `{packet['policy_effect']}`",
        f"- Leaf pack: `{packet['leaf_pack_version']}`",
        f"- Attempted fresh cases: `{len(packet['attempted_cases'])}`",
        f"- Boundary probes: `{len(packet['probes'])}`",
        "- Calibration window: "
        f"`{float(packet['calibration_window'][0]):.2f}`–"
        f"`{float(packet['calibration_window'][1]):.2f}`",
        f"- Packet fingerprint: `{packet['input_fingerprint']}`",
        "",
        str(packet["interpretation"]),
        "",
        "The other eleven relationship boundaries are settled and out of scope. "
        "For each probe, decide only whether the target asserts obedience, works, "
        "holiness, or transformed conduct as a consequence, fruit, sign, or evidence "
        "of salvation or grace.",
        "",
        "## Attempted cases",
        "",
        "| Case | Pastor | Cue score | Probability | In review window |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    probe_keys = {str(item["candidate_key"]) for item in packet["probes"]}
    for case in packet["attempted_cases"]:
        probability = float(case["leaf_probabilities"][relationship])
        lines.append(
            f"| {case['candidate_key']} | {case['pastor']['display_name']} | "
            f"{case['selection_cue_score']} | {probability:.3f} | "
            f"{'yes' if str(case['candidate_key']) in probe_keys else 'no'} |"
        )
    lines.extend(["", "## Boundary probes", ""])
    if not packet["probes"]:
        lines.extend(
            [
                "No attempted case fell inside the calibration window. The packet is "
                "diagnostic only and cannot settle this leaf.",
                "",
            ]
        )
    for case in packet["probes"]:
        probability = float(case["leaf_probabilities"][relationship])
        lines.extend(
            [
                f"### {probability:.3f} / {case['candidate_key']}",
                "",
                f"- Pastor: {case['pastor']['display_name']}",
                f"- Recording: `{case['youtube_video_id']}` — {case['title']}",
                f"- Time: `{case['start_seconds']}`–`{case['end_seconds']}`",
                f"- Selection cue score: `{case['selection_cue_score']}`",
                "",
                "Leading context:",
                "",
                f"> {str(case['leading_context']).replace(chr(10), ' ')}",
                "",
                "Target text:",
                "",
                f"> {str(case['target_text']).replace(chr(10), ' ')}",
                "",
                "Trailing context:",
                "",
                f"> {str(case['trailing_context']).replace(chr(10), ' ')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_salvation_relationship_review(packet: Mapping[str, Any]) -> str:
    lines = [
        "# Salvation relationships review",
        "",
        f"- Status: `{packet['status']}`",
        f"- Policy effect: `{packet['policy_effect']}`",
        f"- Route policy: `{packet['route_policy_version']}`",
        f"- Leaf pack: `{packet['leaf_pack_version']}`",
        f"- Routed cached blocks: `{packet['routed_candidate_count']}`",
        f"- Review cases: `{len(packet['cases'])}`",
        "- Prior review: "
        f"`{packet['prior_review']['input_fingerprint']}` "
        f"(`{len(packet['prior_review']['excluded_candidate_keys'])}` cases excluded)",
        f"- Cache identity: `{packet['cache']['identity']}`",
        f"- Cache location: `{packet['cache']['location']}`",
        f"- Packet fingerprint: `{packet['input_fingerprint']}`",
        "",
        str(packet["interpretation"]),
        "",
        "For each case, review whether high-probability relationships are actually "
        "asserted by the target and whether important asserted relationships were "
        "missed. Context may clarify the target but cannot supply the relationship.",
        "",
    ]
    for case in packet["cases"]:
        probabilities = case["leaf_probabilities"]
        lines.extend(
            [
                f"## {case['pastor']['display_name']} / video {case['video_id']} / "
                f"block {case['block_id']} / {case['review_stratum']}",
                "",
                f"- Recording: `{case['youtube_video_id']}` — {case['title']}",
                f"- Time: `{case['start_seconds']}`–`{case['end_seconds']}`",
                "- Broad route probability: "
                f"`{float(case['route']['supporting_or_above_probability']):.3f}`",
                "- Leaf relationships: "
                + ", ".join(
                    f"{name}={float(probability):.3f}"
                    for name, probability in sorted(
                        probabilities.items(),
                        key=lambda item: (-float(item[1]), item[0]),
                    )
                ),
                "",
                "Leading context:",
                "",
                f"> {str(case['leading_context']).replace(chr(10), ' ')}",
                "",
                "Target text:",
                "",
                f"> {str(case['target_text']).replace(chr(10), ' ')}",
                "",
                "Trailing context:",
                "",
                f"> {str(case['trailing_context']).replace(chr(10), ' ')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _write_review_artifact(
    path: Path,
    packet: Mapping[str, Any],
    render: Callable[[Mapping[str, Any]], str],
) -> tuple[Path, Path, bool]:
    json_path = path.expanduser().resolve()
    markdown_path = json_path.with_suffix(".md")
    expected_json = (
        json.dumps(packet, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    expected_markdown = render(packet)
    if json_path.exists() and markdown_path.exists():
        try:
            existing_json = json_path.read_text(encoding="utf-8")
            existing_markdown = markdown_path.read_text(encoding="utf-8")
            existing = json.loads(existing_json)
        except (OSError, UnicodeError, json.JSONDecodeError):
            existing = existing_json = existing_markdown = None
        if (
            isinstance(existing, Mapping)
            and existing.get("input_fingerprint")
            == packet.get("input_fingerprint")
            and existing_json == expected_json
            and existing_markdown == expected_markdown
        ):
            return json_path, markdown_path, True
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(expected_json, encoding="utf-8")
    markdown_path.write_text(expected_markdown, encoding="utf-8")
    return json_path, markdown_path, False


def write_salvation_relationship_review(
    path: Path,
    packet: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    return _write_review_artifact(path, packet, render_salvation_relationship_review)


def write_obedience_consequence_calibration(
    path: Path,
    packet: Mapping[str, Any],
) -> tuple[Path, Path, bool]:
    return _write_review_artifact(
        path,
        packet,
        render_obedience_consequence_calibration,
    )
