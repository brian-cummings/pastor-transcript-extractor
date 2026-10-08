from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Callable
import webbrowser

import typer
from rich.console import Console
from rich.table import Table

from pastor_transcript_extractor.commands.apps import identity_app
from pastor_transcript_extractor.config import AppPaths, build_paths
from pastor_transcript_extractor.ground_truth_review import format_timestamp
from pastor_transcript_extractor.media_archive import (
    write_canonical_clip_preparation_manifest,
)
from pastor_transcript_extractor.media_artifacts import (
    ArchivedMediaUnavailableError,
    MediaVerificationCache,
    get_registered_normalized_media_artifact,
    get_verified_normalized_media_artifact,
    resolve_normalized_audio_path,
)
from pastor_transcript_extractor.speaker_pair_diagnostics import AudioSpanCache
from pastor_transcript_extractor.speaker_pair_review import (
    ObservationQualification,
    PairJudgment,
    ReviewEvidenceMode,
    ReviewSubmission,
    STANDARD_VARIATION_TAGS,
    create_observation_review_packet,
    create_review_draft,
    submit_review,
)
from pastor_transcript_extractor.speaker_review_invalidation import (
    load_review_revocations,
)
from pastor_transcript_extractor.speaker_negative_window_audit import (
    audit_speaker_negative_windows,
)
from pastor_transcript_extractor.storage import Database


console = Console()
_ground_truth_reviewer: Callable[..., object] | None = None


def configure_ground_truth_reviewer(reviewer: Callable[..., object]) -> None:
    """Bind the existing sermon ground-truth command at composition time."""
    global _ground_truth_reviewer
    _ground_truth_reviewer = reviewer


def _prompt_review_choice(prompt: str, choices: dict[str, object]) -> object:
    choice_text = "/".join(choices)
    while True:
        value = typer.prompt(f"{prompt} [{choice_text}]").strip().lower()
        if value in choices:
            return choices[value]
        console.print(f"Choose one of: {', '.join(choices)}")


def _normalize_review_terminal_input() -> None:
    """Restore Enter-to-newline translation before interactive review prompts."""
    try:
        import termios
    except ImportError:
        return

    try:
        stdin_fd = sys.stdin.fileno()
        if not os.isatty(stdin_fd):
            return
        attributes = termios.tcgetattr(stdin_fd)
        input_flags = attributes[0]
        normalized_flags = (input_flags | termios.ICRNL) & ~(
            termios.IGNCR | termios.INLCR
        )
        if normalized_flags == input_flags:
            return
        attributes[0] = normalized_flags
        termios.tcsetattr(stdin_fd, termios.TCSANOW, attributes)
    except (OSError, ValueError, termios.error):
        # Non-POSIX, detached, and test streams need no terminal repair.
        return


