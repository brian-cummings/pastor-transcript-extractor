from __future__ import annotations

from dataclasses import asdict, dataclass

from pastor_transcript_extractor.analysis_readiness import build_readiness_report
from pastor_transcript_extractor.profile_analysis import (
    profile_membership_fingerprint,
    resolve_profile_sermon_scope,
)
from pastor_transcript_extractor.storage import Database
from pastor_transcript_extractor.structure_analysis import (
    PROFILE_STRUCTURE_ANALYZER_KEY,
    PROFILE_STRUCTURE_ANALYZER_VERSION,
    STRUCTURE_ANALYZER_KEY,
    analyze_sermon_structure,
    build_profile_structure_analysis,
    prepare_structure_analysis,
    profile_structure_input_fingerprint,
)


@dataclass(frozen=True, slots=True)
class StructureProfileReadiness:
    profile_id: int
    display_label: str | None
    sermon_count: int
    current_sermons: int
    missing_sermons: int
    stale_sermons: int
    blocked_sermons: int
    aggregate_state: str
    aggregate_run_id: int | None
    sermon_states: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class StructureReadinessReport:
    profiles: tuple[StructureProfileReadiness, ...]

    @property
    def totals(self) -> dict[str, int]:
        return {
            "profiles": len(self.profiles),
            "sermons": sum(item.sermon_count for item in self.profiles),
            "current": sum(item.current_sermons for item in self.profiles),
            "missing": sum(item.missing_sermons for item in self.profiles),
            "stale": sum(item.stale_sermons for item in self.profiles),
            "blocked": sum(item.blocked_sermons for item in self.profiles),
            "current_aggregates": sum(item.aggregate_state == "current" for item in self.profiles),
        }

    def payload(self) -> dict[str, object]:
        return {"totals": self.totals, "profiles": [asdict(item) for item in self.profiles]}


@dataclass(frozen=True, slots=True)
class StructureBackfillResult:
    before: StructureReadinessReport
    after: StructureReadinessReport | None
    dry_run: bool
    created_sermon_runs: int
    reused_sermon_runs: int
    sermon_failures: tuple[tuple[int, str], ...]
    created_profile_runs: int
    reused_profile_runs: int
    profile_failures: tuple[tuple[int, str], ...]


def build_structure_readiness(database: Database) -> StructureReadinessReport:
    base = build_readiness_report(database)
    profiles = []
    for base_profile in base.profiles:
        try:
            scope = resolve_profile_sermon_scope(database, base_profile.profile_id)
        except ValueError:
            continue
        sermon_states = []
        current_run_ids = []
        counts = {"current": 0, "missing": 0, "stale": 0, "blocked": 0}
        for video in scope.videos:
            latest = database.get_latest_sermon_analysis_run(video.id, STRUCTURE_ANALYZER_KEY)
            blocking_reason = None
            current = None
            try:
                prepared = prepare_structure_analysis(database, video)
                current = database.get_sermon_analysis_run_by_fingerprint(
                    prepared.input_fingerprint
                )
            except ValueError as error:
                blocking_reason = str(error)
            state = (
                "current" if current is not None
                else "blocked" if blocking_reason is not None
                else "stale" if latest is not None
                else "missing"
            )
            counts[state] += 1
            if current is not None:
                current_run_ids.append(current.id)
            sermon_states.append({
                "video_id": video.id,
                "youtube_video_id": video.youtube_video_id,
                "state": state,
                "current_run_id": current.id if current else None,
                "latest_run_id": latest.id if latest else None,
                "blocking_reason": blocking_reason,
            })
        membership = profile_membership_fingerprint(database, scope)
        expected = profile_structure_input_fingerprint(
            profile_id=scope.profile_id,
            membership_fingerprint=membership,
            sermon_run_ids=current_run_ids,
        )
        exact = database.get_speaker_profile_analysis_run_by_fingerprint(expected)
        latest_profile = database.get_latest_speaker_profile_analysis_run(
            scope.profile_id, PROFILE_STRUCTURE_ANALYZER_KEY
        )
        all_current = bool(scope.videos) and len(current_run_ids) == len(scope.videos)
        aggregate_state = (
            "current" if exact is not None and all_current
            else "stale" if latest_profile is not None
            else "missing"
        )
        profile = database.get_speaker_profile(scope.profile_id)
        profiles.append(StructureProfileReadiness(
            profile_id=scope.profile_id,
            display_label=profile.display_label if profile else None,
            sermon_count=len(scope.videos),
            current_sermons=counts["current"],
            missing_sermons=counts["missing"],
            stale_sermons=counts["stale"],
            blocked_sermons=counts["blocked"],
            aggregate_state=aggregate_state,
            aggregate_run_id=exact.id if exact is not None and all_current else (
                latest_profile.id if latest_profile else None
            ),
            sermon_states=tuple(sermon_states),
        ))
    return StructureReadinessReport(tuple(sorted(profiles, key=lambda item: item.profile_id)))


def run_structure_backfill(
    database: Database, *, dry_run: bool = False, minimum_sermons: int = 3
) -> StructureBackfillResult:
    if minimum_sermons < 1:
        raise ValueError("Minimum sermons must be positive")
    before = build_structure_readiness(database)
    if dry_run:
        return StructureBackfillResult(before, None, True, 0, 0, (), 0, 0, ())
    videos_by_id = {video.id: video for video in database.list_videos()}
    target_ids = sorted({
        int(state["video_id"])
        for profile in before.profiles
        if profile.sermon_count >= minimum_sermons
        for state in profile.sermon_states
        if state["state"] in {"missing", "stale"}
    })
    created = reused = 0
    sermon_failures = []
    for video_id in target_ids:
        try:
            outcome = analyze_sermon_structure(database, videos_by_id[video_id])
            created += int(outcome.created)
            reused += int(not outcome.created)
        except Exception as error:
            sermon_failures.append((video_id, str(error)))
    created_profiles = reused_profiles = 0
    profile_failures = []
    for profile in before.profiles:
        if profile.sermon_count < minimum_sermons:
            continue
        try:
            outcome = build_profile_structure_analysis(database, profile.profile_id)
            created_profiles += int(outcome.created)
            reused_profiles += int(not outcome.created)
        except Exception as error:
            profile_failures.append((profile.profile_id, str(error)))
    return StructureBackfillResult(
        before,
        build_structure_readiness(database),
        False,
        created,
        reused,
        tuple(sermon_failures),
        created_profiles,
        reused_profiles,
        tuple(profile_failures),
    )
