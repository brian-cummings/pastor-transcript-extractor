from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
import statistics
from typing import Mapping

from pastor_transcript_extractor.comparison_features import (
    BENCHMARK_FEATURE_SCHEMA_VERSION,
    CANONICAL_COMPOSITION_FEATURE_NAMES,
    COMPARISON_FEATURE_NAMES,
    CORE_FEATURE_NAMES,
    DEPTH_SENSITIVE_FEATURE_NAMES,
    DIAGNOSTIC_ONLY_FEATURE_NAMES,
    FEATURE_ROLE_ASSIGNMENTS,
    canonical_division_clr,
)
from pastor_transcript_extractor.models import (
    BenchmarkComparisonRun,
    ReferencePanel,
    ReferencePanelMembershipEvent,
    ReferencePanelSnapshot,
    ReferencePanelSnapshotMember,
)
from pastor_transcript_extractor.profile_analysis import (
    PROFILE_ANALYZER_KEY,
    PROFILE_ANALYZER_VERSION,
    PROFILE_FEATURE_ORDER,
    get_current_profile_scripture_run,
)
from pastor_transcript_extractor.storage import Database


SNAPSHOT_ANALYZER_VERSION = "reference-panel-snapshot@4"
FEATURE_SCHEMA_VERSION = BENCHMARK_FEATURE_SCHEMA_VERSION
ELIGIBILITY_POLICY_VERSION = "scripture-reference-eligibility@2"
COMPARISON_ANALYZER_VERSION = "scripture-reference-comparison@2"
NORMALIZATION_POLICY_VERSION = "robust-panel-common-mask@2"
MAD_CONSISTENCY_FACTOR = 1.4826
MAX_STANDARDIZED_DIFFERENCE = 5.0

# Corpus sufficiency and analysis completeness explain whether a vector is usable;
# they are deliberately not dimensions in similarity space.
COVERAGE_FEATURE_NAMES = (
    "sermons_attached",
    "sermons_analyzed",
    "sermons_missing_analysis",
    "total_sermon_words",
    "analysis_coverage_fraction",
    "structural_coverage_diagnostics",
)
REQUIRED_COMPARISON_FEATURE_NAMES = (
    *CORE_FEATURE_NAMES,
    *CANONICAL_COMPOSITION_FEATURE_NAMES,
)
UNSUPPORTED_FEATURE_FAMILIES = (
    "semantic-style-run-coverage",
    "theology",
    "politics",
    "christian-nationalism",
    "embeddings",
)
FEATURE_FAMILY_ASSIGNMENTS = {
    **FEATURE_ROLE_ASSIGNMENTS,
    "comparison_eligible": list(COMPARISON_FEATURE_NAMES),
    "diagnostic_only": sorted(
        set(COVERAGE_FEATURE_NAMES) | set(DIAGNOSTIC_ONLY_FEATURE_NAMES)
    ),
    "excluded": list(UNSUPPORTED_FEATURE_FAMILIES),
}

_PANEL_KEY = re.compile(r"^[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class EligibilityPolicy:
    version: str = ELIGIBILITY_POLICY_VERSION
    minimum_analyzed_sermons: int = 5
    minimum_total_sermon_words: int = 10_000
    minimum_analysis_coverage: float = 0.8
    required_comparison_feature_names: tuple[str, ...] = REQUIRED_COMPARISON_FEATURE_NAMES

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("Eligibility policy version must not be blank")
        if self.minimum_analyzed_sermons < 0 or self.minimum_total_sermon_words < 0:
            raise ValueError("Eligibility minimums must not be negative")
        if not 0.0 <= self.minimum_analysis_coverage <= 1.0:
            raise ValueError("Minimum analysis coverage must be between 0 and 1")
        unknown = set(self.required_comparison_feature_names) - set(
            COMPARISON_FEATURE_NAMES
        )
        if unknown:
            raise ValueError(
                f"Unknown required comparison features: {', '.join(sorted(unknown))}"
            )

    def payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "minimum_analyzed_sermons": self.minimum_analyzed_sermons,
            "minimum_total_sermon_words": self.minimum_total_sermon_words,
            "minimum_analysis_coverage": self.minimum_analysis_coverage,
            "required_comparison_feature_names": list(
                self.required_comparison_feature_names
            ),
            "unsupported_feature_families": list(UNSUPPORTED_FEATURE_FAMILIES),
        }


@dataclass(frozen=True, slots=True)
class MembershipOutcome:
    event: ReferencePanelMembershipEvent
    created: bool