@identity_app.command(
    "review-observation",
    help="Present one observation's clips with exact YouTube URLs and timestamps.",
)
def review_observation(
    youtube_video_id: str | None = typer.Option(
        None, "--youtube-video-id", help="Review one YouTube video observation."
    ),
    observation_fingerprint: str | None = typer.Option(
        None,
        "--observation-fingerprint",
        help="Review one exact immutable observation instead of selecting the latest.",
    ),
    all_affected: bool = typer.Option(
        False,
        "--all-affected",
        help="Prepare packets for the exact observations invalidated by provenance repair.",
    ),
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"), help="Review packet root."
    ),
    cache_dir: Path | None = typer.Option(
        None, help="Provenance-bound clip cache."
    ),
    open_packet: bool = typer.Option(
        True, "--open-packet/--no-open-packet", help="Open each local HTML packet."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    selection_count = sum(
        (youtube_video_id is not None, observation_fingerprint is not None, all_affected)
    )
    if selection_count != 1:
        raise typer.BadParameter(
            "Pass exactly one of --youtube-video-id, --observation-fingerprint, "
            "or --all-affected."
        )
    paths = build_paths(base_dir)
    cache_dir = cache_dir or paths.evaluation / "speaker-pairs/cache"
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    database = Database(paths.database, readonly=True)
    if observation_fingerprint is not None:
        observation = database.get_speaker_observation_by_fingerprint(
            observation_fingerprint
        )
        if observation is None:
            raise typer.BadParameter(
                f"Unknown observation fingerprint: {observation_fingerprint}"
            )
        video = database.get_video_by_id(observation.video_id)
        if video is None:
            raise typer.BadParameter(
                f"Observation video is unavailable: {observation_fingerprint}"
            )
        review_inputs = [(video, observation)]
    elif youtube_video_id is not None:
        video = database.get_video_by_youtube_id(youtube_video_id)
        if video is None:
            raise typer.BadParameter(f"Unknown YouTube video ID: {youtube_video_id}")
        observation = database.get_latest_speaker_observation_for_video(video.id)
        review_inputs = [(video, observation)]
    else:
        revocations = load_review_revocations(
            evaluation_root.expanduser().resolve()
        )
        observations = [
            database.get_speaker_observation_by_fingerprint(fingerprint)
            for fingerprint in sorted(
                revocations.affected_observation_fingerprints
            )
        ]
        review_inputs = [
            (video, observation)
            for observation in observations
            if observation is not None
            and (video := database.get_video_by_id(observation.video_id))
            is not None
        ]
    if not review_inputs:
        console.print("No provenance-invalidated observations require review.")
        return
    span_cache = AudioSpanCache(cache_dir.expanduser().resolve())
    for video, observation in review_inputs:
        try:
            artifact = get_verified_normalized_media_artifact(database, video.id)
        except ArchivedMediaUnavailableError as error:
            retry = (
                "pte identity review-observation "
                f"--youtube-video-id {video.youtube_video_id} "
                f"--base-dir {shlex.quote(str(paths.root))}"
            )
            if all_affected:
                console.print(
                    f"{video.youtube_video_id}: deferred "
                    f"(archived_media_unavailable); retry: {retry}"
                )
                continue
            raise typer.BadParameter(f"{error}. Retry: {retry}") from error
        if observation is None or artifact is None:
            console.print(
                f"{video.youtube_video_id}: skipped (observation or verified audio unavailable)"
            )
            continue
        try:
            packet = create_observation_review_packet(
                observation=observation,
                youtube_video_id=video.youtube_video_id,
                audio_path=Path(artifact.artifact_path),
                span_cache=span_cache,
                evaluation_root=evaluation_root.expanduser().resolve(),
            )
            write_canonical_clip_preparation_manifest(
                paths,
                artifact,
                observation,
                clip_paths=tuple(
                    Path(item["wav_path"]) for item in packet.payload["clips"]
                ),
            )
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            raise typer.BadParameter(
                f"{video.youtube_video_id}: {error}"
            ) from error
        console.print(
            f"{video.youtube_video_id}: window "
            f"{observation.start_seconds:.3f}-{observation.end_seconds:.3f}s; "
            f"video=https://www.youtube.com/watch?v={video.youtube_video_id}; "
            f"packet={packet.packet_path}"
        )
        if open_packet:
            webbrowser.open(packet.packet_path.resolve().as_uri())


def _speaker_pair_video_metadata(database: Any, video: Any) -> dict[str, object]:
    source_lookup = getattr(database, "get_source_by_id", None)
    source = (
        source_lookup(video.source_id)
        if callable(source_lookup) and hasattr(video, "source_id")
        else None
    )
    published_at = getattr(video, "published_at", None)
    source_type = getattr(source, "source_type", None)
    return {
        "title": getattr(video, "title", None),
        "channel": getattr(video, "channel_name", None),
        "published_at": (
            published_at.isoformat()
            if hasattr(published_at, "isoformat")
            else published_at
        ),
        "source_url": getattr(source, "url", None),
        "source_type": getattr(source_type, "value", source_type),
    }


@identity_app.command(
    "review-speaker-pair",
    help="Prepare and adjudicate an exact-span speaker-pair review.",
)
def review_speaker_pair(
    video_a: str = typer.Argument(..., help="First candidate YouTube video ID."),
    video_b: str = typer.Argument(..., help="Second candidate YouTube video ID."),
    reviewer: str | None = typer.Option(None, help="Stable human reviewer identifier."),
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"), help="Speaker-pair drafts, reviews, and fixtures root."
    ),
    cache_dir: Path | None = typer.Option(
        None, help="Ignored exact-span audio cache."
    ),
    open_packet: bool = typer.Option(
        True, "--open-packet/--no-open-packet", help="Open the local HTML review packet."
    ),
    prepare_only: bool = typer.Option(
        False, "--prepare-only", help="Create the packet without prompting for adjudication."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
    selection_manifest_json: str | None = typer.Option(None, hidden=True),
    observation_fingerprint_a: str | None = typer.Option(None, hidden=True),
    observation_fingerprint_b: str | None = typer.Option(None, hidden=True),
) -> ReviewSubmission | None:
    paths = build_paths(base_dir)
    cache_dir = cache_dir or paths.evaluation / "speaker-pairs/cache"
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    database = Database(paths.database, readonly=True)
    videos = [database.get_video_by_youtube_id(value) for value in (video_a, video_b)]
    missing = [value for value, video in zip((video_a, video_b), videos) if video is None]
    if missing:
        raise typer.BadParameter(f"Unknown YouTube video ID(s): {', '.join(missing)}")
    requested_fingerprints = (
        observation_fingerprint_a,
        observation_fingerprint_b,
    )
    if any(requested_fingerprints) and not all(requested_fingerprints):
        raise typer.BadParameter(
            "automatic review requires both selected observation fingerprints"
        )
    observations = (
        [
            database.get_speaker_observation_by_fingerprint(fingerprint)
            for fingerprint in requested_fingerprints
        ]
        if all(requested_fingerprints)
        else [
            database.get_latest_speaker_observation_for_video(video.id)
            for video in videos
        ]
    )
    if observations[0] is None or observations[1] is None:
        raise typer.BadParameter("Both videos require immutable speaker observations")
    if all(requested_fingerprints) and any(
        observation.video_id != video.id
        for observation, video in zip(observations, videos)
    ):
        raise typer.BadParameter(
            "selected observation fingerprint does not belong to its video"
        )
    try:
        verification_cache = MediaVerificationCache(cache_dir.expanduser().resolve())
        # Registered hashes may identify already-verified cached evidence without
        # opening an offline archive. Any cache miss verifies the source bytes
        # against this hash before creating new review evidence.
        registered_artifacts = [
            get_registered_normalized_media_artifact(database, video.id)
            for video in videos
        ]
        audio_paths = [
            (
                Path(artifact.artifact_path)
                if artifact is not None
                else resolve_normalized_audio_path(
                    database,
                    video.id,
                    verification_cache=verification_cache,
                )
            )
            for video, artifact in zip(videos, registered_artifacts)
        ]
        if any(path is None for path in audio_paths):
            raise typer.BadParameter("Both observations require local audio")
        selection_manifest = (
            json.loads(selection_manifest_json) if selection_manifest_json is not None else None
        )
        if selection_manifest is not None and not isinstance(selection_manifest, dict):
            raise ValueError("selection manifest must be a JSON object")
        if all(requested_fingerprints):
            selected = (
                selection_manifest.get("selected_observation_fingerprints")
                if selection_manifest is not None
                else None
            )
            if selected != {
                "a": observation_fingerprint_a,
                "b": observation_fingerprint_b,
            }:
                raise ValueError(
                    "selection manifest does not match selected observations"
                )
        draft = create_review_draft(
            observation_a=observations[0],
            observation_b=observations[1],
            video_id_a=video_a,
            video_id_b=video_b,
            audio_path_a=audio_paths[0],
            audio_path_b=audio_paths[1],
            audio_sha256_a=(
                registered_artifacts[0].content_sha256
                if registered_artifacts[0] is not None
                else None
            ),
            audio_sha256_b=(
                registered_artifacts[1].content_sha256
                if registered_artifacts[1] is not None
                else None
            ),
            span_cache=AudioSpanCache(cache_dir.expanduser().resolve()),
            evaluation_root=evaluation_root.expanduser().resolve(),
            selection_manifest=selection_manifest,
            metadata_a=_speaker_pair_video_metadata(database, videos[0]),
            metadata_b=_speaker_pair_video_metadata(database, videos[1]),
        )
    except ArchivedMediaUnavailableError as error:
        raise typer.BadParameter(
            f"{error}. Restore access to the archive mount and retry this command."
        ) from error
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        raise typer.BadParameter(str(error)) from error
    evidence_mode = ReviewEvidenceMode(
        draft.payload.get(
            "review_evidence_mode",
            ReviewEvidenceMode.AUDIO_ONLY,
        )
    )
    console.print(
        f"Prepared {evidence_mode.value} packet: {draft.packet_path}"
    )
    if open_packet:
        webbrowser.open(draft.packet_path.resolve().as_uri())
    if prepare_only:
        console.print("Draft preserved; rerun without --prepare-only to adjudicate it.")
        return None

    _normalize_review_terminal_input()

    qualification_choices = {
        "single": ObservationQualification.QUALIFIED_SINGLE_SPEAKER,
        "multiple": ObservationQualification.MULTIPLE_SPEAKERS,
        "invalid": ObservationQualification.INVALID_AUDIO,
        "cannot": ObservationQualification.CANNOT_DETERMINE,
    }
    console.print(
        "Observation classifications:\n"
        "  single   every clip contains one consistent principal speaker\n"
        "  multiple clips contain different principal speakers\n"
        "  invalid  audio is unusable or lacks reviewable speech\n"
        "  cannot   insufficient confidence to classify"
    )
    qualification_a = _prompt_review_choice(
        "Classify Observation A",
        qualification_choices,
    )
    qualification_b = _prompt_review_choice(
        "Classify Observation B",
        qualification_choices,
    )
    both_qualified = (
        qualification_a == ObservationQualification.QUALIFIED_SINGLE_SPEAKER
        and qualification_b == ObservationQualification.QUALIFIED_SINGLE_SPEAKER
    )
    if both_qualified:
        pair_judgment = _prompt_review_choice(
            "Pair judgment",
            {
                "same": PairJudgment.SAME_SPEAKER,
                "different": PairJudgment.DIFFERENT_SPEAKER,
                "cannot": PairJudgment.CANNOT_DETERMINE,
            },
        )
    else:
        pair_judgment = PairJudgment.CANNOT_DETERMINE
        console.print("At least one observation is unqualified; pair judgment is cannot_determine.")
    reviewer_value = reviewer or typer.prompt("Reviewed by").strip()
    console.print(
        "Standard variation tags (use only when known): "
        + ", ".join(STANDARD_VARIATION_TAGS)
    )
    tags_text = typer.prompt(
        "Variation tags (comma-separated, or blank when unknown)",
        default="",
        show_default=False,
    )
    notes = typer.prompt("Review notes", default="", show_default=False)
    identity_evidence_eligible = both_qualified and pair_judgment in {
        PairJudgment.SAME_SPEAKER,
        PairJudgment.DIFFERENT_SPEAKER,
    }
    approval_confirmed = False
    if identity_evidence_eligible:
        approval_confirmed = typer.confirm(
            (
                "Freeze this exact-span binary judgment as an approved "
                "acoustic fixture?"
                if evidence_mode == ReviewEvidenceMode.AUDIO_ONLY
                else (
                    "Approve this audio-plus-visual judgment as profile "
                    "identity evidence?"
                )
            ),
            default=True,
        )
    try:
        submission = submit_review(
            draft=draft.payload,
            qualification_a=qualification_a,
            qualification_b=qualification_b,
            pair_judgment=pair_judgment,
            reviewer=reviewer_value,
            reviewed_at=None,
            variation_tags=tags_text.split(","),
            notes=notes,
            approval_confirmed=approval_confirmed,
            evaluation_root=evaluation_root.expanduser().resolve(),
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"Wrote append-only review event: {submission.event_path}")
    if submission.fixture_status == "created":
        console.print(f"Created frozen fixture: {submission.fixture_path}")
    elif submission.fixture_status == "existing_consistent":
        console.print("Existing frozen fixture agrees; it was not overwritten.")
    elif submission.fixture_status == "existing_conflict_preserved":
        console.print(
            "Review conflicts with the frozen fixture; both were preserved for "
            "adjudication."
        )
    elif submission.fixture_status == "identity_only":
        console.print(
            "Approved identity evidence; no acoustic fixture was created."
        )
    else:
        console.print("Review was preserved but did not create a fixture.")
    _print_reviewed_evidence_sync_command(
        paths,
        evaluation_root.expanduser().resolve(),
    )
    return submission


def _reviewed_evidence_sync_command(
    paths: AppPaths,
    evaluation_root: Path,
) -> str:
    """Return the exact deferred command for materializing review evidence."""
    return (
        "pte identity sync-reviewed-speaker-evidence "
        f"--evaluation-root {shlex.quote(str(evaluation_root))} "
        f"--base-dir {shlex.quote(str(paths.root))}"
    )


def _print_reviewed_evidence_sync_command(
    paths: AppPaths,
    evaluation_root: Path,
) -> None:
    console.print("Review saved. Evidence was not synchronized.")
    console.print("Sync when ready by copying this command:")
    console.print(_reviewed_evidence_sync_command(paths, evaluation_root))


@identity_app.command(
    "audit-speaker-negative-windows",
    help="Read-only audit of exact observations reviewed as multiple-speaker or invalid audio.",
)
def audit_speaker_negative_windows_command(
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"), help="Speaker-pair artifact root."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Print the complete machine-readable audit."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    database = Database(paths.database, readonly=True)
    try:
        audit = audit_speaker_negative_windows(
            database, evaluation_root.expanduser().resolve()
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    if json_output:
        console.print_json(json.dumps(audit.to_dict(), sort_keys=True))
        return
    table = Table(title="Speaker-negative sermon windows")
    table.add_column("Video")
    table.add_column("Qualification")
    table.add_column("Reviewed window")
    table.add_column("Current window")
    table.add_column("State")
    table.add_column("Signals")
    for record in audit.records:
        table.add_row(
            record.youtube_video_id,
            ",".join(record.qualifications),
            _format_window(record.reviewed_start_seconds, record.reviewed_end_seconds),
            _format_optional_window(record.current_start_seconds, record.current_end_seconds),
            (
                "apply"
                if "approved_fixture_pending_apply" in record.reason_codes
                else "review"
                if record.actionable
                else "stale"
                if "stale_observation" in record.reason_codes
                else "resolved"
            ),
            ",".join(
                reason
                for reason in record.reason_codes
                if reason not in record.qualifications
            ) or "negative_qualification",
        )
    console.print(table)
    payload = audit.to_dict()["counts"]
    assert isinstance(payload, dict)
    console.print(
        "Speaker-negative window audit: "
        f"observations={payload['negative_observations']} "
        f"actionable={payload['actionable']} stale={payload['stale']} "
        f"broad_actionable={payload['broad_actionable']}."
    )


@identity_app.command(
    "review-next-speaker-negative-window",
    help="Review the next current sermon window implicated by a negative speaker qualification.",
)
def review_next_speaker_negative_window(
    reviewer: str | None = typer.Option(
        None, help="Human reviewer name or stable reviewer identifier."
    ),
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"), help="Speaker-pair artifact root."
    ),
    ground_truth_root: Path = typer.Option(
        Path("evaluation"), help="Root containing sermon drafts/ and fixtures/."
    ),
    open_video: bool = typer.Option(
        True, "--open-video/--no-open-video", help="Open the selected YouTube window."
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(f"Application database does not exist: {paths.database}")
    database = Database(paths.database, readonly=True)
    try:
        audit = audit_speaker_negative_windows(
            database, evaluation_root.expanduser().resolve()
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    if not audit.actionable:
        console.print("No current speaker-negative sermon windows require review.")
        return
    record = audit.actionable[0]
    console.print(
        f"Selected {record.youtube_video_id}: "
        f"window={_format_window(record.reviewed_start_seconds, record.reviewed_end_seconds)}; "
        f"qualification={','.join(record.qualifications)}; "
        f"signals={','.join(record.reason_codes)}."
    )
    fixture_dir = ground_truth_root.expanduser().resolve() / "fixtures"
    fixture_path = fixture_dir / f"{record.youtube_video_id}.json"
    if not _fixture_supplies_continuous_sermon_window(fixture_path):
        manifest = {
            "selection_origin": "speaker_negative_window_audit",
            "observation_fingerprint": record.observation_fingerprint,
            "qualifications": list(record.qualifications),
            "reason_codes": list(record.reason_codes),
            "reviewed_window": {
                "start_seconds": record.reviewed_start_seconds,
                "end_seconds": record.reviewed_end_seconds,
            },
        }
        if _ground_truth_reviewer is None:
            raise RuntimeError("Ground-truth review command was not configured.")
        _ground_truth_reviewer(
            youtube_video_id=record.youtube_video_id,
            reviewer=reviewer,
            evaluation_dir=ground_truth_root,
            open_video=open_video,
            base_dir=base_dir,
            selection_manifest_json=json.dumps(manifest, sort_keys=True),
        )
    if _fixture_supplies_continuous_sermon_window(fixture_path):
        console.print(
            "Apply the approved correction:\n"
            f"pte apply-fixture-correction {record.youtube_video_id} "
            f"--fixture-dir {shlex.quote(str(fixture_dir))} "
            f"--base-dir {shlex.quote(str(paths.root))}"
        )
    elif fixture_path.exists():
        console.print(
            "The approved fixture is not one continuous sermon window; "
            "automatic correction is intentionally unavailable."
        )


def _fixture_supplies_continuous_sermon_window(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("expected_outcome") == "sermon"
        and isinstance(payload.get("expected_spans"), list)
        and len(payload["expected_spans"]) == 1
        and payload.get("allowed_interruptions") == []
    )


def _format_window(start: float, end: float) -> str:
    return f"{format_timestamp(start)}–{format_timestamp(end)} ({(end - start) / 60.0:.1f}m)"


def _format_optional_window(start: float | None, end: float | None) -> str:
    if start is None or end is None or end <= start:
        return "unavailable"
    return _format_window(start, end)
