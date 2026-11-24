"""Registry-scale recall check for the identity text pre-filter (docs/PASTOR_FIT_EXPERIMENT.md section 13).

For every video whose speaker observation has an existing voice- or review-made profile
assignment, the observation's sermon-window text is ranked against every registry profile's
pooled text (that video's recordings left out of every profile), exactly as the opt-in
pre-filter ranks them. Measured per N: how often the assigned profile is kept (in the text top N,
or passed through because it has no usable text), and how many profile comparisons in the
cross-source voice pool text would have removed.

Circularity rule: only assignments that text played no part in count as truth. Any observation
with an association report that ran the text pre-filter is excluded, along with its text.
Free: reads `app.db` read-only and extraction JSON; no voice, model or provider call.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
from typing import Any, Callable, Iterable, Mapping

from .identity_text_prefilter import (
    MINIMUM_USABLE_WORDS,
    SCORER,
    TextStyleIndex,
    extraction_paths_by_observation,
    load_index,
)

EXPERIMENT = "identity-text-prefilter-v1"
DEFAULT_TOPS = (3, 5, 10)
ACCEPTANCE = {"top": 5, "minimum_kept_share": 0.95, "measure": "kept_share_assigned_profile_has_text",
              "rule": "Recommend default-on only if, among observations with usable text whose assigned profile "
                      "also has usable text, the assigned profile is in the text top 5 for at least 95%; "
                      "otherwise report the N that reaches 95%. Brian decides; this check changes no default."}
MAXIMUM_EXEMPLARS = 3  # shadow-associate-speakers --maximum-exemplars default
TEXT_MARKER = b'"text_prefilter"'


# ---------- labels ----------

def truth_labels(database) -> tuple[dict[int, set[int]], dict[int, set[str]]]:
    """Canonical profile(s) per observation from effective membership and active machine assignments."""
    from .speaker_machine_assignment import active_machine_assignment_evidence

    labels: dict[int, set[int]] = defaultdict(set)
    sources: dict[int, set[str]] = defaultdict(set)
    for _event, profile_id, observation_id, action, _reviewer, _reason in (
            database.list_effective_profile_observation_events()):
        if action == "attach":
            labels[observation_id].add(database.resolve_speaker_profile_id(profile_id))
            sources[observation_id].add("registry_membership")
    for evidence in active_machine_assignment_evidence(database):
        observation_id = int(evidence["observation_id"])
        labels[observation_id].add(database.resolve_speaker_profile_id(int(evidence["profile_id"])))
        sources[observation_id].add("machine_assignment")
    return dict(labels), dict(sources)


def text_assisted_observations(observation_fingerprints: Mapping[int, str], association_root: Path,
                               extra_artifacts: Mapping[int, Iterable[str]] = {}) -> set[int]:
    """Observations with any association report produced with the text pre-filter."""
    flagged = set()
    for observation_id, fingerprint in observation_fingerprints.items():
        paths = list((association_root / fingerprint[:16]).glob("*.json")) if fingerprint else []
        paths += [Path(p) for p in extra_artifacts.get(observation_id, ())]
        for path in paths:
            try:
                if TEXT_MARKER in path.read_bytes():
                    flagged.add(observation_id)
                    break
            except OSError:
                continue
    return flagged


def select_queries(labels: Mapping[int, set[int]], video_by_observation: Mapping[int, int],
                   excluded: set[int]) -> tuple[dict[int, int], Counter]:
    """One query per video (its latest labeled observation) with a single canonical label."""
    by_video: dict[int, list[int]] = defaultdict(list)
    counts: Counter = Counter()
    for observation_id in labels:
        if observation_id in excluded:
            counts["excluded_text_assisted"] += 1
            continue
        video_id = video_by_observation.get(observation_id)
        if video_id is None:
            counts["labeled_observation_missing"] += 1
            continue
        by_video[video_id].append(observation_id)
    queries = {}
    for video_id, observations in by_video.items():
        profiles = set().union(*(labels[o] for o in observations))
        if len(profiles) != 1:
            counts["videos_with_conflicting_labels"] += 1
            continue
        queries[max(observations)] = next(iter(profiles))
    return queries, counts


# ---------- measurement (pure) ----------

def measure(index: TextStyleIndex, queries: Mapping[int, int], tops: Iterable[int]) -> dict[str, Any]:
    """Rank each query against all labeled profiles; summarize kept share and pruning per N."""
    tops = sorted(set(tops) | {ACCEPTANCE["top"]})
    members: dict[int, list[int]] = defaultdict(list)
    for observation_id, profile_id in queries.items():
        members[profile_id].append(observation_id)
    rows = []
    for observation_id, true_profile in sorted(queries.items()):
        ranking = index.rank(observation_id, members)
        row: dict[str, Any] = {"observation_id": observation_id, "profile_id": true_profile,
                               "query_has_text": ranking.query_has_text,
                               "pool": len(ranking.ranked) + len(ranking.pass_through_profile_ids),
                               "ranked": len(ranking.ranked),
                               "other_recordings": len(members[true_profile]) - 1}
        if ranking.query_has_text:
            distances = dict(ranking.ranked)
            if true_profile in distances:
                true_distance = distances[true_profile]
                others = [d for p, d in ranking.ranked if p != true_profile]
                row["better"] = sum(d < true_distance for d in others)
                row["ties"] = sum(d == true_distance for d in others)
            else:
                row["assigned_profile_passes_through"] = True
            order = [p for p, _ in ranking.ranked]
            row["pruned_exemplars_by_top"] = {
                str(n): sum(min(MAXIMUM_EXEMPLARS, len(members[p])) for p in order[n:]) for n in tops}
        rows.append(row)
    return {"rows": rows, "summary": summarize(rows, tops)}


def kept_credit(row: Mapping[str, Any], top: int) -> float:
    if row.get("assigned_profile_passes_through"):
        return 1.0
    return max(0.0, min(1.0, (top - row["better"]) / (row["ties"] + 1)))


def summarize(rows: list[dict], tops: Iterable[int]) -> dict[str, Any]:
    usable = [r for r in rows if r["query_has_text"]]
    ranked_cases = [r for r in usable if not r.get("assigned_profile_passes_through")]
    per_top = {}
    for n in tops:
        pool = sum(r["pool"] for r in usable)
        pruned = sum(max(0, r["ranked"] - n) for r in usable)
        per_top[str(n)] = {
            "kept_share": _share(sum(kept_credit(r, n) for r in usable), len(usable)),
            "kept_share_assigned_profile_has_text": _share(sum(kept_credit(r, n) for r in ranked_cases),
                                                           len(ranked_cases)),
            "pool_profile_comparisons": pool,
            "pruned_profile_comparisons": pruned,
            "pruned_share": _share(pruned, pool),
            "mean_profiles_kept_per_observation": _share(pool - pruned, len(usable)),
            "pruned_exemplar_centroids_estimate": sum(r["pruned_exemplars_by_top"][str(n)] for r in usable),
        }
    maximum = max((r["ranked"] for r in ranked_cases), default=0)
    reach = next((n for n in range(1, maximum + 1)
                  if _share(sum(kept_credit(r, n) for r in ranked_cases), len(ranked_cases))
                  >= ACCEPTANCE["minimum_kept_share"]), None)
    by_size = {}
    for label, low, high in (("1 other recording", 1, 1), ("2-3 other recordings", 2, 3),
                             ("4+ other recordings", 4, 10 ** 9)):
        group = [r for r in usable if low <= r["other_recordings"] <= high]
        by_size[label] = {"n": len(group), "kept_share_top5": _share(sum(kept_credit(r, 5) for r in group), len(group))}
    acceptance_top = str(ACCEPTANCE["top"])
    accepted = None
    if acceptance_top in per_top and ranked_cases:
        accepted = per_top[acceptance_top][ACCEPTANCE["measure"]] >= ACCEPTANCE["minimum_kept_share"]
    return {
        "observations": len(rows),
        "observations_with_usable_text": len(usable),
        "observations_without_usable_text": len(rows) - len(usable),
        "assigned_profile_passes_through": len(usable) - len(ranked_cases),
        "median_expected_rank": (statistics.median(1 + r["better"] + r["ties"] / 2 for r in ranked_cases)
                                 if ranked_cases else None),
        "per_top": per_top,
        "smallest_top_reaching_95_percent": reach,
        "by_assigned_profile_size": by_size,
        "meets_default_on_bar": accepted,
    }


def _share(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


# ---------- run and report ----------

def output_dir(base_dir: Path | None) -> Path:
    from .bound_claims.common import ensure_outside_repository
    from .config import build_paths, evaluation_root_for
    return ensure_outside_repository(evaluation_root_for(build_paths(base_dir), base_dir) / EXPERIMENT)


def run(base_dir: Path | None, tops: Iterable[int] = DEFAULT_TOPS, association_root: Path | None = None,
        echo: Callable[[str], None] = print) -> dict[str, Any]:
    from .config import build_paths
    from .storage import Database

    paths = build_paths(base_dir)
    out = output_dir(base_dir)
    association_root = (association_root or paths.evaluation / "speaker-associations/shadow-runs").expanduser().resolve()
    database = Database(paths.database, readonly=True)
    labels, label_sources = truth_labels(database)
    observations = {o.id: o for o in database.list_speaker_observations()}
    machine_artifacts: dict[int, list[str]] = defaultdict(list)
    for evidence in database.list_speaker_machine_evidence():
        machine_artifacts[int(evidence["observation_id"])].append(str(evidence["association_artifact_path"]))
    echo(f"Labeled observations: {len(labels)}; checking association reports for text pre-filter use.")
    excluded = text_assisted_observations(
        {o: observations[o].input_fingerprint for o in labels if o in observations},
        association_root, machine_artifacts)
    extraction_paths, video_by_observation = extraction_paths_by_observation(database)
    queries, selection_counts = select_queries(labels, video_by_observation, excluded)
    echo(f"Loading sermon-window text for {len(queries)} videos (cached after the first run).")
    index = load_index(extraction_paths, video_by_observation, queries,
                       paths.evaluation / "speaker-pairs/cache/text-prefilter-v1")
    result = measure(index, queries, tops)
    sources = Counter(source for o in queries for source in label_sources.get(o, ()))
    report = {
        "experiment": EXPERIMENT,
        "spec": "docs/PASTOR_FIT_EXPERIMENT.md section 13",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scorer": dict(SCORER),
        "acceptance": ACCEPTANCE,
        "circularity": {
            "rule": "Only assignments text played no part in are truth. Observations with any association "
                    "report that ran the text pre-filter are excluded as queries and as profile text.",
            "text_assisted_observations_excluded": len(excluded),
        },
        "population": {
            "registry_profiles_with_labeled_recordings": len(set(queries.values())),
            "labeled_observations": len(labels),
            "queried_videos": len(queries),
            "label_sources": dict(sources),
            **dict(selection_counts),
            "minimum_usable_words": MINIMUM_USABLE_WORDS,
        },
        "summary": result["summary"],
        "rows": result["rows"],
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "REPORT.md").write_text(markdown(report), encoding="utf-8")
    echo(f"Wrote {out / 'REPORT.md'} and report.json")
    return {"output_dir": str(out), "summary": report["summary"], "population": report["population"],
            "circularity": report["circularity"]}


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def markdown(report: Mapping[str, Any]) -> str:
    s, pop = report["summary"], report["population"]
    acceptance_top = str(ACCEPTANCE["top"])
    verdict = s["meets_default_on_bar"]
    lines = [
        f"# Identity text pre-filter check ({EXPERIMENT})", "",
        "Spec: `docs/PASTOR_FIT_EXPERIMENT.md` section 13. Free: no voice, model or provider call. "
        f"Scorer `{report['scorer']['version']}`: Burrows' Delta on the {report['scorer']['style_words']} most "
        "frequent words of sermon-window text (rolling captions normalized).", "",
        "## Verdict", "",
        f"- Assigned profile in the text top {acceptance_top}: "
        f"**{_pct(s['per_top'].get(acceptance_top, {}).get(ACCEPTANCE['measure']))}** of "
        f"{s['observations_with_usable_text'] - s['assigned_profile_passes_through']} observations where both the "
        f"observation and its assigned profile have usable text (bar: {_pct(ACCEPTANCE['minimum_kept_share'])}). "
        f"Counting pass-through profiles as kept: {_pct(s['per_top'].get(acceptance_top, {}).get('kept_share'))} of "
        f"{s['observations_with_usable_text']}.",
        f"- {'Meets' if verdict else 'Does not meet'} the bar for recommending the pre-filter on by default. "
        "Brian decides; this check changes nothing.",
        f"- Smallest N reaching 95%: {s['smallest_top_reaching_95_percent'] or 'not reached'}.", "",
        "## Per N", "",
        "| N | in top N (assigned profile has text) | kept, incl. pass-through | profile comparisons pruned | share pruned "
        "| profiles kept per observation | exemplar centroids avoided (est.) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for n, row in sorted(s["per_top"].items(), key=lambda item: int(item[0])):
        lines.append(f"| {n} | {_pct(row['kept_share_assigned_profile_has_text'])} | {_pct(row['kept_share'])} "
                     f"| {row['pruned_profile_comparisons']:,} of {row['pool_profile_comparisons']:,} "
                     f"| {_pct(row['pruned_share'])} | {row['mean_profiles_kept_per_observation'] or 0:.1f} "
                     f"| {row['pruned_exemplar_centroids_estimate']:,} |")
    lines += ["", "## By size of the assigned profile (N = 5)", "", "| other recordings | observations | kept |",
              "| --- | --- | --- |"]
    for label, row in s["by_assigned_profile_size"].items():
        lines.append(f"| {label} | {row['n']} | {_pct(row['kept_share_top5'])} |")
    median = s["median_expected_rank"]
    lines += [
        "", "## Population", "",
        f"- Registry profiles with labeled recordings: {pop['registry_profiles_with_labeled_recordings']}",
        f"- Labeled observations: {pop['labeled_observations']}; queried videos (one per video): {pop['queried_videos']}",
        f"- Label sources: {', '.join(f'{k} {v}' for k, v in sorted(pop['label_sources'].items())) or 'none'}",
        f"- Videos skipped for conflicting labels: {pop.get('videos_with_conflicting_labels', 0)}",
        f"- Observations without usable text (under {pop['minimum_usable_words']} words or no sermon window): "
        f"{s['observations_without_usable_text']}; these prune nothing",
        f"- Assigned profile without usable text (passes through, counted as kept): {s['assigned_profile_passes_through']}",
        f"- Median expected rank of the assigned profile: {'n/a' if median is None else f'{median:.1f}'}", "",
        "## Circularity", "",
        report["circularity"]["rule"],
        f"Excluded now: {report['circularity']['text_assisted_observations_excluded']}.", "",
        "## Reading", "",
        "- \"Kept\" means the assigned profile would still reach voice comparison: it is in the text top N, or it has "
        "no usable text and passes through. Ties earn expected credit.",
        "- Pruning applies only to the cross-source pool, which shadow association uses when a candidate has no "
        "source, name or confirmation route, or after a weak local result. Pairwise policy comparisons (up to "
        f"{MAXIMUM_EXEMPLARS} per compared profile) are unchanged; text removes exemplar preparation and retrieval "
        "centroids for pruned profiles.",
        "- The pool here is every registry profile with labeled recordings; the production pool is the subset "
        "that is shadow-ready, so production pruning is somewhat smaller.",
        "- Each profile's text leaves out the queried video, so a sermon never matches itself.", "",
    ]
    return "\n".join(lines)