@dataclass(frozen=True, slots=True)
class SnapshotOutcome:
    snapshot: ReferencePanelSnapshot
    created: bool


@dataclass(frozen=True, slots=True)
class ComparisonOutcome:
    run: BenchmarkComparisonRun
    created: bool
    result: dict[str, object]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def create_panel(
    database: Database,
    *,
    key: str,
    name: str,
    description: str,
    provenance: str = "manual-review",
) -> tuple[ReferencePanel, bool]:
    key = key.strip()
    name = name.strip()
    description = description.strip()
    provenance = provenance.strip()
    if not _PANEL_KEY.fullmatch(key):
        raise ValueError(
            "Reference panel key must contain lowercase letters, digits, and internal hyphens"
        )
    if not name or not description or not provenance:
        raise ValueError("Panel name, description, and provenance must not be blank")
    return database.ensure_reference_panel(
        key=key,
        display_name=name,
        description=description,
        provenance=provenance,
    )


def record_membership(
    database: Database,
    *,
    panel_key: str,
    profile_id: int,
    action: str,
    reviewer: str,
    rationale: str,
) -> MembershipOutcome:
    panel = database.get_reference_panel(panel_key)
    if panel is None:
        raise ValueError(f"Unknown reference panel: {panel_key}")
    if database.get_speaker_profile(profile_id) is None:
        raise ValueError(f"Unknown speaker profile: {profile_id}")
    reviewer = reviewer.strip()
    rationale = rationale.strip()
    if not reviewer or not rationale:
        raise ValueError("Reviewer and rationale must not be blank")
    fingerprint = _fingerprint(
        {
            "action": action,
            "panel_id": panel.id,
            "profile_id": profile_id,
            "rationale": rationale,
            "reviewer": reviewer,
            "schema_version": 1,
        }
    )
    event, created = database.add_reference_panel_membership_event(
        panel_id=panel.id,
        profile_id=profile_id,
        action=action,
        reviewer=reviewer,
        rationale=rationale,
        event_fingerprint=fingerprint,
    )
    return MembershipOutcome(event=event, created=created)


def effective_membership(database: Database, panel: ReferencePanel) -> list[dict[str, object]]:
    grouped: dict[int, list[ReferencePanelMembershipEvent]] = {}
    for event in database.list_effective_reference_panel_membership_events(panel.id):
        requested_id = event.profile_id
        resolved_id = database.resolve_speaker_profile_id(requested_id)
        grouped.setdefault(resolved_id, []).append(event)
    return [
        {
            "requested_profile_ids": sorted(event.profile_id for event in events),
            "membership_event_ids": sorted(event.id for event in events),
            "membership_reviews": [
                {
                    "event_id": event.id,
                    "profile_id": event.profile_id,
                    "reviewer": event.reviewer,
                    "rationale": event.rationale,
                    "created_at": event.created_at.isoformat(),
                }
                for event in sorted(events, key=lambda item: item.profile_id)
            ],
            "resolved_profile_id": resolved_id,
            "resolved_display_label": (
                profile.display_label or profile.stable_key
                if (profile := database.get_speaker_profile(resolved_id)) is not None
                else f"profile-{resolved_id}"
            ),
        }
        for resolved_id, events in sorted(grouped.items())
    ]


def _measurements(database: Database, run_id: int) -> dict[str, object]:
    return {
        item.metric_key: json.loads(item.value_json)
        for item in database.list_speaker_profile_analysis_measurements(run_id)
    }


