from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

import typer
from rich.console import Console

from pastor_transcript_extractor.artifact_namespace import resolve_video_artifact_paths
from pastor_transcript_extractor.commands.apps import root_app
from pastor_transcript_extractor.commands.common import get_database
from pastor_transcript_extractor.config import build_llm_config, build_paths
from pastor_transcript_extractor.fixture_validation import validate_fixture_directory
from pastor_transcript_extractor.interaction_diagnostics import (
    DEFAULT_SENTINELS,
    DiagnosticInferenceCache,
    build_diagnostic_report,
    create_diagnostic_run,
    load_sentinel_blocks,
    run_model_diagnostics,
)
from pastor_transcript_extractor.local_llm import OllamaClient
from pastor_transcript_extractor.recording_verifier import (
    RecordingVerifierCache,
    build_report as build_recording_verifier_report,
    create_run as create_recording_verifier_run,
    load_cases as load_recording_verifier_cases,
    run_diagnostics as run_recording_verifier_diagnostics,
    validate_partition_access,
)
from pastor_transcript_extractor.reviewed_speaker_evidence import load_reviewed_speaker_evidence
from pastor_transcript_extractor.speaker_machine_assignment import (
    machine_assignment_report,
)
from pastor_transcript_extractor.speaker_pair_eligibility import (
    assess_automatic_speaker_observation,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    assess_profile_association_readiness,
)
from pastor_transcript_extractor.fixture_validation import (
    FixtureValidationError,
    ValidatedFixture,
    validate_fixture_payload,
)
from pastor_transcript_extractor.pipeline_diagnostics import (
    aggregate_diagnostic_traces,
    build_comparison_markdown,
    build_diagnostic_markdown,
    build_diagnostic_trace,
    build_identity_automation_blocker_analysis,
    build_identity_operational_outcome,
    build_systemic_markdown,
    build_systemic_progression_summary,
    compact_diagnostic_trace,
    compare_systemic_reports,
    load_identity_association_admissions,
    load_identity_association_attempts,
    load_identity_boundary_feedback,
)


console = Console()


def _load_pipeline_diagnostic_fixture(
    fixture_path: Path | None,
    *,
    youtube_video_id: str,
) -> ValidatedFixture | None:
    if fixture_path is None:
        return None
    resolved = fixture_path.expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        fixture = validate_fixture_payload(payload, path=resolved)
    except (OSError, json.JSONDecodeError, FixtureValidationError) as error:
        raise typer.BadParameter(f"Invalid diagnostic fixture: {error}") from error
    if fixture.video_id != youtube_video_id:
        raise typer.BadParameter(
            f"Fixture video id {fixture.video_id!r} does not match {youtube_video_id!r}."
        )
    return fixture


def _persisted_identity_outcome(
    database: Any,
    *,
    video_id: int,
    extraction_result_id: int,
    content_disposition: str | None,
    association_attempts: list[dict[str, Any]],
    boundary_feedback: list[dict[str, Any]],
) -> dict[str, Any]:
    observation = database.get_latest_speaker_observation_for_video(video_id)
    profile_ids = (
        sorted(
            {
                database.resolve_speaker_profile_id(profile_id)
                for profile_id in database.list_effective_profile_ids_for_observation(
                    observation.id
                )
            }
        )
        if observation is not None
        else []
    )
    profile_redirects = {
        profile.id: database.resolve_speaker_profile_id(profile.id)
        for profile in database.list_speaker_profiles()
    }
    return build_identity_operational_outcome(
        content_disposition=content_disposition,
        extraction_result_id=extraction_result_id,
        observation=(
            {
                "id": observation.id,
                "extraction_result_id": observation.extraction_result_id,
                "input_fingerprint": observation.input_fingerprint,
            }
            if observation is not None
            else None
        ),
        effective_profile_ids=profile_ids,
        association_attempts=association_attempts,
        boundary_feedback=boundary_feedback,
        profile_redirects=profile_redirects,
    )

