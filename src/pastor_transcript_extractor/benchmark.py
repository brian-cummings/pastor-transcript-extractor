from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import statistics
from typing import Mapping

from pastor_transcript_extractor.models import (
    ReferencePanel,
    ReferencePanelMembershipEvent,
    ReferencePanelSnapshot,
    ReferencePanelSnapshotMember,
)
from pastor_transcript_extractor.profile_analysis import (
    PROFILE_ANALYZER_KEY,
    PROFILE_ANALYZER_VERSION,
    PROFILE_FEATURE_ORDER,
)
from pastor_transcript_extractor.storage import Database


SNAPSHOT_ANALYZER_VERSION = "reference-panel-snapshot@1"
FEATURE_SCHEMA_VERSION = "deterministic-profile-feature-vector@2"
ELIGIBILITY_POLICY_VERSION = "scripture-reference-eligibility@1"

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
COMPARISON_FEATURE_NAMES = tuple(
    name for name in PROFILE_FEATURE_ORDER if name != "analysis_coverage_fraction"
)
REQUIRED_COMPARISON_FEATURE_NAMES = (
    "zero_detected_reference_sermon_fraction",
    "references_per_1000_words",
    "book_breadth_per_10_references",
    "book_concentration_hhi",
    "old_testament_share",
)
UNSUPPORTED_FEATURE_FAMILIES = (
    "semantic-style-run-coverage",
    "theology",
    "politics",
    "christian-nationalism",
    "embeddings",
)
FEATURE_FAMILY_ASSIGNMENTS = {
    "version": "benchmark-feature-families@1",
    "comparison_eligible": list(COMPARISON_FEATURE_NAMES),
    "diagnostic_only": list(COVERAGE_FEATURE_NAMES),
    "excluded": list(UNSUPPORTED_FEATURE_FAMILIES),
}

_PANEL_KEY = re.compile(r"^[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class EligibilityPolicy:
    version: str = ELIGIBILITY_POLICY_VERSION
    minimum_analyzed_sermons: int = 3
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
    run = database.get_compatible_speaker_profile_analysis_run(
        resolved_id, PROFILE_ANALYZER_KEY, PROFILE_ANALYZER_VERSION
    )
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
        reasons.append("missing_analysis")
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
        comparison = {name: _number(by_name.get(name)) for name in COMPARISON_FEATURE_NAMES}
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