def _number(value: object) -> float | int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def _member_payload(
    database: Database,
    membership: Mapping[str, object],
    policy: EligibilityPolicy,
) -> dict[str, object]:
    resolved_id = int(membership["resolved_profile_id"])
    requested_ids = list(membership["requested_profile_ids"])  # type: ignore[arg-type]
    membership_event_ids = list(membership["membership_event_ids"])  # type: ignore[arg-type]
    resolved_display_label = str(membership["resolved_display_label"])
    run = get_current_profile_scripture_run(database, resolved_id)
    comparison = {name: None for name in COMPARISON_FEATURE_NAMES}
    diagnostics: dict[str, object] = {
        "sermons_attached": None,
        "sermons_analyzed": None,
        "sermons_missing_analysis": None,
        "total_sermon_words": None,
        "analysis_coverage_fraction": None,
        "structural_coverage_diagnostics": None,
    }
    reasons: list[str] = []
    if run is None:
        latest = database.get_compatible_speaker_profile_analysis_run(
            resolved_id, PROFILE_ANALYZER_KEY, PROFILE_ANALYZER_VERSION
        )
        reasons.append("stale_analysis" if latest else "missing_analysis")
    else:
        values = _measurements(database, run.id)
        vector = values.get("deterministic_profile_feature_vector")
        by_name: Mapping[str, object] = {}
        if (
            isinstance(vector, dict)
            and vector.get("schema_version") == 2
            and vector.get("feature_names") == list(PROFILE_FEATURE_ORDER)
            and isinstance(vector.get("values"), list)
            and len(vector["values"]) == len(PROFILE_FEATURE_ORDER)
            and isinstance(vector.get("by_name"), dict)
        ):
            by_name = dict(zip(PROFILE_FEATURE_ORDER, vector["values"], strict=True))
        else:
            reasons.append("incompatible_feature_schema")
        composition = canonical_division_clr(
            values.get("canonical_division_emphasis", {})
            if isinstance(values.get("canonical_division_emphasis"), dict)
            else {}
        )
        comparison = {
            name: (
                composition.get(name)
                if composition is not None and name in CANONICAL_COMPOSITION_FEATURE_NAMES
                else _number(by_name.get(name))
            )
            for name in COMPARISON_FEATURE_NAMES
        }
        diagnostics = {
            "sermons_attached": _number(values.get("sermons_attached")),
            "sermons_analyzed": _number(values.get("sermons_analyzed")),
            "sermons_missing_analysis": _number(values.get("sermons_missing_analysis")),
            "total_sermon_words": _number(values.get("total_sermon_words")),
            "analysis_coverage_fraction": _number(by_name.get("analysis_coverage_fraction")),
            "structural_coverage_diagnostics": values.get(
                "structural_coverage_diagnostics"
            ),
        }
        analyzed = diagnostics["sermons_analyzed"]
        words = diagnostics["total_sermon_words"]
        coverage = diagnostics["analysis_coverage_fraction"]
        if analyzed is None or analyzed < policy.minimum_analyzed_sermons:
            reasons.append("insufficient_analyzed_sermons")
        if words is None or words < policy.minimum_total_sermon_words:
            reasons.append("insufficient_total_sermon_words")
        if coverage is None or coverage < policy.minimum_analysis_coverage:
            reasons.append("insufficient_analysis_coverage")
        missing = [name for name, value in comparison.items() if value is None]
        missing_required = [
            name for name in policy.required_comparison_feature_names
            if comparison.get(name) is None
        ]
        diagnostics["missing_comparison_features"] = missing
        diagnostics["missing_required_comparison_features"] = missing_required
        diagnostics["reviewed_feature_depth_support"] = {
            "core": bool(analyzed is not None and analyzed >= 5),
            "canonical_composition": bool(analyzed is not None and analyzed >= 5),
            "depth_sensitive": bool(analyzed is not None and analyzed >= 8),
        }
        if missing_required:
            reasons.append("missing_required_comparison_features")
    return {
        "requested_profile_ids": requested_ids,
        "membership_event_ids": membership_event_ids,
        "resolved_profile_id": resolved_id,
        "resolved_display_label": resolved_display_label,
        "profile_analysis_run_id": run.id if run is not None else None,
        "eligibility_status": "eligible" if not reasons else "ineligible",
        "exclusion_reasons": reasons,
        "comparison_values": comparison,
        "coverage_diagnostics": diagnostics,
    }


def _panel_feature_statistics(
    member_payloads: list[dict[str, object]],
) -> dict[str, object]:
    eligible = [
        member
        for member in member_payloads
        if member["eligibility_status"] == "eligible"
    ]
    by_feature: dict[str, dict[str, float | int | None]] = {}
    for name in COMPARISON_FEATURE_NAMES:
        values = [
            value
            for member in eligible
            if (
                value := member["comparison_values"][name]  # type: ignore[index]
            )
            is not None
            and (
                name not in DEPTH_SENSITIVE_FEATURE_NAMES
                or member["coverage_diagnostics"]
                .get("reviewed_feature_depth_support", {})  # type: ignore[union-attr]
                .get("depth_sensitive", False)
            )
        ]
        if values:
            center = statistics.median(values)
            mad = statistics.median(abs(value - center) for value in values)
            minimum: float | int | None = min(values)
            maximum: float | int | None = max(values)
        else:
            center = mad = minimum = maximum = None
        by_feature[name] = {
            "eligible_count": len(values),
            "missing_count": len(eligible) - len(values),
            "median": center,
            "median_absolute_deviation": mad,
            "minimum": minimum,
            "maximum": maximum,
        }
    return {
        "version": "reference-panel-feature-statistics@1",
        "eligible_member_count": len(eligible),
        "features": by_feature,
    }