@root_app.command(
    "diagnose",
    help="Build a read-only sermon-isolation trace and human diagnostic views.",
)
def diagnose_pipeline(
    video_id: int = typer.Option(..., "--video-id", help="Database video id to diagnose."),
    fixture: Path | None = typer.Option(
        None,
        "--fixture",
        help="Optional reviewed fixture JSON for actual recall and contamination measurements.",
    ),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Output directory; defaults to the video's immutable artifact namespace.",
    ),
    identity_feedback_root: Path = typer.Option(
        Path("evaluation/speaker-associations/shadow-runs"),
        "--identity-feedback-root",
        help=(
            "Existing identity shadow artifacts containing association outcomes and "
            "sermon-edge advisories."
        ),
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    paths = build_paths(base_dir, remember=True)
    video = database.get_video_by_id(video_id)
    if video is None:
        raise typer.BadParameter(f"Unknown video id: {video_id}")
    extraction = database.get_latest_extraction_result_for_video(video.id)
    if extraction is None or not extraction.proposed_json_path:
        raise typer.BadParameter(f"Video #{video.id} has no proposed extraction artifact.")
    proposed_path = Path(extraction.proposed_json_path)
    try:
        proposed = json.loads(proposed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise typer.BadParameter(f"Invalid proposed extraction artifact: {error}") from error
    if not isinstance(proposed, dict):
        raise typer.BadParameter("Proposed extraction artifact must be a JSON object.")
    reviewed_fixture = _load_pipeline_diagnostic_fixture(
        fixture,
        youtube_video_id=video.youtube_video_id,
    )
    identity_feedback = load_identity_boundary_feedback(
        identity_feedback_root,
        database_video_ids={video.id},
    )
    identity_attempts = load_identity_association_attempts(
        identity_feedback_root,
        database_video_ids={video.id},
    )
    disposition = proposed.get("final_disposition")
    disposition = disposition if isinstance(disposition, dict) else {}
    identity_observation = database.get_latest_speaker_observation_for_video(video.id)
    boundary_feedback = [
        event
        for event in identity_feedback.get(video.id, [])
        if event.get("observation_id") in {
            None,
            identity_observation.id if identity_observation is not None else None,
        }
    ]
    trace = build_diagnostic_trace(
        proposed,
        proposed_path=proposed_path,
        youtube_video_id=video.youtube_video_id,
        database_video_id=video.id,
        fixture=reviewed_fixture,
        media_duration_seconds=float(video.duration_seconds) if video.duration_seconds else None,
        video_title=video.title,
        identity_boundary_feedback=boundary_feedback,
        identity_outcome=_persisted_identity_outcome(
            database,
            video_id=video.id,
            extraction_result_id=extraction.id,
            content_disposition=(
                str(disposition["status"]) if disposition.get("status") else None
            ),
            association_attempts=identity_attempts.get(video.id, []),
            boundary_feedback=boundary_feedback,
        ),
    )
    root = (
        output_dir.expanduser().resolve()
        if output_dir is not None
        else resolve_video_artifact_paths(database, paths, video).root / "diagnostics"
    )
    root.mkdir(parents=True, exist_ok=True)
    trace_path = root / "diagnostic-trace-v7.json"
    report_path = root / "diagnostic-report.md"
    trace_path.write_text(json.dumps(trace, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(build_diagnostic_markdown(trace), encoding="utf-8")
    console.print(f"Wrote canonical diagnostic trace to {trace_path}")
    console.print(f"Wrote pipeline and timeline views to {report_path}")
    operational = trace.get("operational_status", {})
    operational = operational if isinstance(operational, dict) else {}
    blocker = operational.get("blocker")
    blocker_label = (
        f"{blocker.get('stage')} / {blocker.get('code')}"
        if isinstance(blocker, dict)
        else "none"
    )
    window = operational.get("effective_window")
    window_label = (
        f"{float(window['start_seconds']):.0f}s–{float(window['end_seconds']):.0f}s"
        if isinstance(window, dict)
        and isinstance(window.get("start_seconds"), (int, float))
        and isinstance(window.get("end_seconds"), (int, float))
        else "none"
    )
    console.print(
        f"Current disposition: {operational.get('disposition', 'unknown')}; "
        f"effective window: {window_label}; operational blocker: {blocker_label}."
    )
    if trace.get("ground_truth", {}).get("status") != "available":
        console.print("Measured correctness: unavailable without reviewed ground truth.")
    observed = trace.get("earliest_observed_failure")
    cause = trace.get("root_cause_hypothesis", {})
    console.print(
        "Earliest observed failure: "
        f"{observed.get('stage') if isinstance(observed, dict) else 'none'}; "
        f"likely cause: {cause.get('stage') or 'none'} "
        f"({cause.get('confidence') or 'n/a'} confidence)."
    )

@root_app.command(
    "diagnose-system",
    help="Diagnose all existing extraction outcomes without reclassifying the corpus.",
)
def diagnose_pipeline_system(
    fixture_dir: Path = typer.Option(
        Path("evaluation/fixtures"),
        help="Reviewed fixture directory to diagnose from existing artifacts.",
    ),
    output_root: Path = typer.Option(
        Path("evaluation/diagnostics"),
        help="Generated systemic diagnostic root.",
    ),
    identity_feedback_root: Path = typer.Option(
        Path("evaluation/speaker-associations/shadow-runs"),
        "--identity-feedback-root",
        help=(
            "Existing identity shadow artifacts containing association outcomes and "
            "sermon-edge advisories."
        ),
    ),
    speaker_evidence_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"),
        "--speaker-evidence-root",
        help="Reviewed speaker evidence used to reconstruct current profile topology.",
    ),
    all_existing: bool = typer.Option(
        True,
        "--all-existing/--fixtures-only",
        help=(
            "Include every latest extraction artifact; matching fixtures add reviewed "
            "quality evidence."
        ),
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help=(
            "Embed complete traces and write per-video diagnostic files. The default "
            "systemic JSON keeps only comparison-ready trace projections."
        ),
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    try:
        fixtures = validate_fixture_directory(fixture_dir.expanduser().resolve())
    except FixtureValidationError as error:
        raise typer.BadParameter(str(error)) from error
    fixtures_by_youtube_id = {fixture.video_id: fixture for fixture in fixtures}
    videos = database.list_videos()
    videos_by_id = {video.id: video for video in videos}
    videos_by_youtube_id = {video.youtube_video_id: video for video in videos}
    latest_extractions = {}
    for extraction in database.list_extraction_results():
        existing = latest_extractions.get(extraction.video_id)
        if existing is None or extraction.id > existing.id:
            latest_extractions[extraction.video_id] = extraction
    missing: list[dict[str, str]] = []
    targets: list[tuple[Any, Any, ValidatedFixture | None]] = []
    if all_existing:
        for video_id, extraction in latest_extractions.items():
            video = videos_by_id.get(video_id)
            if video is None:
                continue
            targets.append(
                (
                    video,
                    extraction,
                    fixtures_by_youtube_id.get(video.youtube_video_id),
                )
            )
        targeted_youtube_ids = {video.youtube_video_id for video, _, _ in targets}
        for fixture in fixtures:
            if fixture.video_id not in targeted_youtube_ids:
                missing.append(
                    {
                        "youtube_video_id": fixture.video_id,
                        "reason": "reviewed_fixture_video_or_extraction_missing",
                    }
                )
    else:
        for fixture in fixtures:
            video = videos_by_youtube_id.get(fixture.video_id)
            extraction = latest_extractions.get(video.id) if video is not None else None
            if video is None or extraction is None:
                missing.append(
                    {
                        "youtube_video_id": fixture.video_id,
                        "reason": "video_or_proposed_artifact_missing",
                    }
                )
                continue
            targets.append((video, extraction, fixture))
    targets.sort(key=lambda item: item[0].youtube_video_id)
    diagnostic_video_ids = {video.id for video, _, _ in targets}
    identity_feedback = load_identity_boundary_feedback(
        identity_feedback_root,
        database_video_ids=diagnostic_video_ids,
    )
    identity_attempts = load_identity_association_attempts(
        identity_feedback_root,
        database_video_ids=diagnostic_video_ids,
    )
    identity_admissions = load_identity_association_admissions(
        identity_feedback_root,
        database_video_ids=diagnostic_video_ids,
    )
    all_observations = database.list_speaker_observations()
    observations_by_video_id = {}
    for observation in all_observations:
        existing = observations_by_video_id.get(observation.video_id)
        if existing is None or observation.id > existing.id:
            observations_by_video_id[observation.video_id] = observation
    profile_ids_by_observation_id = {
        observation.id: sorted(
            {
                database.resolve_speaker_profile_id(profile_id)
                for profile_id in database.list_effective_profile_ids_for_observation(
                    observation.id
                )
            }
        )
        for observation in observations_by_video_id.values()
    }
    profile_redirects = {
        profile.id: database.resolve_speaker_profile_id(profile.id)
        for profile in database.list_speaker_profiles()
    }
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    output_dir = output_root.expanduser().resolve() / run_id
    video_root = output_dir / "videos"
    traces: list[dict[str, Any]] = []
    for video, extraction, reviewed_fixture in targets:
        if not extraction.proposed_json_path:
            missing.append(
                {
                    "youtube_video_id": video.youtube_video_id,
                    "reason": "proposed_artifact_path_missing",
                }
            )
            continue
        proposed_path = Path(extraction.proposed_json_path)
        try:
            proposed = json.loads(proposed_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            missing.append(
                {
                    "youtube_video_id": video.youtube_video_id,
                    "reason": "proposed_artifact_invalid",
                }
            )
            continue
        if not isinstance(proposed, dict):
            missing.append(
                {
                    "youtube_video_id": video.youtube_video_id,
                    "reason": "proposed_artifact_not_object",
                }
            )
            continue
        observation = observations_by_video_id.get(video.id)
        boundary_feedback = [
            event
            for event in identity_feedback.get(video.id, [])
            if event.get("observation_id")
            in {None, observation.id if observation is not None else None}
        ]
        disposition = proposed.get("final_disposition")
        disposition = disposition if isinstance(disposition, dict) else {}
        trace = build_diagnostic_trace(
            proposed,
            proposed_path=proposed_path,
            youtube_video_id=video.youtube_video_id,
            database_video_id=video.id,
            fixture=reviewed_fixture,
            media_duration_seconds=(
                float(video.duration_seconds) if video.duration_seconds else None
            ),
            video_title=video.title,
            identity_boundary_feedback=boundary_feedback,
            identity_outcome=build_identity_operational_outcome(
                content_disposition=(
                    str(disposition["status"])
                    if disposition.get("status")
                    else None
                ),
                extraction_result_id=extraction.id,
                observation=(
                    {
                        "id": observation.id,
                        "extraction_result_id": observation.extraction_result_id,
                        "input_fingerprint": observation.input_fingerprint,
                    }
                    if observation is not None
                    else None
                ),
                effective_profile_ids=(
                    profile_ids_by_observation_id.get(observation.id, [])
                    if observation is not None
                    else []
                ),
                association_attempts=identity_attempts.get(video.id, []),
                boundary_feedback=boundary_feedback,
                profile_redirects=profile_redirects,
            ),
        )
        traces.append(trace)
        if verbose:
            per_video = video_root / video.youtube_video_id
            per_video.mkdir(parents=True, exist_ok=True)
            (per_video / "diagnostic-trace-v7.json").write_text(
                json.dumps(trace, indent=2, sort_keys=True), encoding="utf-8"
            )
            (per_video / "diagnostic-report.md").write_text(
                build_diagnostic_markdown(trace), encoding="utf-8"
            )
    status_counts: dict[str, int] = {}
    without_extraction_status_counts: dict[str, int] = {}
    for video in videos:
        status = video.status.value
        status_counts[status] = status_counts.get(status, 0) + 1
        if video.id not in latest_extractions:
            without_extraction_status_counts[status] = (
                without_extraction_status_counts.get(status, 0) + 1
            )
    try:
        reviewed_speaker_evidence = load_reviewed_speaker_evidence(
            speaker_evidence_root.expanduser().resolve()
        )
        profile_readiness = assess_profile_association_readiness(
            database, reviewed_speaker_evidence
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(
            f"Unable to build identity automation-blocker analysis: {error}"
        ) from error
    observation_by_fingerprint = {
        observation.input_fingerprint: {
            "observation_id": observation.id,
            "database_video_id": observation.video_id,
            "youtube_video_id": (
                videos_by_id[observation.video_id].youtube_video_id
                if observation.video_id in videos_by_id
                else None
            ),
        }
        for observation in all_observations
    }
    association_eligibility_by_observation_id: dict[int, str] = {}
    for trace in traces:
        identity_outcome = trace.get("identity_outcome")
        identity_outcome = (
            identity_outcome if isinstance(identity_outcome, dict) else {}
        )
        observation_id = identity_outcome.get("observation_id")
        trace_video = trace.get("video")
        trace_video = trace_video if isinstance(trace_video, dict) else {}
        database_video_id = trace_video.get("database_video_id")
        if not (
            identity_outcome.get("content_disposition") == "accepted_sermon"
            and identity_outcome.get("observation_status") == "current"
            and isinstance(observation_id, int)
            and not identity_outcome.get("effective_profile_ids")
            and not identity_outcome.get("latest_association_outcome")
            and isinstance(database_video_id, int)
        ):
            continue
        eligibility = assess_automatic_speaker_observation(
            database,
            database_video_id,
            verify_media=False,
        )
        association_eligibility_by_observation_id[observation_id] = (
            eligibility.reason_code
        )
    current_machine_assignment_report = machine_assignment_report(database)
    identity_automation_blockers = build_identity_automation_blocker_analysis(
        traces,
        profile_readiness=[
            {
                "profile_id": profile.profile_id,
                "member_observation_ids": list(profile.member_observation_ids),
                "member_fingerprints": list(profile.member_fingerprints),
                "recording_count": profile.recording_count,
                "normalized_names": list(profile.normalized_names),
                "automatic_profile_ready": profile.automatic_profile_ready,
                "automatic_blockers": list(profile.automatic_blockers),
                "certified_exemplar_observation_ids": list(
                    profile.certified_exemplar_observation_ids
                ),
            }
            for profile in profile_readiness
        ],
        reviewed_same_pairs=[
            sorted(relation.fingerprints)
            for relation in reviewed_speaker_evidence.pair_relations.values()
            if relation.outcome == "same_speaker"
        ],
        observation_by_fingerprint=observation_by_fingerprint,
        association_eligibility_by_observation_id=(
            association_eligibility_by_observation_id
        ),
        association_admission_by_observation_id=identity_admissions,
        machine_assignments=current_machine_assignment_report["assignments"],
        tripped_machine_policy_fingerprints=(
            current_machine_assignment_report[
                "tripped_policy_fingerprints"
            ]
        ),
        profile_redirects=profile_redirects,
    )
    report = aggregate_diagnostic_traces(
        traces,
        missing=missing,
        scope="all_existing" if all_existing else "reviewed_fixtures",
        population_summary=(
            {
                "population_count": len(videos),
                "database_video_count": len(videos),
                "latest_extraction_count": len(latest_extractions),
                "videos_without_extraction_count": len(videos)
                - len(latest_extractions),
                "video_status_counts": dict(sorted(status_counts.items())),
                "videos_without_extraction_status_counts": dict(
                    sorted(without_extraction_status_counts.items())
                ),
                "reviewed_fixture_count": len(fixtures),
            }
            if all_existing
            else {"reviewed_fixture_count": len(fixtures)}
        ),
        identity_automation_blockers=identity_automation_blockers,
    )
    report["pipeline_progression_summary"] = (
        build_systemic_progression_summary(report)
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "system-diagnostics.json"
    markdown_path = output_dir / "system-diagnostics.md"
    persisted_report = {
        **report,
        "trace_detail_level": "full" if verbose else "compact_comparison",
        "traces": (
            traces
            if verbose
            else [compact_diagnostic_trace(trace) for trace in traces]
        ),
    }
    json_path.write_text(
        json.dumps(persisted_report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    markdown_path.write_text(build_systemic_markdown(report), encoding="utf-8")
    console.print(f"Wrote systemic diagnostic evidence to {json_path}")
    console.print(f"Wrote systemic failure view to {markdown_path}")
    population = report["population"]
    console.print(
        f"Derived {len(traces)} trace(s): "
        f"reviewed={population['reviewed_trace_count']}, "
        f"unreviewed={population['unreviewed_trace_count']}; "
        f"missing={len(missing)}; "
        f"trace_detail={'full' if verbose else 'compact'}. "
        "No extraction or classification artifacts were changed."
    )


@root_app.command(
    "diagnose-compare",
    help="Compare two existing systemic diagnostic reports without reclassifying.",
)
def compare_pipeline_diagnostics(
    before: Path = typer.Option(..., "--before", help="Earlier system-diagnostics.json."),
    after: Path = typer.Option(..., "--after", help="Later system-diagnostics.json."),
    output_root: Path = typer.Option(
        Path("evaluation/diagnostics/comparisons"),
        help="Generated comparison root.",
    ),
) -> None:
    reports: list[dict[str, Any]] = []
    for label, path in (("before", before), ("after", after)):
        resolved = path.expanduser().resolve()
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise typer.BadParameter(f"Invalid {label} diagnostic report: {error}") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("traces"), list):
            raise typer.BadParameter(
                f"Invalid {label} diagnostic report: expected an object with traces."
            )
        reports.append(payload)
    comparison = compare_systemic_reports(reports[0], reports[1])
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    output_dir = output_root.expanduser().resolve() / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "diagnostic-comparison.json"
    markdown_path = output_dir / "diagnostic-comparison.md"
    json_path.write_text(
        json.dumps(comparison, indent=2, sort_keys=True), encoding="utf-8"
    )
    markdown_path.write_text(
        build_comparison_markdown(comparison), encoding="utf-8"
    )
    console.print(f"Wrote diagnostic comparison evidence to {json_path}")
    console.print(f"Wrote diagnostic comparison view to {markdown_path}")
    counts = comparison["change_counts"]
    ordered_changes = (
        "fixed",
        "improved",
        "regressed",
        "tradeoff",
        "policy_changed",
        "changed",
        "unchanged",
        "added",
        "removed",
    )
    summary = ", ".join(
        f"{change}={counts[change]}"
        for change in ordered_changes
        if change in counts
    )
    console.print(
        f"Compared {sum(counts.values())} existing trace(s): {summary}."
    )


@root_app.command(
    "diagnose-interaction",
    help="Compare local models on deduplicated interaction evidence without changing production artifacts.",
)
def diagnose_interaction(
    models: list[str] | None = typer.Option(
        None, "--model", help="Ollama model to compare; repeat for multiple models."
    ),
    output_root: Path = typer.Option(
        Path("evaluation/interaction-diagnostics"), help="Generated diagnostic result root."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    database = get_database(base_dir)
    selected_models = models or [build_llm_config().model]
    sentinels = [
        (video_id, *load_sentinel_blocks(database, video_id))
        for video_id in DEFAULT_SENTINELS
    ]
    root = output_root.expanduser().resolve()
    cache = DiagnosticInferenceCache(root / "cache")
    llm_config = build_llm_config()
    model_results: list[dict[str, object]] = []
    for model in selected_models:
        client = OllamaClient(replace(llm_config, enabled=True, model=model))
        try:
            digest = client.model_digest()
        except Exception as error:
            raise typer.BadParameter(
                f"Could not use Ollama model {model!r}; install it before comparison: {error}"
            ) from error
        console.print(f"Running offline interaction diagnostics with {model}")
        model_results.append(run_model_diagnostics(
            client,
            model_digest=digest,
            sentinels=sentinels,
            cache=cache,
            progress=lambda current_model, video_id, current, total: console.print(
                f"  {current_model} {video_id} block {current}/{total}"
            ),
        ))
    run = create_diagnostic_run(model_results)
    output_dir = root / str(run["run_id"])
    output_dir.mkdir(parents=True, exist_ok=False)
    json_path = output_dir / "results.json"
    report_path = output_dir / "report.md"
    json_path.write_text(json.dumps(run, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(build_diagnostic_report(run), encoding="utf-8")
    console.print(f"Wrote interaction diagnostic JSON to {json_path}")
    console.print(f"Wrote interaction diagnostic report to {report_path}")


@root_app.command(
    "diagnose-recording-verifier",
    help="Test one recording-level sermon decision on a non-held-out fixture partition.",
)
def diagnose_recording_verifier(
    model: str = typer.Option("gemma3:12b", "--model", help="Ollama model to test."),
    partition: str = typer.Option(
        "development",
        "--partition",
        help="Fixture partition to test. Use development while tuning.",
    ),
    confirm_frozen_policy: bool = typer.Option(
        False,
        "--confirm-frozen-policy",
        help="Required to unseal the held-out partition for final validation.",
    ),
    fixture_dir: Path = typer.Option(
        Path("evaluation/fixtures"), help="Approved fixture directory."
    ),
    output_root: Path = typer.Option(
        Path("evaluation/recording-verifier"),
        help="Generated diagnostic result root.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    try:
        validate_partition_access(
            partition,
            confirm_frozen_policy=confirm_frozen_policy,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    database = get_database(base_dir)
    fixture_root = fixture_dir.expanduser().resolve()
    cases = load_recording_verifier_cases(
        database,
        fixture_root,
        partition=partition,
    )
    if not cases:
        raise typer.BadParameter(f"No fixtures found in partition {partition!r}.")
    root = output_root.expanduser().resolve()
    llm_config = build_llm_config()
    client = OllamaClient(replace(llm_config, enabled=True, model=model))
    try:
        digest = client.model_digest()
    except Exception as error:
        raise typer.BadParameter(
            f"Could not use Ollama model {model!r}; install it before comparison: {error}"
        ) from error
    console.print(
        f"Running recording-level verifier with {model} on "
        f"{len(cases)} {partition} fixture(s)."
    )
    model_result = run_recording_verifier_diagnostics(
        client,
        model_digest=digest,
        cases=cases,
        cache=RecordingVerifierCache(root / "cache"),
        progress=lambda video_id, current, total: console.print(
            f"  {video_id} case {current}/{total}"
        ),
    )
    run = create_recording_verifier_run(model_result, partition=partition)
    output_dir = root / str(run["run_id"])
    output_dir.mkdir(parents=True, exist_ok=False)
    json_path = output_dir / "results.json"
    report_path = output_dir / "report.md"
    json_path.write_text(json.dumps(run, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(
        build_recording_verifier_report(run),
        encoding="utf-8",
    )
    console.print(f"Wrote recording verifier JSON to {json_path}")
    console.print(f"Wrote recording verifier report to {report_path}")
