from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

from pastor_transcript_extractor.models import SpeakerProfile, Video
from pastor_transcript_extractor.profile_analysis import (
    PROFILE_ANALYZER_KEY,
    PROFILE_ANALYZER_VERSION,
    build_profile_scripture_analysis,
    profile_analysis_input_fingerprint,
    profile_membership_fingerprint,
    resolve_profile_sermon_scope,
)
from pastor_transcript_extractor.sermon_analysis import (
    ANALYZER_KEY,
    ANALYZER_VERSION,
    AnalysisOutcome,
    analyze_sermon,
    prepare_sermon_analysis,
)
from pastor_transcript_extractor.storage import Database


ELIGIBLE_PROFILE_STATES = frozenset({"active", "provisional"})


@dataclass(frozen=True, slots=True)
class SermonReadiness:
    video_id: int
    youtube_video_id: str
    profile_ids: tuple[int, ...]
    state: str
    current_run_id: int | None
    latest_run_id: int | None
    blocking_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProfileReadiness:
    profile_id: int
    display_label: str | None
    lifecycle_state: str
    effective_sermons: int
    eligible_sermons: int
    excluded_without_identified_content: int
    current_sermons: int
    missing_sermons: int
    stale_sermons: int
    blocked_sermons: int
    aggregate_state: str
    aggregate_run_id: int | None
    exploratory_eligible: bool
    approaching_decision_depth: bool


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    analyzer_key: str
    analyzer_version: str
    profile_analyzer_key: str
    profile_analyzer_version: str
    sermons: tuple[SermonReadiness, ...]
    profiles: tuple[ProfileReadiness, ...]

    @property
    def eligible_sermons(self) -> int:
        return len(self.sermons)

    @property
    def current_sermons(self) -> int:
        return sum(item.state == "current" for item in self.sermons)

    @property
    def missing_sermons(self) -> int:
        return sum(item.state == "missing" for item in self.sermons)

    @property
    def stale_sermons(self) -> int:
        return sum(item.state == "stale" for item in self.sermons)

    @property
    def blocked_sermons(self) -> int:
        return sum(item.blocking_reason is not None for item in self.sermons)

    @property
    def coverage_percent(self) -> float:
        if not self.sermons:
            return 100.0
        return round(100 * self.current_sermons / len(self.sermons), 1)

    def depth_count(self, minimum: int) -> int:
        return sum(item.eligible_sermons >= minimum for item in self.profiles)

    def to_dict(self) -> dict[str, object]:
        return {
            "provenance": {
                "sermon_analyzer": f"{self.analyzer_key}@{self.analyzer_version}",
                "profile_analyzer": (
                    f"{self.profile_analyzer_key}@{self.profile_analyzer_version}"
                ),
            },
            "coverage": {
                "eligible": self.eligible_sermons,
                "current": self.current_sermons,
                "missing": self.missing_sermons,
                "stale": self.stale_sermons,
                "blocked": self.blocked_sermons,
                "percent_current": self.coverage_percent,
            },
            "profile_depth": {
                f"at_least_{minimum}": self.depth_count(minimum)
                for minimum in (3, 5, 8, 10)
            },
            "aggregate_states": {
                state: sum(item.aggregate_state == state for item in self.profiles)
                for state in ("current", "stale", "missing")
            },
            "sermons": [asdict(item) for item in self.sermons],
            "profiles": [asdict(item) for item in self.profiles],
        }


@dataclass(frozen=True, slots=True)
class BackfillResult:
    before: ReadinessReport
    after: ReadinessReport
    created_sermon_runs: int
    reused_sermon_runs: int
    failed_sermons: tuple[tuple[int, str], ...]
    created_profile_runs: int
    reused_profile_runs: int
    failed_profiles: tuple[tuple[int, str], ...]