def build_snapshot(
    database: Database,
    panel_key: str,
    *,
    policy: EligibilityPolicy | None = None,
    snapshot_analyzer_version: str = SNAPSHOT_ANALYZER_VERSION,
) -> SnapshotOutcome:
    panel = database.get_reference_panel(panel_key)
    if panel is None:
        raise ValueError(f"Unknown reference panel: {panel_key}")
    policy = policy or EligibilityPolicy()
    if not snapshot_analyzer_version.strip():
        raise ValueError("Snapshot analyzer version must not be blank")
    member_payloads = [
        _member_payload(database, membership, policy)
        for membership in effective_membership(database, panel)
    ]
    panel_statistics = _panel_feature_statistics(member_payloads)
    fingerprint_payload = {
        "panel": {
            "id": panel.id,
            "key": panel.key,
            "name": panel.display_name,
            "description": panel.description,
            "provenance": panel.provenance,
        },
        "members": [
            {
                "requested_profile_ids": item["requested_profile_ids"],
                "membership_event_ids": item["membership_event_ids"],
                "resolved_profile_id": item["resolved_profile_id"],
                "resolved_display_label": item["resolved_display_label"],
                "profile_analysis_run_id": item["profile_analysis_run_id"],
                "eligibility_status": item["eligibility_status"],
                "exclusion_reasons": item["exclusion_reasons"],
            }
            for item in member_payloads
        ],
        "profile_analyzer_key": PROFILE_ANALYZER_KEY,
        "profile_analyzer_version": PROFILE_ANALYZER_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "comparison_feature_names": list(COMPARISON_FEATURE_NAMES),
        "coverage_feature_names": list(COVERAGE_FEATURE_NAMES),
        "feature_family_assignments": FEATURE_FAMILY_ASSIGNMENTS,
        "panel_feature_statistics": panel_statistics,
        "eligibility_policy": policy.payload(),
        "snapshot_analyzer_version": snapshot_analyzer_version,
    }
    fingerprint = _fingerprint(fingerprint_payload)
    members = [
        (
            _json(item["requested_profile_ids"]),
            _json(item["membership_event_ids"]),
            int(item["resolved_profile_id"]),
            str(item["resolved_display_label"]),
            item["profile_analysis_run_id"],
            str(item["eligibility_status"]),
            _json(item["exclusion_reasons"]),
            _json(item["comparison_values"]),
            _json(item["coverage_diagnostics"]),
        )
        for item in member_payloads
    ]
    snapshot, created = database.add_reference_panel_snapshot(
        panel_id=panel.id,
        profile_analyzer_key=PROFILE_ANALYZER_KEY,
        profile_analyzer_version=PROFILE_ANALYZER_VERSION,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        comparison_feature_names_json=_json(list(COMPARISON_FEATURE_NAMES)),
        coverage_feature_names_json=_json(list(COVERAGE_FEATURE_NAMES)),
        feature_family_assignments_json=_json(FEATURE_FAMILY_ASSIGNMENTS),
        panel_feature_statistics_json=_json(panel_statistics),
        eligibility_policy_version=policy.version,
        eligibility_policy_json=_json(policy.payload()),
        snapshot_analyzer_version=snapshot_analyzer_version,
        input_fingerprint=fingerprint,
        members=members,
    )
    return SnapshotOutcome(snapshot=snapshot, created=created)


def snapshot_document(
    database: Database,
    panel: ReferencePanel,
    snapshot: ReferencePanelSnapshot,
) -> dict[str, object]:
    comparison_names = json.loads(snapshot.comparison_feature_names_json)
    members = database.list_reference_panel_snapshot_members(snapshot.id)
    decoded = [_decode_member(member) for member in members]
    return {
        "panel": {
            "key": panel.key,
            "name": panel.display_name,
            "description": panel.description,
            "provenance": panel.provenance,
        },
        "snapshot": {
            "id": snapshot.id,
            "fingerprint": snapshot.input_fingerprint,
            "snapshot_analyzer_version": snapshot.snapshot_analyzer_version,
            "profile_analyzer": (
                f"{snapshot.profile_analyzer_key}@{snapshot.profile_analyzer_version}"
            ),
            "feature_schema_version": snapshot.feature_schema_version,
            "comparison_feature_names": comparison_names,
            "coverage_feature_names": json.loads(snapshot.coverage_feature_names_json),
            "feature_family_assignments": json.loads(
                snapshot.feature_family_assignments_json
            ),
            "panel_feature_statistics": json.loads(
                snapshot.panel_feature_statistics_json
            ),
            "eligibility_policy_version": snapshot.eligibility_policy_version,
            "eligibility_policy": json.loads(snapshot.eligibility_policy_json),
            "created_at": snapshot.created_at.isoformat(),
        },
        "members": decoded,
        "feature_matrix": {
            "feature_names": comparison_names,
            "rows": [
                {
                    "profile_id": member["resolved_profile_id"],
                    "display_label": member["resolved_display_label"],
                    "profile_analysis_run_id": member["profile_analysis_run_id"],
                    "values": [
                        member["comparison_values"][name] for name in comparison_names
                    ],
                    "missing": [
                        member["comparison_values"][name] is None
                        for name in comparison_names
                    ],
                    "coverage": member["coverage_diagnostics"],
                }
                for member in decoded
                if member["eligibility_status"] == "eligible"
            ],
        },
    }


