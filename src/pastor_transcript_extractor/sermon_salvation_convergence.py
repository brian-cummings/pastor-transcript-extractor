"""Provider-free convergence of the frozen nine salvation observations."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any, Mapping

from pastor_transcript_extractor.analysis_artifact_cache import database_snapshot, file_signature, write_json_markdown
from pastor_transcript_extractor.sermon_salvation_profile_analysis import (
    APPROVED_SALVATION_COLLECTION_REVIEW_FINGERPRINT,
    _sermon_measurements,
)
from pastor_transcript_extractor.sermon_salvation_relationships import (
    SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
    SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
    SALVATION_RELATIONSHIPS_PACK_VERSION,
    SALVATION_ROUTE_POLICY_VERSION,
    SALVATION_ROUTE_THRESHOLD,
    UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS,
    refresh_salvation_relationship_projection,
    resolve_salvation_relationship_analysis_artifact,
    salvation_route_decision,
    salvation_relationship_pack_digest,
)
from pastor_transcript_extractor.sermon_salvation_repeatability_expansion import (
    CONVERGENCE_SAMPLE_SIZES,
)
from pastor_transcript_extractor.sermon_topic_profile_analysis import read_classification_for_gate
from pastor_transcript_extractor.sermon_topic_projection import (
    TOPIC_PROFILE_PROJECTION_POLICY_VERSION, assess_topic_profile_projection,
)
from pastor_transcript_extractor.sermon_topics import TOPIC_PACK_VERSION, resolve_topic_analysis_artifact
from pastor_transcript_extractor.storage import Database


POLICY_VERSION = "salvation-nine-leaf-convergence-v1-partial-checkpoints"
DEFAULT_OUTPUT = Path("evaluation/sermon-topics/salvation-nine-leaf-convergence-v1.json")
ORDER_COUNT = 128
MEASUREMENT_VERSION = "salvation-cohort-measurements-v1"
DEFAULT_MEASUREMENT_CACHE = Path("evaluation/sermon-topics/salvation-cohort-measurements-v1.json")


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 6)


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 6)


def _load_sermon(database: Database, row: Mapping[str, Any], profile_id: int, *, gate: Any = None) -> dict[str, Any]:
    video_id = int(row["video_id"])
    video = database.get_video_by_id(video_id)
    if video is None:
        raise ValueError(f"Frozen cohort video {video_id} is missing")
    if gate is None:
        gate = assess_topic_profile_projection(database, video)
    if not gate.eligible or gate.profile_id != profile_id:
        raise ValueError(f"Frozen cohort video {video_id} no longer passes the topic gate")
    source_before = file_signature(gate.source_path)
    classification = read_classification_for_gate(gate)
    if file_signature(gate.source_path) != source_before:
        raise ValueError(f"Video {video_id} classification changed while loading; rerun")
    topic = resolve_topic_analysis_artifact(classification)
    routed_topic_blocks = [block for block in topic.get("blocks", [])
                           if isinstance(block, Mapping) and salvation_route_decision(block)["route"]]
    try:
        stored = resolve_salvation_relationship_analysis_artifact(classification)
    except ValueError as error:
        if "no cached TypeSafe salvation relationship analysis" not in str(error):
            raise
        if routed_topic_blocks:
            return {"video_id": video_id, "baseline": bool(row.get("baseline")),
                    "measurement_status": "unavailable_missing_cached_leaf_artifact",
                    "routed_topic_block_count": len(routed_topic_blocks),
                    "topic_artifact_sha256": _hash(topic),
                    "classification_path": str(gate.source_path)}
        stored = None
    if routed_topic_blocks and stored is not None and (
        stored.get("question_pack_version") != SALVATION_RELATIONSHIPS_PACK_VERSION
        or stored.get("question_pack_digest") != salvation_relationship_pack_digest()
    ):
        raise ValueError(f"Video {video_id} has stale salvation question evidence")
    artifact = deepcopy(dict(stored)) if stored is not None else {"blocks": []}
    refresh_salvation_relationship_projection(artifact, topic)
    if artifact.get("missing_current_routed_block_ids"):
        raise ValueError(f"Video {video_id} lacks current routed salvation evidence")
    source = {"artifact": artifact, "video_id": video_id, "title": video.title,
              "youtube_video_id": video.youtube_video_id,
              "stored_artifact_sha256": _hash(stored) if stored is not None else None}
    if int(artifact["routed_block_count"]) == 0:
        sermon = {"video_id": video_id, "profile_id": profile_id,
                  "title": video.title, "youtube_video_id": video.youtube_video_id,
                  "routed_block_count": 0, "source_artifact_sha256": source["stored_artifact_sha256"],
                  "relationships": {leaf: {"evidence": [], "observation_count": 0,
                                           "observed": False, "routed_block_fraction": 0.0}
                                    for leaf in SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS}}
    else:
        sermon = _sermon_measurements(source, row, profile_id=profile_id)
    sermon["measurement_status"] = ("zero_routed_blocks" if int(artifact["routed_block_count"]) == 0
                                     else "measured")
    sermon["period_key"] = row.get("period_key")
    sermon["series_key"] = row.get("series_key")
    sermon["baseline"] = bool(row.get("baseline"))
    sermon["classification_path"] = str(gate.source_path)
    sermon["topic_artifact_sha256"] = _hash(topic)
    sermon["projected_artifact_sha256"] = _hash(artifact)
    return sermon


def _orders(sermons: list[Mapping[str, Any]], seed: str) -> list[list[int]]:
    ids = [int(item["video_id"]) for item in sermons]
    baseline = sorted(int(item["video_id"]) for item in sermons if item["baseline"])
    additions = sorted(set(ids) - set(baseline))
    primary = baseline + additions
    orders = [primary]
    for index in range(ORDER_COUNT):
        orders.append(sorted(ids, key=lambda video_id: _hash([seed, index, video_id])))
    return orders


def validate_cohort_proposal(proposal: Mapping[str, Any]) -> None:
    if proposal.get("policy_version") != "salvation-exact-cohort-proposal-v3-diversity":
        raise ValueError("Convergence requires the frozen v3 cohort proposal")
    if proposal.get("provider_requests") != 0:
        raise ValueError("Convergence requires provider-free cohort selection")
    proposal_identity = {key: value for key, value in proposal.items()
                         if key not in {"input_fingerprint", "status", "analytical_credit_granted",
                                        "provider_requests", "excluded_profile_ids"}}
    if _hash(proposal_identity) != proposal.get("input_fingerprint"):
        raise ValueError("Frozen cohort proposal fingerprint does not match its contents")


def validate_cohort_measurements(proposal: Mapping[str, Any], sermons_by_profile: Mapping[int, list[Mapping[str, Any]]]) -> None:
    for pastor in proposal["pastors"]:
        profile_id = int(pastor["profile_id"])
        expected = {int(row["video_id"]) for row in pastor["included"]}
        loaded = sermons_by_profile[profile_id]
        loaded_ids = [int(item["video_id"]) for item in loaded]
        if set(loaded_ids) != expected or len(loaded_ids) != len(expected):
            raise ValueError(f"Profile {profile_id} sermon evidence does not match the frozen proposal")
        measured = [item for item in loaded if item.get("measurement_status") !=
                    "unavailable_missing_cached_leaf_artifact"]
        if len([item for item in measured if item["baseline"]]) != 3:
            raise ValueError(f"Profile {profile_id} must preserve three baseline sermons")


def build_convergence(proposal: Mapping[str, Any], sermons_by_profile: Mapping[int, list[Mapping[str, Any]]]) -> dict[str, Any]:
    """Analyze every supported checkpoint, preserving unavailable N=12 entries."""
    validate_cohort_proposal(proposal)
    validate_cohort_measurements(proposal, sermons_by_profile)
    reports = []
    for pastor in proposal["pastors"]:
        profile_id = int(pastor["profile_id"])
        expected = {int(row["video_id"]) for row in pastor["included"]}
        loaded = sermons_by_profile[profile_id]
        unavailable = [item for item in loaded if item.get("measurement_status") ==
                       "unavailable_missing_cached_leaf_artifact"]
        sermons = [item for item in loaded if item.get("measurement_status") !=
                   "unavailable_missing_cached_leaf_artifact"]
        by_id = {int(item["video_id"]): item for item in sermons}
        orders = _orders(sermons, str(proposal["input_fingerprint"]))
        full_n = len(sermons)
        relationships = {}
        for leaf in SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS:
            values = {video_id: float(item["relationships"][leaf]["routed_block_fraction"])
                      for video_id, item in by_id.items()}
            detections = {video_id: bool(item["relationships"][leaf]["observed"])
                          for video_id, item in by_id.items()}
            full_mean = _mean(list(values.values()))
            checkpoints = []
            for n in CONVERGENCE_SAMPLE_SIZES:
                if n > full_n:
                    checkpoints.append({"n": n, "status": "unavailable_insufficient_measured_sermons",
                                        "selected_sermons": len(expected),
                                        "measured_sermons": full_n,
                                        "unmeasured_video_ids": [item["video_id"] for item in unavailable]})
                    continue
                means = [_mean([values[video_id] for video_id in order[:n]]) for order in orders]
                first = orders[0][:n]
                checkpoints.append({"n": n, "status": "available",
                                    "primary_video_ids": first,
                                    "primary_equal_sermon_mean": means[0],
                                    "primary_sermons_with_observation": sum(detections[video_id] for video_id in first),
                                    "primary_absolute_delta_from_full_available": round(abs(means[0] - full_mean), 6),
                                    "order_sensitivity": {"orders": len(orders), "minimum": min(means),
                                                          "p05": _quantile(means, .05),
                                                          "median": _quantile(means, .5),
                                                          "p95": _quantile(means, .95), "maximum": max(means)}})
            period_groups = {key: [values[int(item["video_id"])] for item in sermons
                                   if item.get("period_key") == key]
                             for key in sorted({str(item["period_key"]) for item in sermons
                                                if item.get("period_key")})}
            period_sensitivity = [{"period_key": key, "sermons": len(group), "equal_sermon_mean": _mean(group)}
                                  for key, group in period_groups.items()]
            series_sensitivity = []
            counts = Counter(item.get("series_key") for item in sermons if item.get("series_key"))
            for key in sorted(counts):
                if counts[key] < 2:
                    continue
                inside = [values[int(item["video_id"])] for item in sermons if item.get("series_key") == key]
                outside = [values[int(item["video_id"])] for item in sermons if item.get("series_key") != key]
                series_sensitivity.append({"series_key": key, "within_sermons": len(inside),
                                           "outside_sermons": len(outside),
                                           "within_mean": _mean(inside), "outside_mean": _mean(outside),
                                           "absolute_delta": round(abs(_mean(inside) - _mean(outside)), 6)})
            relationships[leaf] = {"full_available_n": full_n, "full_available_equal_sermon_mean": full_mean,
                                   "full_sermons_with_observation": sum(detections.values()),
                                   "evidence_status": ("positive_evidence_observed" if any(detections.values())
                                                       else "insufficient_positive_evidence"),
                                   "checkpoints": checkpoints, "period_sensitivity": period_sensitivity,
                                   "series_sensitivity": series_sensitivity}
        reports.append({"profile_id": profile_id, "display_name": pastor["display_name"],
                        "sermon_count": full_n, "selected_sermon_count": len(expected),
                        "video_ids": sorted(expected),
                        "unavailable_sermons": unavailable,
                        "zero_routed_sermon_ids": sorted(int(item["video_id"]) for item in sermons
                                                          if item.get("measurement_status") == "zero_routed_blocks"),
                        "missing_period_provenance": sum(item.get("period_key") is None for item in sermons),
                        "missing_series_provenance": sum(item.get("series_key") is None for item in sermons),
                        "source_artifacts": [{"video_id": item["video_id"],
                                              "stored_artifact_sha256": item["source_artifact_sha256"],
                                              "topic_artifact_sha256": item["topic_artifact_sha256"],
                                              "projected_artifact_sha256": item["projected_artifact_sha256"]}
                                             for item in sorted(sermons, key=lambda item: item["video_id"])],
                        "relationships": relationships})
    identity = {"schema_version": 1, "policy_version": POLICY_VERSION,
                "proposal_fingerprint": proposal["input_fingerprint"],
                "observation_policy_version": SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
                "question_pack_version": SALVATION_RELATIONSHIPS_PACK_VERSION,
                "approved_collection_review_fingerprint": APPROVED_SALVATION_COLLECTION_REVIEW_FINGERPRINT,
                "sample_sizes": list(CONVERGENCE_SAMPLE_SIZES), "order_count": ORDER_COUNT + 1,
                "measured_relationships": list(SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS),
                "unresolved_relationships": sorted(UNRESOLVED_SALVATION_RELATIONSHIP_OBSERVATIONS),
                "pastors": reports}
    return {**identity, "input_fingerprint": _hash(identity), "provider_requests": 0,
            "status": "diagnostic_pending_interpretation",
            "analytical_credit_granted": False}


def collect_cohort_measurements(
    database: Database, proposal: Mapping[str, Any], cache_path: Path | None = None,
    now: datetime | None = None,
) -> tuple[dict[int, list[Mapping[str, Any]]], bool]:
    """Reuse evidence across diagnostics before reading or projecting classifications."""
    validate_cohort_proposal(proposal)
    current = now or datetime.now(timezone.utc)
    snapshot = database_snapshot(database.database_path, current)
    contract = {"measurement_version": MEASUREMENT_VERSION,
                "proposal_fingerprint": proposal["input_fingerprint"],
                "observation_policy": SALVATION_RELATIONSHIP_OBSERVATION_POLICY_VERSION,
                "thresholds": SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS,
                "approved_review": APPROVED_SALVATION_COLLECTION_REVIEW_FINGERPRINT,
                "route_policy": SALVATION_ROUTE_POLICY_VERSION,
                "route_threshold": SALVATION_ROUTE_THRESHOLD,
                "topic_pack": TOPIC_PACK_VERSION,
                "projection_policy": TOPIC_PROFILE_PROJECTION_POLICY_VERSION,
                "question_pack_digest": salvation_relationship_pack_digest(),
                "snapshot": snapshot}
    if cache_path is not None:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            identity = {key: value for key, value in cached.items() if key != "input_fingerprint"}
            files = cached["source_files"]
            if (cached["contract"] == contract and _hash(identity) == cached["input_fingerprint"]
                    and isinstance(files, list)
                    and all(file_signature(item["path"]) == item for item in files)
                    and database_snapshot(database.database_path, current) == snapshot):
                sermons = {int(key): value for key, value in cached["sermons_by_profile"].items()}
                validate_cohort_measurements(proposal, sermons)
                return sermons, True
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
            pass
    sermons = {}
    sources = {}
    for pastor in proposal["pastors"]:
        profile_id = int(pastor["profile_id"])
        sermons[profile_id] = []
        for row in pastor["included"]:
            video = database.get_video_by_id(int(row["video_id"]))
            if video is None:
                raise ValueError(f"Frozen cohort video {row['video_id']} is missing")
            gate = assess_topic_profile_projection(database, video)
            before = file_signature(gate.source_path)
            sermon = _load_sermon(database, row, profile_id, gate=gate)
            if file_signature(gate.source_path) != before or sermon["classification_path"] != str(gate.source_path):
                raise ValueError("Classification changed during cohort measurement; rerun")
            sources[str(gate.source_path)] = before
            sermons[profile_id].append(sermon)
    validate_cohort_measurements(proposal, sermons)
    files = [sources[key] for key in sorted(sources)]
    if (database_snapshot(database.database_path, current) != snapshot
            or any(file_signature(item["path"]) != item for item in files)):
        raise ValueError("Application evidence changed during cohort measurement; rerun")
    if cache_path is not None:
        identity = {"contract": contract, "source_files": files,
                    "sermons_by_profile": {str(key): value for key, value in sermons.items()}}
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({**identity, "input_fingerprint": _hash(identity)},
                                         indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return sermons, False


def evaluate_convergence(database: Database, proposal: Mapping[str, Any]) -> dict[str, Any]:
    sermons, _ = collect_cohort_measurements(database, proposal)
    return build_convergence(proposal, sermons)


def render_convergence(report: Mapping[str, Any]) -> str:
    lines = ["# Nine-leaf salvation convergence", "",
             f"- Fingerprint: `{report['input_fingerprint']}`",
             f"- Frozen cohort proposal: `{report['proposal_fingerprint']}`",
             "- Provider requests: 0", "- Analytical credit: none pending interpretation", "",
             "Each rate gives one sermon equal weight. The primary order preserves the three",
             "baseline sermons, then adds selected recordings by video ID. Order sensitivity",
             "uses 128 deterministic permutations of all selected independent sermons.",
             "A sermon with no salvation-routed blocks contributes an observed-zero rate",
             "and is listed separately. A missing cached leaf artifact with routed topic",
             "blocks is unmeasured and cannot support that checkpoint. Unknown period/series",
             "labels are excluded from named-group means but remain in the measured cohort",
             "and outside-series comparison. Zero observations mean",
             "insufficient positive evidence, not stable absence. No numerical pass threshold",
             "is fitted to this cohort.", ""]
    for pastor in report["pastors"]:
        lines += [f"## {pastor['display_name']} (profile {pastor['profile_id']})", "",
                  f"Selected independent sermons: {pastor['selected_sermon_count']}; "
                  f"measured sermons: {pastor['sermon_count']}; "
                  f"unmeasured video IDs: {[item['video_id'] for item in pastor['unavailable_sermons']]}; "
                  f"zero-route video IDs: {pastor['zero_routed_sermon_ids']}; "
                  f"missing period labels: "
                  f"{pastor['missing_period_provenance']}; missing series labels: "
                  f"{pastor['missing_series_provenance']}.", "",
                  "| Leaf | Full mean | Observed sermons | N=3 | N=4 | N=5 | N=6 | N=8 | N=10 | N=12 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for leaf, item in pastor["relationships"].items():
            values = [f"{point['primary_equal_sermon_mean']:.3f}" if point["status"] == "available" else "—"
                      for point in item["checkpoints"]]
            lines.append(f"| `{leaf}` | {item['full_available_equal_sermon_mean']:.3f} | "
                         f"{item['full_sermons_with_observation']}/{pastor['sermon_count']} | " + " | ".join(values) + " |")
        lines += ["", "Per-leaf order distributions, period comparisons, and replicated-series",
                  "inside/outside comparisons are in the JSON report. The full mean uses all",
                  "available selected sermons, including Ryder's N=11.", ""]
    return "\n".join(lines).rstrip() + "\n"


def write_convergence(path: Path, report: Mapping[str, Any]) -> tuple[Path, Path, bool]:
    return write_json_markdown(path, report, render_convergence(report))
