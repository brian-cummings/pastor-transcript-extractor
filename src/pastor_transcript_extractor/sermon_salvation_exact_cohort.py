"""Provider-free, cache-aware proposal for an exact salvation repeatability cohort."""
from __future__ import annotations

from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from pastor_transcript_extractor.sermon_salvation_repeatability_expansion import (
    CONVERGENCE_SAMPLE_SIZES,
    TARGET_MINIMUM_PERIODS,
    TARGET_MINIMUM_SERMONS_PER_PERIOD,
    TARGET_MINIMUM_SERMONS_PER_SERIES,
    TARGET_SERMONS_PER_PASTOR,
    _canonical_hash,
)
from pastor_transcript_extractor.storage import Database


POLICY_VERSION = "salvation-exact-cohort-proposal-v3-diversity"
EVIDENCE_POLICY_VERSION = "salvation-exact-cohort-evidence-v1"
DEFAULT_OUTPUT = Path("evaluation/sermon-topics/salvation-exact-cohort-proposal-v3.json")
DEFAULT_EVIDENCE_CACHE = Path("evaluation/sermon-topics/salvation-exact-cohort-evidence-cache-v1.json")
DEFAULT_INTEGRITY_REVIEW = Path("evaluation/sermon-topics/salvation-exact-cohort-integrity-review-v2.json")
MAX_DOCUMENTED_SERIES_SERMONS = TARGET_SERMONS_PER_PASTOR // 2
MIN_DISTINCT_OUTSIDE_TITLES = 3
TARGET_PROFILES = (117, 80, 130)
_WORDS = re.compile(r"[a-z0-9']+")
_SERIES = re.compile(r"Part\s+\d+\s+of\s+the\s+Series:\s*(.+?)(?:\.\s+By\b|$)", re.I)