def _decode_member(member: ReferencePanelSnapshotMember) -> dict[str, object]:
    return {
        "requested_profile_ids": json.loads(member.requested_profile_ids_json),
        "membership_event_ids": json.loads(member.membership_event_ids_json),
        "resolved_profile_id": member.resolved_profile_id,
        "resolved_display_label": member.resolved_display_label,
        "profile_analysis_run_id": member.profile_analysis_run_id,
        "eligibility_status": member.eligibility_status,
        "exclusion_reasons": json.loads(member.exclusion_reasons_json),
        "comparison_values": json.loads(member.comparison_values_json),
        "coverage_diagnostics": json.loads(member.coverage_diagnostics_json),
    }


def _policy_from_snapshot(snapshot: ReferencePanelSnapshot) -> EligibilityPolicy:
    payload = json.loads(snapshot.eligibility_policy_json)
    required = payload.get("required_comparison_feature_names")
    return EligibilityPolicy(
        version=str(payload["version"]),
        minimum_analyzed_sermons=int(payload["minimum_analyzed_sermons"]),
        minimum_total_sermon_words=int(payload["minimum_total_sermon_words"]),
        minimum_analysis_coverage=float(payload["minimum_analysis_coverage"]),
        required_comparison_feature_names=(
            tuple(str(name) for name in required)
            if isinstance(required, list)
            else REQUIRED_COMPARISON_FEATURE_NAMES
        ),
    )


def _candidate_payload(
    database: Database,
    *,
    requested_profile_id: int,
    policy: EligibilityPolicy,
) -> dict[str, object]:
    if database.get_speaker_profile(requested_profile_id) is None:
        raise ValueError(f"Unknown speaker profile: {requested_profile_id}")
    resolved_id = database.resolve_speaker_profile_id(requested_profile_id)
    profile = database.get_speaker_profile(resolved_id)
    assert profile is not None
    return _member_payload(
        database,
        {
            "requested_profile_ids": [requested_profile_id],
            "membership_event_ids": [],
            "resolved_profile_id": resolved_id,
            "resolved_display_label": profile.display_label or profile.stable_key,
        },
        policy,
    )


def _feature_scale(statistics_payload: Mapping[str, object]) -> tuple[float, str] | None:
    mad = _number(statistics_payload.get("median_absolute_deviation"))
    if mad is not None and mad > 0:
        return float(mad) * MAD_CONSISTENCY_FACTOR, "scaled_mad"
    minimum = _number(statistics_payload.get("minimum"))
    maximum = _number(statistics_payload.get("maximum"))
    if minimum is not None and maximum is not None and maximum > minimum:
        return float(maximum - minimum), "observed_range_fallback"
    return None


def _comparison_families(level: str) -> dict[str, tuple[str, ...]]:
    families = {
        "core": tuple(CORE_FEATURE_NAMES),
        "canonical_composition": tuple(CANONICAL_COMPOSITION_FEATURE_NAMES),
    }
    if level == "full":
        families["depth_sensitive"] = tuple(DEPTH_SENSITIVE_FEATURE_NAMES)
    return families