def _eligible_profiles(database: Database) -> list[tuple[int, SpeakerProfile]]:
    resolved: dict[int, SpeakerProfile] = {}
    for profile in database.list_speaker_profiles():
        if profile.lifecycle_state not in ELIGIBLE_PROFILE_STATES:
            continue
        profile_id = database.resolve_speaker_profile_id(profile.id)
        canonical = database.get_speaker_profile(profile_id)
        if canonical is not None and canonical.lifecycle_state in ELIGIBLE_PROFILE_STATES:
            resolved[profile_id] = canonical
    return sorted(resolved.items())


def build_readiness_report(
    database: Database,
    *,
    analyzer_version: str = ANALYZER_VERSION,
    profile_analyzer_version: str = PROFILE_ANALYZER_VERSION,
) -> ReadinessReport:
    if not analyzer_version.strip() or not profile_analyzer_version.strip():
        raise ValueError("Analyzer versions must not be blank")
    videos_by_id = {video.id: video for video in database.list_videos()}
    profile_inputs: dict[int, tuple[SpeakerProfile, tuple[Video, ...]]] = {}
    video_profiles: dict[int, set[int]] = {}

    for profile_id, profile in _eligible_profiles(database):
        try:
            scope = resolve_profile_sermon_scope(database, profile_id)
        except ValueError:
            profile_inputs[profile_id] = (profile, ())
            continue
        profile_inputs[profile_id] = (profile, scope.videos)
        for video in scope.videos:
            extraction = database.get_latest_extraction_result_for_video(video.id)
            if extraction is not None and extraction.proposed_json_path is not None:
                video_profiles.setdefault(video.id, set()).add(profile_id)

    sermon_status: dict[int, SermonReadiness] = {}
    for video_id, profile_ids in sorted(video_profiles.items()):
        video = videos_by_id[video_id]
        latest = database.get_latest_sermon_analysis_run(video_id, ANALYZER_KEY)
        current = None
        blocking_reason = None
        try:
            prepared = prepare_sermon_analysis(
                database, video, analyzer_version=analyzer_version
            )
            current = database.get_sermon_analysis_run_by_fingerprint(
                prepared.input_fingerprint
            )
        except Exception as error:
            blocking_reason = str(error)
        state = "current" if current is not None else ("stale" if latest else "missing")
        sermon_status[video_id] = SermonReadiness(
            video_id=video_id,
            youtube_video_id=video.youtube_video_id,
            profile_ids=tuple(sorted(profile_ids)),
            state=state,
            current_run_id=current.id if current else None,
            latest_run_id=latest.id if latest else None,
            blocking_reason=blocking_reason,
        )

    profiles: list[ProfileReadiness] = []
    for profile_id, (profile, videos) in profile_inputs.items():
        effective_count = len(videos)
        eligible = [video for video in videos if video.id in sermon_status]
        statuses = [sermon_status[video.id] for video in eligible]
        current_ids = [item.current_run_id for item in statuses if item.current_run_id]
        latest_aggregate = database.get_latest_speaker_profile_analysis_run(
            profile_id, PROFILE_ANALYZER_KEY
        )
        aggregate_state = "missing"
        aggregate_run_id = latest_aggregate.id if latest_aggregate else None
        if videos:
            scope = resolve_profile_sermon_scope(database, profile_id)
            membership = profile_membership_fingerprint(database, scope)
            expected = profile_analysis_input_fingerprint(
                profile_id=profile_id,
                membership_fingerprint=membership,
                sermon_analysis_run_ids=current_ids,
                analyzer_version=profile_analyzer_version,
            )
            exact = database.get_speaker_profile_analysis_run_by_fingerprint(expected)
            all_current = bool(eligible) and len(current_ids) == len(eligible)
            if exact is not None and all_current:
                aggregate_state = "current"
                aggregate_run_id = exact.id
            elif latest_aggregate is not None:
                aggregate_state = "stale"
        profiles.append(
            ProfileReadiness(
                profile_id=profile_id,
                display_label=profile.display_label,
                lifecycle_state=profile.lifecycle_state,
                effective_sermons=effective_count,
                eligible_sermons=len(eligible),
                excluded_without_identified_content=effective_count - len(eligible),
                current_sermons=sum(item.state == "current" for item in statuses),
                missing_sermons=sum(item.state == "missing" for item in statuses),
                stale_sermons=sum(item.state == "stale" for item in statuses),
                blocked_sermons=sum(item.blocking_reason is not None for item in statuses),
                aggregate_state=aggregate_state,
                aggregate_run_id=aggregate_run_id,
                exploratory_eligible=len(eligible) >= 3,
                approaching_decision_depth=5 <= len(eligible) < 8,
            )
        )

    return ReadinessReport(
        analyzer_key=ANALYZER_KEY,
        analyzer_version=analyzer_version,
        profile_analyzer_key=PROFILE_ANALYZER_KEY,
        profile_analyzer_version=profile_analyzer_version,
        sermons=tuple(sermon_status.values()),
        profiles=tuple(profiles),
    )