def _file_identity(path: str | None, content_sha256: str | None) -> dict[str, Any]:
    if not path:
        return {"path": None, "available": False}
    file = Path(path)
    if not file.is_file():
        return {"path": path, "available": False}
    stat = file.stat()
    return {"path": path, "available": True, "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "stored_sha256": content_sha256}


def _artifact_inputs(database: Database, inventory: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    """Read only artifact pointers; unchanged source files can reuse cached evidence."""
    result = {}
    for pastor in inventory["pastors"]:
        if int(pastor["profile_id"]) not in TARGET_PROFILES:
            continue
        for candidate in pastor["candidates"]:
            video_id = int(candidate["video_id"])
            transcripts = database.list_transcript_artifacts_for_video(video_id)
            transcripts = [item for item in transcripts if item.raw_text_path and
                           item.superseded_by_artifact_id is None]
            transcripts.sort(key=lambda item: (item.artifact_kind == "canonical", item.id), reverse=True)
            transcript = transcripts[0] if transcripts else None
            metadata = database.get_latest_metadata_artifact_for_video(video_id)
            media = database.list_media_artifacts_for_video(video_id)
            source_hashes = sorted({item.content_sha256 for item in media
                                    if item.artifact_kind == "source_audio"})
            result[video_id] = {
                "transcript": {"artifact_id": transcript.id if transcript else None,
                               **_file_identity(transcript.raw_text_path if transcript else None,
                                                transcript.content_sha256 if transcript else None)},
                "metadata": {"artifact_id": metadata.id if metadata else None,
                             "source_kind": metadata.source_kind if metadata else None,
                             **_file_identity(metadata.artifact_path if metadata else None,
                                              metadata.content_sha256 if metadata else None)},
                "source_audio_sha256": source_hashes,
            }
    return result


def _shingles(text: str, width: int = 5) -> set[str]:
    words = _WORDS.findall(text.lower())
    return {" ".join(words[index:index + width]) for index in range(max(0, len(words) - width + 1))}


def _source_evidence(inputs: Mapping[int, Mapping[str, Any]]) -> tuple[dict[int, dict[str, Any]], dict[int, set[str]]]:
    details: dict[int, dict[str, Any]] = {}
    shingles: dict[int, set[str]] = {}
    for video_id, item in inputs.items():
        meta = item["metadata"]
        raw: Mapping[str, Any] = {}
        if meta["available"]:
            payload = json.loads(Path(meta["path"]).read_text(encoding="utf-8"))
            raw = payload.get("raw_metadata", {})
        upload = raw.get("upload_date") or raw.get("release_date")
        period = None
        if meta.get("source_kind") == "yt_dlp_full_video" and isinstance(upload, str):
            try:
                parsed = date.fromisoformat(upload[:4] + "-" + upload[4:6] + "-" + upload[6:8])
                period = f"{parsed.year}-h{1 if parsed.month <= 6 else 2}"
            except ValueError:
                pass
        description = str(raw.get("description") or "")
        match = _SERIES.search(description)
        transcript = item["transcript"]
        if transcript["available"]:
            content = Path(transcript["path"]).read_text(encoding="utf-8")
            shingles[video_id] = _shingles(content)
            transcript_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        else:
            shingles[video_id] = set()
            transcript_digest = None
        details[video_id] = {
            "artifact_provenance": item,
            "transcript_sha256": transcript_digest,
            "source_period_key": period,
            "source_period_evidence": ({"source_kind": "stored_youtube_upload_date",
                                        "value": upload, "metadata_artifact_id": meta["artifact_id"],
                                        "metadata_sha256": meta.get("stored_sha256")}
                                       if period else None),
            "source_series_name": match.group(1).strip() if match else None,
            "source_series_evidence": ({"source_kind": "stored_youtube_description",
                                        "excerpt": match.group(0)[:240],
                                        "metadata_artifact_id": meta["artifact_id"],
                                        "metadata_sha256": meta.get("stored_sha256")}
                                       if match else None),
            "transcript_word_shingle_count": len(shingles[video_id]),
        }
    return details, shingles


def _pair_evidence(inventory: Mapping[str, Any], source: Mapping[int, Mapping[str, Any]],
                   shingles: Mapping[int, set[str]]) -> list[dict[str, Any]]:
    result = []
    for pastor in inventory["pastors"]:
        if int(pastor["profile_id"]) not in TARGET_PROFILES:
            continue
        rows = sorted(pastor["candidates"], key=lambda item: int(item["video_id"]))
        for index, a in enumerate(rows):
            for b in rows[index + 1:]:
                aid, bid = int(a["video_id"]), int(b["video_id"])
                x, y = shingles[aid], shingles[bid]
                shared = len(x & y)
                containment = round(shared / min(len(x), len(y)), 5) if x and y else None
                same_title = str(a["title"]).strip().casefold() == str(b["title"]).strip().casefold()
                common_audio = sorted(set(source[aid]["artifact_provenance"]["source_audio_sha256"])
                                      & set(source[bid]["artifact_provenance"]["source_audio_sha256"]))
                if not same_title and not common_audio and (containment or 0) < .10:
                    continue
                if common_audio:
                    decision = "same_recording"
                elif same_title and containment is not None and containment >= .05:
                    decision = "same_sermon_likely"
                elif same_title:
                    decision = "same_title_unresolved"
                else:
                    decision = "transcript_overlap_review"
                result.append({"video_ids": [aid, bid], "profile_id": int(pastor["profile_id"]),
                               "decision": decision, "matching_title": same_title,
                               "shared_5_word_shingles": shared,
                               "shorter_transcript_containment": containment,
                               "shared_source_audio_sha256": common_audio,
                               "transcript_sha256": [source[aid]["transcript_sha256"],
                                                     source[bid]["transcript_sha256"]],
                               "source_period_keys": [source[aid]["source_period_key"],
                                                      source[bid]["source_period_key"]]})
    return result


def collect_exact_cohort_evidence(database: Database, inventory: Mapping[str, Any],
                                  cache_path: Path) -> tuple[dict[str, Any], bool]:
    """Cache bounded metadata/transcript analysis by immutable artifact identities."""
    inputs = _artifact_inputs(database, inventory)
    fingerprint = _canonical_hash({"policy": EVIDENCE_POLICY_VERSION,
                                   "inventory": _canonical_hash(inventory),
                                   "artifacts": inputs})
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("artifact_fingerprint") == fingerprint:
                return cached, True
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    source, shingles = _source_evidence(inputs)
    packet = {"artifact_fingerprint": fingerprint, "source": source,
              "pairs": _pair_evidence(inventory, source, shingles)}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return packet, False


def _groups(ids: set[int], pairs: list[Mapping[str, Any]]) -> list[list[int]]:
    parent = {video_id: video_id for video_id in ids}
    def root(video_id: int) -> int:
        while parent[video_id] != video_id:
            video_id = parent[video_id]
        return video_id
    for pair in pairs:
        a, b = (int(value) for value in pair["video_ids"])
        if a in parent and b in parent and pair["decision"] in {
            "same_recording", "same_sermon_split", "same_sermon_likely",
            "same_title_unresolved", "transcript_overlap_review"
        }:
            parent[root(b)] = root(a)
    grouped: dict[int, list[int]] = {}
    for video_id in sorted(ids):
        grouped.setdefault(root(video_id), []).append(video_id)
    return sorted(grouped.values(), key=lambda group: group[0])


def _normalized_title(title: str | None) -> str:
    return " ".join(_WORDS.findall(str(title or "").lower()))


def build_exact_cohort_proposal(inventory: Mapping[str, Any], cohort: Mapping[str, Any],
                                evidence: Mapping[str, Any],
                                integrity_review: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Select once, preserve baseline, and state every unmet replication contract."""
    baseline_by_profile = {int(p["profile_id"]): p for p in inventory["pastors"]}
    baseline_by_id = {int(sermon["video_id"]): sermon for pastor in cohort["pastors"]
                      for sermon in pastor["sermons"]}
    reviewed_series_by_source_name = {}
    for video_id, baseline in baseline_by_id.items():
        detail = evidence["source"].get(str(video_id), evidence["source"].get(video_id, {}))
        source_name = detail.get("source_series_name")
        if source_name and baseline.get("series_key"):
            reviewed_series_by_source_name[source_name.casefold()] = baseline["series_key"]
    review = integrity_review or {}
    if review and review.get("inventory_fingerprint") != inventory.get("input_fingerprint"):
        raise ValueError("Integrity review belongs to a different candidate inventory")
    if review and review.get("cohort_sha256") != cohort.get("cohort_sha256"):
        raise ValueError("Integrity review belongs to a different baseline cohort")
    pair_adjudications = review.get("pair_adjudications", {})
    candidate_provenance = review.get("candidate_provenance", {})
    reports = []
    for profile_id in TARGET_PROFILES:
        pastor = baseline_by_profile.get(profile_id)
        if pastor is None:
            raise ValueError(f"Expansion inventory is missing profile {profile_id}")
        rows = {int(item["video_id"]): item for item in pastor["candidates"]}
        baseline_ids = {int(value) for value in pastor["baseline_video_ids"]}
        if len(baseline_ids) != 3 or not baseline_ids <= rows.keys():
            raise ValueError(f"Profile {profile_id} must preserve three eligible baseline sermons")
        pairs = []
        for raw in evidence["pairs"]:
            if int(raw["profile_id"]) != profile_id:
                continue
            pair = dict(raw)
            pair_key = "-".join(str(value) for value in pair["video_ids"])
            adjudication = pair_adjudications.get(pair_key)
            if adjudication:
                if adjudication.get("decision") not in {"same_sermon_split", "independent_sermons"}:
                    raise ValueError(f"Invalid integrity adjudication for {pair_key}")
                if not adjudication.get("evidence"):
                    raise ValueError(f"Integrity adjudication {pair_key} requires evidence")
                pair["decision"] = adjudication["decision"]
                pair["review_evidence"] = adjudication["evidence"]
            pairs.append(pair)
        groups = _groups(set(rows), pairs)
        alternates: dict[int, int] = {}
        equivalence = []
        for group in groups:
            baselines = sorted(baseline_ids & set(group))
            representative = baselines[0] if baselines else min(
                group, key=lambda video_id: (-int(rows[video_id].get("eligible_block_count") or 0), video_id))
            for video_id in group:
                if video_id != representative:
                    alternates[video_id] = representative
            equivalence.append({"video_ids": group, "representative_video_id": representative,
                                "status": ("independent_candidate" if len(group) == 1 else
                                           "confirmed_same_sermon_split" if all(
                                               pair["decision"] == "same_sermon_split"
                                               for pair in pairs if set(pair["video_ids"]) <= set(group)) else
                                           "adjudication_required" if any(
                                    pair["decision"].endswith("unresolved") or pair["decision"] == "transcript_overlap_review"
                                    for pair in pairs if set(pair["video_ids"]) <= set(group)) else "probable_equivalence"),
                                "pair_evidence": [pair for pair in pairs
                                                  if set(pair["video_ids"]) <= set(group)]})
        candidates = []
        for video_id, row in sorted(rows.items()):
            detail = evidence["source"][str(video_id)] if str(video_id) in evidence["source"] else evidence["source"][video_id]
            baseline = baseline_by_id.get(video_id)
            period = baseline.get("period_key") if baseline else (row.get("period_key") or detail["source_period_key"])
            period_evidence = baseline.get("period_evidence") if baseline else (row.get("period_evidence") or detail["source_period_evidence"])
            series = baseline.get("series_key") if baseline else None
            series_evidence = {"source_kind": "reviewed_baseline_cohort", "cohort_sha256": cohort.get("cohort_sha256")}
            if not baseline:
                name = detail.get("source_series_name")
                if name:
                    series = reviewed_series_by_source_name.get(name.casefold()) or re.sub(
                        r"[^a-z0-9]+", "-", name.lower()).strip("-")
                    series_evidence = {**detail["source_series_evidence"],
                                       "reviewed_baseline_series_match":
                                       name.casefold() in reviewed_series_by_source_name}
                else:
                    series_evidence = None
                reviewed = candidate_provenance.get(str(video_id), {})
                if reviewed:
                    for field in ("period", "series"):
                        assignment = reviewed.get(field)
                        if not assignment:
                            continue
                        if not assignment.get("key") or not assignment.get("evidence"):
                            raise ValueError(f"Reviewed {field} for {video_id} requires source evidence")
                        if field == "period":
                            period, period_evidence = assignment["key"], assignment["evidence"]
                        else:
                            series, series_evidence = assignment["key"], assignment["evidence"]
            candidates.append({"video_id": video_id, "youtube_video_id": row.get("youtube_video_id"),
                               "title": row.get("title"), "source_id": row.get("source_id"),
                               "eligible_block_count": row.get("eligible_block_count"),
                               "gate_input_fingerprint": row.get("gate_input_fingerprint"),
                               "baseline": video_id in baseline_ids,
                               "period_key": period, "period_evidence": period_evidence,
                               "series_key": series, "series_evidence": series_evidence,
                               "artifact_provenance": detail["artifact_provenance"],
                               "transcript_sha256": detail["transcript_sha256"]})
        by_id = {item["video_id"]: item for item in candidates}
        eligible = [item for item in candidates if item["video_id"] not in alternates
                    and item["video_id"] not in baseline_ids]
        eligible.sort(key=lambda item: (not bool(item["period_key"]),
                                        not bool(item["series_key"]), item["video_id"]))
        selected_ids = baseline_ids | {item["video_id"] for item in eligible[:TARGET_SERMONS_PER_PASTOR - 3]}
        included = [by_id[video_id] for video_id in sorted(selected_ids)]
        excluded = []
        for item in candidates:
            video_id = item["video_id"]
            if video_id in selected_ids:
                continue
            excluded.append({**item, "reason": ("equivalence_group_alternate" if video_id in alternates else "capacity"),
                             "representative_video_id": alternates.get(video_id)})
        series_counts = Counter(item["series_key"] for item in included if item["series_key"])
        period_counts = Counter(item["period_key"] for item in included if item["period_key"])
        replicated_series = sum(count >= TARGET_MINIMUM_SERMONS_PER_SERIES for count in series_counts.values())
        replicated_periods = sum(count >= TARGET_MINIMUM_SERMONS_PER_PERIOD for count in period_counts.values())
        largest_series_key = min(series_counts, key=lambda key: (-series_counts[key], key)) if series_counts else None
        largest_series_count = series_counts.get(largest_series_key, 0)
        outside_largest = ([item for item in included if item["series_key"] != largest_series_key]
                           if largest_series_key else included)
        distinct_outside_titles = len({_normalized_title(item["title"]) for item in outside_largest})
        shortfalls = {
            "independent_sermons": max(0, TARGET_SERMONS_PER_PASTOR - len(included)),
            "replicated_periods": max(0, TARGET_MINIMUM_PERIODS - replicated_periods),
            "documented_series_concentration": max(0, largest_series_count - MAX_DOCUMENTED_SERIES_SERMONS),
            "outside_largest_title_diversity": max(0, MIN_DISTINCT_OUTSIDE_TITLES - distinct_outside_titles),
            "missing_series_provenance": sum(item["series_key"] is None for item in included),
            "missing_period_provenance": sum(item["period_key"] is None for item in included),
            "unresolved_equivalence_groups": sum(group["status"] == "adjudication_required" for group in equivalence),
        }
        contract_blockers = [key for key in (
            "independent_sermons", "replicated_periods", "documented_series_concentration",
            "outside_largest_title_diversity", "unresolved_equivalence_groups"
        ) if shortfalls[key] > 0]
        reports.append({"profile_id": profile_id, "display_name": pastor["display_name"],
                        "baseline_video_ids": sorted(baseline_ids), "included": included,
                        "excluded": excluded, "equivalence_groups": equivalence,
                        "series_counts": dict(sorted(series_counts.items())),
                        "replicated_series_count": replicated_series,
                        "largest_documented_series": {"key": largest_series_key,
                                                      "sermons": largest_series_count,
                                                      "maximum": MAX_DOCUMENTED_SERIES_SERMONS},
                        "distinct_source_titles_outside_largest": distinct_outside_titles,
                        "period_counts": dict(sorted(period_counts.items())),
                        "shortfalls": shortfalls,
                        "contract_blockers": contract_blockers,
                        "contract_satisfied": not contract_blockers})
    identity = {"schema_version": 1, "policy_version": POLICY_VERSION,
                "inventory_fingerprint": inventory.get("input_fingerprint"),
                "cohort_sha256": cohort.get("cohort_sha256"),
                "artifact_fingerprint": evidence.get("artifact_fingerprint"),
                "integrity_review_fingerprint": _canonical_hash(review),
                "bounded_discovery": review.get("bounded_discovery", {}),
                "target_profiles": list(TARGET_PROFILES),
                "equivalence_policy": {
                    "transcript_comparison": "five-word shingle containment against shorter transcript",
                    "shared_source_audio_hash": "same_recording",
                    "matching_title_with_containment_at_least": .05,
                    "matching_title_below_boundary": "same_title_unresolved",
                    "different_title_containment_review_at_least": .10,
                    "group_counting": "one conservative representative per connected equivalence group",
                    "representative_order": "baseline, then eligible block count descending, then video ID",
                    "addition_order": "period provenance, series provenance, then video ID",
                },
                "selection_contract": {"sermons_per_pastor": TARGET_SERMONS_PER_PASTOR,
                                       "series_diversity": {"maximum_documented_series_sermons":
                                                            MAX_DOCUMENTED_SERIES_SERMONS,
                                                            "minimum_distinct_source_titles_outside_largest":
                                                            MIN_DISTINCT_OUTSIDE_TITLES,
                                                            "unassigned_series_membership": "visible; bounded human integrity review"},
                                       "series_sensitivity": "within-versus-outside for each documented replicated series",
                                       "minimum_sermons_per_replicated_series_diagnostic":
                                           TARGET_MINIMUM_SERMONS_PER_SERIES,
                                       "minimum_replicated_periods": TARGET_MINIMUM_PERIODS,
                                       "minimum_sermons_per_period": TARGET_MINIMUM_SERMONS_PER_PERIOD,
                                       "convergence_sample_sizes": list(CONVERGENCE_SAMPLE_SIZES)},
                "pastors": reports}
    return {**identity, "input_fingerprint": _canonical_hash(identity),
            "status": ("bounded_approval_ready" if all(item["contract_satisfied"] for item in reports)
                       else "contract_shortfall_review_required"),
            "analytical_credit_granted": False, "provider_requests": 0,
            "excluded_profile_ids": [318]}


def render_exact_cohort_proposal(report: Mapping[str, Any]) -> str:
    lines = ["# Salvation exact-cohort proposal", "",
             f"- Fingerprint: `{report['input_fingerprint']}`",
             f"- Status: `{report['status']}`",
             "- Analytical credit: none before bounded human approval",
             "- Provider requests: 0", "- Profile 318: outside this initial experiment", ""]
    lines += ["Contract per pastor: 12 independent sermons; two replicated periods",
              "with at least three sermons each; no documented series above six",
              "sermons; at least three distinct source titles outside the largest",
              "documented series. Unassigned series membership remains visible for",
              "bounded human integrity review.", "",
              "Matching titles nominate a check. Source-audio hashes and five-word transcript",
              "shingle overlap determine conservative equivalence groups; unresolved pairs",
              "contribute at most one proposed recording. Dates and series require source",
              "evidence or the reviewed baseline. Exact selection rules are in JSON.", ""]
    for pastor in report["pastors"]:
        gaps = ", ".join(f"{key}={pastor['shortfalls'][key]}" for key in pastor["contract_blockers"])
        lines += [f"## {pastor['display_name']} (profile {pastor['profile_id']})", "",
                  f"Proposed recordings: {len(pastor['included'])}/12. Contract gaps: {gaps or 'none'}.",
                  f"Unassigned provenance, for visibility: series={pastor['shortfalls']['missing_series_provenance']}; "
                  f"period={pastor['shortfalls']['missing_period_provenance']}. These are not contract blockers by themselves.",
                  f"Series diversity: largest documented series {pastor['largest_documented_series']['key'] or 'none'} "
                  f"has {pastor['largest_documented_series']['sermons']}/{len(pastor['included'])} sermons "
                  f"(limit {pastor['largest_documented_series']['maximum']}); "
                  f"{pastor['distinct_source_titles_outside_largest']} distinct source titles outside it "
                  f"(minimum {MIN_DISTINCT_OUTSIDE_TITLES}); "
                  f"{pastor['replicated_series_count']} documented replicated series for sensitivity analysis.", "",
                  "| Video | Baseline | Period / provenance | Series / provenance | Title |",
                  "| ---: | --- | --- | --- | --- |"]
        for item in pastor["included"]:
            title = str(item["title"]).replace("|", "\\|")
            period_source = (item["period_evidence"] or {}).get("source_kind", "unavailable")
            series_source = (item["series_evidence"] or {}).get("source_kind", "unavailable")
            lines.append(f"| {item['video_id']} | {'yes' if item['baseline'] else 'no'} | "
                         f"{item['period_key'] or '—'} / {period_source} | "
                         f"{item['series_key'] or '—'} / {series_source} | {title} |")
        lines += ["", "### Exclusions and equivalence", ""]
        for item in pastor["excluded"]:
            lines.append(f"- {item['video_id']}: {item['reason']}" +
                         (f"; representative {item['representative_video_id']}" if item['representative_video_id'] else ""))
        if not pastor["excluded"]:
            lines.append("- None.")
        for group in pastor["equivalence_groups"]:
            if len(group["video_ids"]) == 1:
                continue
            pairs = "; ".join(f"{pair['video_ids']}: {pair['decision']}, "
                              f"5-word containment {pair['shorter_transcript_containment']}"
                              for pair in group["pair_evidence"])
            lines.append(f"- Group {group['video_ids']}: {group['status']}; {pairs}.")
        lines += ["", "Artifact IDs, SHA-256 values, source paths, and pair evidence are in the JSON packet.", ""]
    discovery = report.get("bounded_discovery") or {}
    if discovery:
        lines += ["## Bounded already-ingested candidate check", "",
                  str(discovery.get("summary", "")), ""]
        for item in discovery.get("candidates", []):
            lines.append(f"- Video {item['video_id']}: {item['status']}; {item['reason']}.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_exact_cohort_proposal(path: Path, report: Mapping[str, Any]) -> tuple[Path, Path, bool]:
    path = path.expanduser().resolve()
    markdown = path.with_suffix(".md")
    rendered = render_exact_cohort_proposal(report)
    if path.is_file() and markdown.is_file():
        try:
            if (json.loads(path.read_text(encoding="utf-8")).get("input_fingerprint") == report["input_fingerprint"]
                    and markdown.read_text(encoding="utf-8") == rendered):
                return path, markdown, True
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown.write_text(rendered, encoding="utf-8")
    return path, markdown, False