def _common_feature_mask(candidate, references, families, panel_statistics):
    """Freeze one geometry; missing/constant coordinates never disappear per pair."""
    selected = {}
    omissions = []
    reasons = []
    statistics_by_feature = panel_statistics.get("features", {})
    for family, names in families.items():
        supported = []
        for name in names:
            values = [_number(item["comparison_values"].get(name)) for item in [candidate, *references]]
            stats = statistics_by_feature.get(name)
            scale = _feature_scale(stats) if isinstance(stats, Mapping) else None
            reason = None
            if any(value is None for value in values):
                reason = "missing_in_common_comparison_set"
            elif scale is None:
                reason = "constant_or_unscalable_calibration_coordinate"
                if any(value != values[0] for value in values[1:]):
                    reasons.append("out_of_panel_unscalable_difference")
            if reason:
                omissions.append({"feature": name, "family": family, "reason": reason,
                                  "candidate_value": values[0],
                                  "reference_values": [
                                      {"profile_id": reference["resolved_profile_id"], "value": value,
                                       "raw_difference": values[0] - value if values[0] is not None and value is not None else None}
                                      for reference, value in zip(references, values[1:], strict=True)
                                  ]})
            else:
                supported.append(name)
        if supported:
            selected[family] = tuple(supported)
    if not selected:
        reasons.append("no_common_supported_features")
    return selected, omissions, reasons


def _rank_reference(
    candidate: Mapping[str, object],
    reference: Mapping[str, object],
    *,
    families: Mapping[str, tuple[str, ...]],
    panel_statistics: Mapping[str, object],
) -> dict[str, object] | None:
    candidate_values = candidate["comparison_values"]
    reference_values = reference["comparison_values"]
    feature_statistics = panel_statistics.get("features", {})
    assert isinstance(candidate_values, Mapping)
    assert isinstance(reference_values, Mapping)
    assert isinstance(feature_statistics, Mapping)
    family_rows: list[dict[str, object]] = []
    all_features: list[dict[str, object]] = []
    unavailable_families: list[str] = []
    for family_name, feature_names in families.items():
        feature_rows: list[dict[str, object]] = []
        for name in feature_names:
            left = _number(candidate_values.get(name))
            right = _number(reference_values.get(name))
            stats = feature_statistics.get(name)
            scale = _feature_scale(stats) if isinstance(stats, Mapping) else None
            if left is None or right is None:
                return None
            if scale is None:
                if left != right:
                    return None
                continue
            scale_value, scale_method = scale
            raw_difference = float(left - right)
            uncapped = abs(raw_difference) / scale_value
            row = {
                "feature": name,
                "family": family_name,
                "candidate_value": left,
                "reference_value": right,
                "raw_difference": round(raw_difference, 6),
                "normalization_scale": round(scale_value, 6),
                "normalization_method": scale_method,
                "standardized_absolute_difference": round(
                    min(uncapped, MAX_STANDARDIZED_DIFFERENCE), 6
                ),
                "standardized_difference_was_capped": uncapped
                > MAX_STANDARDIZED_DIFFERENCE,
            }
            feature_rows.append(row)
            all_features.append(row)
        if not feature_rows:
            unavailable_families.append(family_name)
            continue
        family_distance = math.sqrt(
            statistics.fmean(
                float(row["standardized_absolute_difference"]) ** 2
                for row in feature_rows
            )
        )
        family_rows.append(
            {
                "family": family_name,
                "distance": round(family_distance, 6),
                "feature_count": len(feature_rows),
            }
        )
    if not family_rows:
        return None
    overall = math.sqrt(
        statistics.fmean(float(row["distance"]) ** 2 for row in family_rows)
    )
    return {
        "reference_profile_id": reference["resolved_profile_id"],
        "reference_display_label": reference["resolved_display_label"],
        "reference_profile_analysis_run_id": reference["profile_analysis_run_id"],
        "distance": round(overall, 6),
        "family_distances": family_rows,
        "unavailable_families": unavailable_families,
        "feature_differences": sorted(
            all_features,
            key=lambda row: (
                float(row["standardized_absolute_difference"]),
                str(row["feature"]),
            ),
        ),
    }


