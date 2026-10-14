"""Bounded source/material development using shared independent leaf infrastructure."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

from pastor_transcript_extractor.sermon_leaf_packs import SOURCE_MATERIAL, listener_directive_route
from pastor_transcript_extractor.sermon_listener_directive_review import prepare_review, fingerprint

DEFAULT_SOURCE_REVIEW_OUTPUT = Path("evaluation/sermon-topics/source-material-review-v1.json")
SOURCE_PROBE_PATH = Path(__file__).parent / "data" / "source-material-probes-v1.json"
SOURCE_ROUTE_VERSION = "source-material-route-eligible-v1-candidate"
# Inspection cues do not establish source presence or decide coverage routing.
SOURCE_CUES = {
    "biblical_story_cue": re.compile(r"\b(Jesus|Peter|Moses|Abraham|disciples|David)\b", re.I),
    "testimony_cue": re.compile(r"\b(I|my|testimony|testified|experience)\b", re.I),
    "attribution_cue": re.compile(r"\b(writes|wrote|quoted|quote|history|White|Manual|confession)\b", re.I),
}


def source_material_route(block: Mapping[str, Any]) -> dict[str, Any]:
    return {**listener_directive_route(block), "policy_version": SOURCE_ROUTE_VERSION,
            "signal": "final_content_projection_eligibility",
            "topic_signal_role": "sampling_diagnostic_only",
            "status": "candidate_pending_bounded_review"}


def select_source_cases(blocks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    remaining = sorted((b for b in blocks if source_material_route(b)["route"]),
                       key=lambda b: int(b["block_id"]))
    chosen = []
    for stratum in (*SOURCE_CUES, "no_source_cue"):
        candidates = [b for b in remaining if
                      (bool(SOURCE_CUES[stratum].search(b["target_text"])) if stratum in SOURCE_CUES
                       else not any(c.search(b["target_text"]) for c in SOURCE_CUES.values()))]
        if not candidates:
            continue
        item = candidates[len(candidates) // 2]
        chosen.append({**item, "review_stratum": stratum,
                       "expected_positive_leaves": None,
                       "proposed_label": "inspect_target_material_and_attribution"})
        remaining.remove(item)
    # Keep bounded coverage when one or more cue strata are absent.
    for item in remaining:
        if len(chosen) == 4:
            break
        chosen.append({**item, "review_stratum": "coverage_fallback",
                       "expected_positive_leaves": None,
                       "proposed_label": "inspect_target_material_and_attribution"})
    return chosen


def prepare_source_review(database, *, model: str, probe_cache: Path) -> dict[str, Any]:
    packet = prepare_review(database, model=model, probe_cache=probe_cache,
                            pack=SOURCE_MATERIAL, probe_path=SOURCE_PROBE_PATH,
                            selector=select_source_cases, router=source_material_route)
    packet.update({
        "review_policy": "source-material-bounded-review-v1",
        "route_policy_version": SOURCE_ROUTE_VERSION,
        "proposed_decision": "Review six independent source/form questions, target-only attribution, and eligibility-only routing separately. Recommend readiness only after semantic interpretation; preserve overlaps and defer production thresholds.",
        "routing_proposal": "Route all current final projection-eligible blocks. No broad-topic cutoff or cue gates source measurement.",
        "sampling_limit": "At most twelve natural blocks from three reviewed sermons plus 23 authored probes; not a corpus recall or workload estimate.",
        "broader_collection_activated": False,
        "stratum_counts": {name: sum(c["review_stratum"] == name for c in packet["cases"])
                           for name in (*SOURCE_CUES, "no_source_cue", "coverage_fallback")},
    })
    packet.pop("input_fingerprint")
    packet["input_fingerprint"] = fingerprint(packet)
    return packet