def refresh_profile_analyses(
    database: Database,
    *,
    minimum_sermons: int = 3,
    analyzer_version: str = ANALYZER_VERSION,
    profile_analyzer_version: str = PROFILE_ANALYZER_VERSION,
) -> tuple[int, int, tuple[tuple[int, str], ...]]:
    if minimum_sermons < 1:
        raise ValueError("Minimum sermons must be at least 1")
    report = build_readiness_report(
        database,
        analyzer_version=analyzer_version,
        profile_analyzer_version=profile_analyzer_version,
    )
    created = reused = 0
    failures: list[tuple[int, str]] = []
    for profile in report.profiles:
        if (
            profile.eligible_sermons < minimum_sermons
            or profile.current_sermons != profile.eligible_sermons
            or profile.aggregate_state == "current"
        ):
            continue
        try:
            outcome = build_profile_scripture_analysis(
                database,
                profile.profile_id,
                analyzer_version=profile_analyzer_version,
                sermon_analyzer_version=analyzer_version,
            )
        except Exception as error:
            failures.append((profile.profile_id, str(error)))
            continue
        if outcome.created:
            created += 1
        else:
            reused += 1
    return created, reused, tuple(failures)


def run_deterministic_backfill(
    database: Database,
    *,
    minimum_sermons: int = 3,
    analyzer_version: str = ANALYZER_VERSION,
    profile_analyzer_version: str = PROFILE_ANALYZER_VERSION,
    analyze: Callable[..., AnalysisOutcome] = analyze_sermon,
) -> BackfillResult:
    if minimum_sermons < 1:
        raise ValueError("Minimum sermons must be at least 1")
    before = build_readiness_report(
        database,
        analyzer_version=analyzer_version,
        profile_analyzer_version=profile_analyzer_version,
    )
    videos = {video.id: video for video in database.list_videos()}
    created = reused = 0
    failures: list[tuple[int, str]] = []
    for item in before.sermons:
        if item.state == "current":
            continue
        try:
            outcome = analyze(
                database, videos[item.video_id], analyzer_version=analyzer_version
            )
        except Exception as error:
            failures.append((item.video_id, str(error)))
            continue
        if outcome.created:
            created += 1
        else:
            reused += 1

    profile_created, profile_reused, profile_failures = refresh_profile_analyses(
        database,
        minimum_sermons=minimum_sermons,
        analyzer_version=analyzer_version,
        profile_analyzer_version=profile_analyzer_version,
    )
    after = build_readiness_report(
        database,
        analyzer_version=analyzer_version,
        profile_analyzer_version=profile_analyzer_version,
    )
    return BackfillResult(
        before=before,
        after=after,
        created_sermon_runs=created,
        reused_sermon_runs=reused,
        failed_sermons=tuple(failures),
        created_profile_runs=profile_created,
        reused_profile_runs=profile_reused,
        failed_profiles=profile_failures,
    )