def compare_profile_to_panel(
    database: Database,
    *,
    profile_id: int,
    panel_key: str,
    snapshot_id: int | None = None,
    analyzer_version: str = COMPARISON_ANALYZER_VERSION,
    comparison_level: str = "core",
    historical_references: bool = False,
) -> ComparisonOutcome:
    if comparison_level not in {"core", "full"}:
        raise ValueError("Comparison level must be core or full")
    if historical_references and snapshot_id is None:
        raise ValueError("Historical references require an explicit snapshot ID")
    if not analyzer_version.strip():
        raise ValueError("Comparison analyzer version must not be blank")
    panel = database.get_reference_panel(panel_key)
    if panel is None:
        raise ValueError(f"Unknown reference panel: {panel_key}")
    snapshot = (
        database.get_reference_panel_snapshot(snapshot_id)
        if snapshot_id is not None
        else database.get_latest_reference_panel_snapshot(panel.id)
    )
    if snapshot is None:
        detail = f" #{snapshot_id}" if snapshot_id is not None else ""
        raise ValueError(f"Reference panel {panel_key!r} has no snapshot{detail}")
    if snapshot.panel_id != panel.id:
        raise ValueError(
            f"Snapshot #{snapshot.id} does not belong to reference panel {panel_key!r}"
        )
    if snapshot.snapshot_analyzer_version != SNAPSHOT_ANALYZER_VERSION:
        raise ValueError(
            f"Reference panel snapshot #{snapshot.id} uses "
            f"{snapshot.snapshot_analyzer_version}; rebuild the panel for "
            f"{SNAPSHOT_ANALYZER_VERSION}"
        )
    if snapshot.feature_schema_version != FEATURE_SCHEMA_VERSION:
        raise ValueError(
            f"Reference panel snapshot #{snapshot.id} has incompatible feature schema "
            f"{snapshot.feature_schema_version}"
        )
    policy = _policy_from_snapshot(snapshot)
    candidate = _candidate_payload(
        database, requested_profile_id=profile_id, policy=policy
    )
    candidate_run_id = candidate["profile_analysis_run_id"]
    candidate_diagnostics = candidate["coverage_diagnostics"]
    assert isinstance(candidate_diagnostics, Mapping)
    depth_support = candidate_diagnostics.get("reviewed_feature_depth_support", {})
    candidate_core_supported = bool(
        isinstance(depth_support, Mapping)
        and depth_support.get("core")
        and depth_support.get("canonical_composition")
    )
    level = comparison_level
    reasons = list(candidate["exclusion_reasons"])  # type: ignore[arg-type]
    if candidate["eligibility_status"] != "eligible":
        reasons.insert(0, "candidate_ineligible")
    if level == "full" and not (isinstance(depth_support, Mapping) and depth_support.get("depth_sensitive")):
        reasons.append("insufficient_depth_for_full_comparison")
    if not candidate_core_supported:
        reasons.append("insufficient_depth_for_core_comparison")
    members = [
        _decode_member(item)
        for item in database.list_reference_panel_snapshot_members(snapshot.id)
    ]
    excluded_references: list[dict[str, object]] = []
    eligible_references: list[dict[str, object]] = []
    for member in members:
        member_reasons: list[str] = []
        if not historical_references:
            current = get_current_profile_scripture_run(database, int(member["resolved_profile_id"]))
            if current is None or current.id != member["profile_analysis_run_id"]:
                member_reasons.append("reference_snapshot_input_not_current")
                if member["eligibility_status"] == "eligible":
                    # Frozen calibration includes this member too. Silently
                    # dropping it would still use its stale normalization input.
                    reasons.append("reference_snapshot_inputs_not_current")
        if member["resolved_profile_id"] == candidate["resolved_profile_id"]:
            member_reasons.append("same_profile_as_candidate")
        if member["eligibility_status"] != "eligible":
            member_reasons.extend(member["exclusion_reasons"])  # type: ignore[arg-type]
        member_diagnostics = member["coverage_diagnostics"]
        member_depth = (
            member_diagnostics.get("reviewed_feature_depth_support", {})
            if isinstance(member_diagnostics, Mapping)
            else {}
        )
        if not (
            isinstance(member_depth, Mapping)
            and member_depth.get("core")
            and member_depth.get("canonical_composition")
        ):
            member_reasons.append("insufficient_depth_for_core_comparison")
        if level == "full" and not (
            isinstance(member_depth, Mapping) and member_depth.get("depth_sensitive")
        ):
            member_reasons.append("insufficient_depth_for_full_comparison")
        if member_reasons:
            excluded_references.append(
                {
                    "profile_id": member["resolved_profile_id"],
                    "display_label": member["resolved_display_label"],
                    "reasons": sorted(set(member_reasons)),
                }
            )
        else:
            eligible_references.append(member)
    if not eligible_references:
        reasons.append("no_eligible_reference_profiles")
    panel_statistics = json.loads(snapshot.panel_feature_statistics_json)
    families, omissions, mask_reasons = _common_feature_mask(
        candidate, eligible_references, _comparison_families(level), panel_statistics
    )
    reasons.extend(mask_reasons)
    rankings = []
    if not reasons:
        for reference in eligible_references:
            ranking = _rank_reference(
                candidate,
                reference,
                families=families,
                panel_statistics=panel_statistics,
            )
            if ranking is None:
                excluded_references.append(
                    {
                        "profile_id": reference["resolved_profile_id"],
                        "display_label": reference["resolved_display_label"],
                        "reasons": ["insufficient_normalization_or_feature_coverage"],
                    }
                )
            else:
                rankings.append(ranking)
        rankings.sort(key=lambda row: (float(row["distance"]), int(row["reference_profile_id"])))
        if not rankings:
            reasons.append("no_comparable_reference_profiles")
    ranking_separation = None
    if len(rankings) >= 2:
        nearest_distance = float(rankings[0]["distance"])
        second_distance = float(rankings[1]["distance"])
        ranking_separation = {
            "nearest_distance": nearest_distance,
            "second_nearest_distance": second_distance,
            "absolute_margin": round(second_distance - nearest_distance, 6),
            "relative_margin": (
                round((second_distance - nearest_distance) / second_distance, 6)
                if second_distance > 0
                else None
            ),
            "interpretation": "descriptive_ranking_separation_not_confidence",
        }
    result: dict[str, object] = {
        "schema_version": 2,
        "validation_status": "experimental_unvalidated",
        "certified_comparison_features": [],
        "input_scope": "current_candidate_historical_references" if historical_references else "current_candidate_and_references",
        "omitted_coordinates": omissions,
        "status": "comparable" if not reasons else "abstained",
        "abstention_reasons": sorted(set(reasons)),
        "scope": "experimental_comparison_of_collected_sermon_samples",
        "candidate": {
            "requested_profile_id": profile_id,
            "resolved_profile_id": candidate["resolved_profile_id"],
            "display_label": candidate["resolved_display_label"],
            "profile_analysis_run_id": candidate_run_id,
            "coverage_diagnostics": candidate_diagnostics,
        },
        "panel": {
            "key": panel.key,
            "display_name": panel.display_name,
            "snapshot_id": snapshot.id,
            "snapshot_fingerprint": snapshot.input_fingerprint,
        },
        "comparison_level": level,
        "feature_families": {
            name: list(features) for name, features in families.items()
        },
        "normalization": {
            "policy_version": NORMALIZATION_POLICY_VERSION,
            "center_source": "frozen_reference_panel_snapshot",
            "calibration_profile_ids": [member["resolved_profile_id"] for member in members if member["eligibility_status"] == "eligible"],
            "candidate_in_calibration": any(member["resolved_profile_id"] == candidate["resolved_profile_id"] and member["eligibility_status"] == "eligible" for member in members),
            "calibration_scope": "eligible_snapshot_members_including_any_candidate_overlap",
            "scale": "1.4826 * median absolute deviation; observed range fallback",
            "standardized_difference_cap": MAX_STANDARDIZED_DIFFERENCE,
            "family_aggregation": "root mean square within family",
            "overall_aggregation": "equal-weight root mean square across families",
        },
        "tied_nearest_reference_ids": [
            row["reference_profile_id"] for row in rankings
            if row["distance"] == rankings[0]["distance"]
        ],
        "effective_feature_squared_weights": {
            feature: 1 / (len(families) * len(features))
            for features in families.values() for feature in features
        },
        "rankings": rankings,
        "ranking_separation": ranking_separation,
        "excluded_references": excluded_references,
        "interpretation_limits": [
            "Distances are descriptive and are not calibrated probabilities.",
            "The nearest reference is not necessarily a close reference.",
            "This result does not measure overall preaching similarity or church fit.",
        ],
    }
    fingerprint = _fingerprint(
        {
            "analyzer_version": analyzer_version,
            "candidate_profile_id": candidate["resolved_profile_id"],
            "candidate_profile_analysis_run_id": candidate_run_id,
            "feature_schema_version": snapshot.feature_schema_version,
            "normalization_policy_version": NORMALIZATION_POLICY_VERSION,
            "panel_snapshot_id": snapshot.id,
            "result": result,
        }
    )
    run, created = database.add_benchmark_comparison_run(
        candidate_profile_id=int(candidate["resolved_profile_id"]),
        candidate_profile_analysis_run_id=(
            int(candidate_run_id) if candidate_run_id is not None else None
        ),
        panel_snapshot_id=snapshot.id,
        analyzer_version=analyzer_version,
        normalization_policy_version=NORMALIZATION_POLICY_VERSION,
        input_fingerprint=fingerprint,
        result_json=_json(result),
    )
    return ComparisonOutcome(
        run=run,
        created=created,
        result=json.loads(run.result_json),
    )
