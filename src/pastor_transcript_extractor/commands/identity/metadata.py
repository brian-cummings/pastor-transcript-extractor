from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import webbrowser

import typer
from rich.console import Console
from rich.table import Table

from pastor_transcript_extractor.commands.apps import identity_app
from pastor_transcript_extractor.commands.common import get_database
from pastor_transcript_extractor.commands.identity.review import (
    _normalize_review_terminal_input,
)
from pastor_transcript_extractor.config import (
    build_llm_config,
    build_paths,
    build_tool_config,
)
from pastor_transcript_extractor.ground_truth_review import youtube_timestamp_url
from pastor_transcript_extractor.local_llm import LocalLlmError, OllamaClient
from pastor_transcript_extractor.metadata_enrichment import (
    MetadataEnrichmentResult,
    enrich_metadata,
    latest_metadata_description,
    videos_for_profile,
    videos_for_profiles,
)
from pastor_transcript_extractor.models import Video
from pastor_transcript_extractor.speaker_profile_attribution import (
    apply_reviewed_profile_attribution,
    get_profile_attribution_candidate,
    load_profile_attribution_clip_timestamps,
    load_profile_attribution_deferrals,
    list_proposed_profile_attribution_candidates,
    list_source_pastor_profile_attribution_candidates,
    list_unnamed_profile_attribution_candidates,
    record_profile_attribution_deferral,
    write_profile_attribution_packet,
)
from pastor_transcript_extractor.speaker_profile_metadata_attribution import (
    ProfileMetadataAttributionRun,
    load_profile_metadata_attributions,
    profile_metadata_candidate_profile_ids,
    run_profile_metadata_attribution,
)
from pastor_transcript_extractor.speaker_profile_metadata_attribution_typesafe import (
    DEFAULT_TYPESAFE_MODEL,
    TypeSafeSdkNameAttributionProvider,
    run_typesafe_profile_metadata_attribution,
)
from pastor_transcript_extractor.storage import Database


console = Console()


@identity_app.command(
    "review-profile-attribution",
    help="Present an unnamed profile's backing videos and record its reviewed name.",
)
def review_profile_attribution_command(
    reviewer: str = typer.Option(..., help="Stable human reviewer identifier."),
    profile_id: int | None = typer.Option(
        None,
        help="Exact canonical profile; default selects the largest unnamed profile.",
    ),
    all_proposals: bool = typer.Option(
        False,
        "--all-proposals",
        help="Review every current non-deferred metadata name proposal.",
    ),
    all_anonymous_profiles: bool = typer.Option(
        False,
        "--all-anonymous-profiles",
        help="Review every current non-deferred, reviewable anonymous profile.",
    ),
    source_pastor_candidate: bool = typer.Option(
        False,
        "--source-pastor-candidate",
        help=(
            "Review the largest unnamed single-source profile whose configured "
            "source pastor is not yet represented on that source."
        ),
    ),
    plan_only: bool = typer.Option(
        False,
        "--plan-only",
        help="Show the review queue without opening packets or writing review events.",
    ),
    representative_videos: int = typer.Option(
        6,
        min=1,
        help="Maximum backing videos shown in the review packet.",
    ),
    open_packet: bool = typer.Option(
        True,
        "--open-packet/--no-open-packet",
        help="Open the local HTML packet containing timestamped videos.",
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"),
        help="Persisted identity clip-selection cache used for timestamps.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    if sum(
        (
            profile_id is not None,
            all_proposals,
            all_anonymous_profiles,
            source_pastor_candidate,
        )
    ) > 1:
        raise typer.BadParameter(
            "Pass at most one of --profile-id, --all-proposals, or "
            "--all-anonymous-profiles, or --source-pastor-candidate."
        )
    batch_mode = all_proposals or all_anonymous_profiles
    paths = build_paths(base_dir, remember=not plan_only)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    database = (
        Database(paths.database, readonly=True)
        if plan_only
        else get_database(base_dir)
    )
    deferral_root = paths.logs / "profile-attribution-reviews" / "deferrals"
    metadata_attributions = load_profile_metadata_attributions(
        paths.logs / "profile-metadata-attribution"
    )
    clip_timestamps = load_profile_attribution_clip_timestamps(cache_dir)
    console.print(
        "Attribution timing: loaded "
        f"{len(clip_timestamps)} persisted identity clip timestamp(s)."
    )
    try:
        if profile_id is None:
            deferred = load_profile_attribution_deferrals(deferral_root)
            if all_proposals:
                candidate_source = list_proposed_profile_attribution_candidates(
                    database,
                    representative_limit=representative_videos,
                    clip_timestamps=clip_timestamps,
                    metadata_attributions=metadata_attributions,
                )
            elif source_pastor_candidate:
                candidate_source = list_source_pastor_profile_attribution_candidates(
                    database,
                    representative_limit=representative_videos,
                    clip_timestamps=clip_timestamps,
                    metadata_attributions=metadata_attributions,
                )
            else:
                candidate_source = list_unnamed_profile_attribution_candidates(
                    database,
                    representative_limit=representative_videos,
                    clip_timestamps=clip_timestamps,
                    metadata_attributions=metadata_attributions,
                )
            candidates = tuple(
                candidate
                for candidate in candidate_source
                if candidate.membership_fingerprint not in deferred
            )
            if source_pastor_candidate:
                candidates = candidates[:1]
            if not candidates:
                if all_proposals:
                    console.print(
                        "No current non-deferred metadata name proposal "
                        "requires review."
                    )
                elif source_pastor_candidate:
                    console.print(
                        "No non-deferred unnamed single-source profile has an "
                        "unrepresented configured source pastor."
                    )
                else:
                    console.print(
                        "No non-deferred unnamed profile has reviewable backing "
                        "videos. Pass --profile-id to revisit a deferred profile."
                    )
                return
        else:
            candidates = (
                get_profile_attribution_candidate(
                    database,
                    profile_id,
                    representative_limit=representative_videos,
                    clip_timestamps=clip_timestamps,
                    metadata_attributions=metadata_attributions,
                ),
            )
    except (OSError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error

    if plan_only:
        proposal_count = sum(
            candidate.metadata_attribution is not None
            and candidate.metadata_attribution.decision == "propose_name"
            for candidate in candidates
        )
        console.print(
            "Profile attribution review plan: "
            f"profiles={len(candidates)} metadata_proposals={proposal_count}; "
            "no packets opened and no review events written."
        )
        if source_pastor_candidate:
            candidate = candidates[0]
            console.print(
                "Source-pastor suggestion: "
                f"profile={candidate.profile_id} source={candidate.source_id} "
                f"pastor={candidate.source_pastor_name!r} "
                f"members={candidate.member_count}; human confirmation required."
            )
        return

    approved_count = deferred_count = cancelled_count = 0
    for queue_index, candidate in enumerate(candidates, start=1):
        console.print(
            f"Selected profile {candidate.profile_id}: "
            f"members={candidate.member_count} "
            f"queue={queue_index}/{len(candidates)}"
        )
        try:
            packet_path = write_profile_attribution_packet(
                candidate,
                paths.logs
                / "profile-attribution-reviews"
                / f"profile-{candidate.profile_id}.html",
            )
        except OSError as error:
            raise typer.BadParameter(str(error)) from error

        table = Table(title=f"Profile {candidate.profile_id} backing videos")
        table.add_column("#", justify="right")
        table.add_column("Title")
        table.add_column("Timestamped video")
        for index, evidence in enumerate(candidate.evidence, start=1):
            table.add_row(
                str(index),
                evidence.title,
                youtube_timestamp_url(
                    evidence.video_url,
                    evidence.timestamp_seconds,
                ),
            )
        console.print(table)
        console.print(f"Prepared profile attribution packet: {packet_path}")
        metadata_attribution = candidate.metadata_attribution
        suggested_name = candidate.source_pastor_name or ""
        if candidate.source_pastor_name is not None:
            console.print(
                "Source-pastor suggestion: proposed "
                f"{candidate.source_pastor_name!r} from source "
                f"{candidate.source_id}; source assignment is context only and "
                "human confirmation is required."
            )
        if metadata_attribution is not None:
            if (
                metadata_attribution.decision == "propose_name"
                and metadata_attribution.proposed_name
            ):
                if not suggested_name:
                    suggested_name = metadata_attribution.proposed_name
                console.print(
                    "Metadata attribution: proposed "
                    f"{metadata_attribution.proposed_name!r} from "
                    f"{metadata_attribution.supporting_recording_count} "
                    "recording(s); human confirmation required."
                )
            else:
                console.print(
                    "Metadata attribution: "
                    f"{metadata_attribution.decision}; routed for human review "
                    f"(reasons={','.join(metadata_attribution.reason_codes)})."
                )
        if open_packet:
            webbrowser.open(packet_path.as_uri())
        _normalize_review_terminal_input()
        name = typer.prompt(
            "Speaker name (blank or 'skip' defers this evidence set)",
            default=suggested_name,
            show_default=bool(suggested_name),
        ).strip()
        if not name or name.casefold() in {"s", "skip", "cannot"}:
            try:
                deferral_path = record_profile_attribution_deferral(
                    candidate,
                    reviewer=reviewer,
                    root=deferral_root,
                )
            except (OSError, ValueError) as error:
                raise typer.BadParameter(str(error)) from error
            console.print(
                "Attribution deferred for this exact profile membership; "
                f"event={deferral_path}"
            )
            deferred_count += 1
            if profile_id is not None:
                return
            continue
        evidence_number = typer.prompt(
            "Backing video number",
            default=1,
            type=int,
        )
        if evidence_number < 1 or evidence_number > len(candidate.evidence):
            raise typer.BadParameter("backing video number is outside the packet")
        evidence = candidate.evidence[evidence_number - 1]
        reason = typer.prompt(
            "Evidence/reason",
            default=(
                "Visually identified in backing video "
                f"{evidence.youtube_video_id} at "
                f"{evidence.timestamp_seconds} seconds"
            ),
        ).strip()
        if not typer.confirm(
            f"Attach {name!r} to profile {candidate.profile_id}?",
            default=all_proposals and bool(suggested_name),
        ):
            console.print("Attribution cancelled; no registry mutation occurred.")
            cancelled_count += 1
            if batch_mode:
                continue
            return
        try:
            result = apply_reviewed_profile_attribution(
                database,
                profile_id=candidate.profile_id,
                observation_id=evidence.observation_id,
                display_name=name,
                reviewer=reviewer,
                reason=reason,
                packet_path=packet_path,
            )
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error
        console.print(
            f"Attributed profile {candidate.profile_id}: "
            f"name={result.normalized_name} claim={result.claim_id} "
            f"link_status={result.link_status}"
        )
        if result.linked_pastor_slug is not None:
            console.print(
                f"Linked configured pastor: {result.linked_pastor_slug}"
            )
        approved_count += 1
        if not batch_mode:
            return

    if batch_mode:
        summary_label = (
            "Metadata proposal review complete"
            if all_proposals
            else "Anonymous profile review complete"
        )
        console.print(
            f"{summary_label}: "
            f"approved={approved_count} deferred={deferred_count} "
            f"cancelled={cancelled_count}."
        )
    else:
        console.print("All currently reviewable unnamed profiles were deferred.")


@identity_app.command(
    "enrich-metadata",
    help=(
        "Fetch full yt-dlp metadata only when a video's latest snapshot has no description."
    ),
)
def enrich_metadata_command(
    video_id: int | None = typer.Option(
        None,
        "--video-id",
        help="Enrich one video by numeric database id.",
    ),
    profile_id: int | None = typer.Option(
        None,
        "--profile-id",
        help="Enrich videos attached to one speaker profile.",
    ),
    all_anonymous_profiles: bool = typer.Option(
        False,
        "--all-anonymous-profiles",
        help="Enrich all current canonical anonymous profiles.",
    ),
    plan_only: bool = typer.Option(
        False,
        "--plan-only",
        help="Show the selected and eligible counts without network requests or writes.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    selector_count = sum(
        (video_id is not None, profile_id is not None, all_anonymous_profiles)
    )
    if selector_count != 1:
        raise typer.BadParameter(
            "Pass exactly one of --video-id, --profile-id, or "
            "--all-anonymous-profiles."
        )
    paths = build_paths(base_dir, remember=not plan_only)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    database = Database(paths.database, readonly=plan_only)
    selected_profile_count = 0
    if video_id is not None:
        video = database.get_video_by_id(video_id)
        if video is None:
            raise typer.BadParameter(f"Video does not exist: {video_id}")
        videos = (video,)
    elif profile_id is not None:
        try:
            videos = videos_for_profile(database, profile_id)
        except ValueError as error:
            raise typer.BadParameter(str(error)) from error
        selected_profile_count = 1
    else:
        anonymous_profile_ids = profile_metadata_candidate_profile_ids(database)
        videos = videos_for_profiles(database, anonymous_profile_ids)
        selected_profile_count = len(anonymous_profile_ids)

    if plan_only:
        already_complete = sum(
            latest_metadata_description(database, video) is not None
            for video in videos
        )
        console.print(
            "Metadata enrichment plan: "
            f"profiles={selected_profile_count} videos={len(videos)} "
            f"eligible={len(videos) - already_complete} "
            f"already_complete={already_complete}; "
            "no network requests or writes."
        )
        return

    tools = build_tool_config()

    def report_progress(
        index: int,
        total: int,
        video: Video,
        outcome: str,
        detail: str | None,
    ) -> None:
        message = (
            f"Metadata enrichment [{index}/{total}] video #{video.id} "
            f"({video.youtube_video_id}): {outcome.replace('_', ' ')}"
        )
        if detail:
            message += f" — {detail}"
        console.print(message, markup=False)

    result: MetadataEnrichmentResult = enrich_metadata(
        database,
        paths,
        videos,
        yt_dlp_bin=tools.yt_dlp_bin,
        yt_dlp_js_runtimes=tools.yt_dlp_js_runtimes,
        progress_callback=report_progress,
    )
    console.print(
        "Metadata enrichment complete: "
        f"eligible={result.eligible} enriched={result.enriched} "
        f"already_complete={result.already_complete} "
        f"unavailable={result.unavailable} failed={result.failed}."
    )


@identity_app.command(
    "analyze-profile-metadata",
    help=(
        "Run cached, grounded metadata-name attribution for unnamed profiles."
    ),
)
def analyze_profile_metadata_command(
    all_profiles: bool = typer.Option(
        False,
        "--all",
        "--all-anonymous-profiles",
        help="Analyze every current unnamed canonical profile.",
    ),
    profile_id: int | None = typer.Option(
        None,
        "--profile-id",
        help="Analyze one exact canonical profile.",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Override the selected backend's model.",
    ),
    backend: str = typer.Option(
        "ollama",
        "--backend",
        help="Attribution backend: ollama or typesafe.",
    ),
    details: bool = typer.Option(
        False,
        "--details",
        help="Show names, evidence excerpts, failures, and artifact paths.",
    ),
    plan_only: bool = typer.Option(
        False,
        "--plan-only",
        help="Show eligible profiles without model calls or artifact writes.",
    ),
    base_dir: Path | None = typer.Option(
        None,
        help="Override app data directory.",
    ),
) -> None:
    backend = backend.strip().lower()
    if backend not in {"ollama", "typesafe"}:
        raise typer.BadParameter("--backend must be ollama or typesafe")
    if all_profiles == (profile_id is not None):
        raise typer.BadParameter(
            "Pass exactly one of --all-anonymous-profiles (or --all) or "
            "--profile-id."
        )
    paths = build_paths(base_dir, remember=not plan_only)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    database = Database(paths.database, readonly=True)
    selected_ids = (
        None if all_profiles else frozenset((int(profile_id),))
    )
    candidate_ids = profile_metadata_candidate_profile_ids(
        database,
        profile_ids=selected_ids,
    )
    if not candidate_ids:
        console.print("Profile metadata attribution: eligible=0; no model calls.")
        return
    if plan_only:
        no_calls = (
            "no Ollama calls or artifact writes"
            if backend == "ollama"
            else "no TypeSafe calls or artifact writes"
        )
        console.print(
            "Profile metadata attribution plan: "
            f"backend={backend} eligible={len(candidate_ids)}; "
            f"{no_calls}."
        )
        return
    try:
        progress = (
            lambda index, total, current_profile_id, outcome: console.print(
                "Profile metadata attribution "
                f"[{index}/{total}] profile={current_profile_id}: {outcome}"
            )
        )
        if backend == "typesafe":
            provider = TypeSafeSdkNameAttributionProvider(
                model=model or DEFAULT_TYPESAFE_MODEL
            )
            result = run_typesafe_profile_metadata_attribution(
                database,
                paths.logs / "profile-metadata-attribution",
                provider,
                profile_ids=frozenset(candidate_ids),
                progress_callback=progress,
            )
        else:
            config = build_llm_config()
            if model is not None:
                config = replace(config, model=model)
            if not config.enabled:
                raise typer.BadParameter("Local LLM is disabled by PTE_LLM_ENABLED.")
            client = OllamaClient(config)
            result = run_profile_metadata_attribution(
                database,
                paths.logs / "profile-metadata-attribution",
                client,
                model_digest=client.model_digest(),
                profile_ids=frozenset(candidate_ids),
                progress_callback=progress,
            )
    except (LocalLlmError, OSError, RuntimeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        "Profile metadata attribution complete: "
        f"eligible={result.eligible} proposed={result.proposed} "
        f"insufficient_evidence={result.insufficient_evidence} "
        f"conflicting_evidence={result.conflicting_evidence} "
        f"invalid_metadata={result.invalid_metadata} "
        f"abstentions={result.abstentions} cache_hits={result.cache_hits} "
        f"cache_misses={result.cache_misses} model_calls={result.model_calls} "
        f"failed={result.failed}."
    )
    _print_profile_metadata_proposals(result)
    if details:
        _print_profile_metadata_details(result)


def _print_profile_metadata_proposals(
    result: ProfileMetadataAttributionRun,
) -> None:
    proposals = tuple(
        item for item in result.results if item.decision == "propose_name"
    )
    if not proposals:
        return
    console.print("[bold]Metadata name proposals[/bold]")
    for item in proposals:
        console.print(
            f"  profile={item.profile_id} name={item.proposed_name!r} "
            f"recordings={item.supporting_recording_count} "
            f"cache_hit={item.cache_hit} artifact={item.artifact_path}",
            markup=False,
        )


def _print_profile_metadata_details(
    result: ProfileMetadataAttributionRun,
) -> None:
    console.print("[bold]Metadata attribution details[/bold]")
    for item in result.results:
        console.print(
            f"  profile={item.profile_id} decision={item.decision} "
            f"routing={item.routing} name={item.proposed_name!r} "
            f"recordings={item.supporting_recording_count} "
            f"cache_hit={item.cache_hit}",
            markup=False,
        )
        console.print(
            f"    reasons={','.join(item.reason_codes)} "
            f"conflicts={','.join(item.conflicting_names) or 'none'}",
            markup=False,
        )
        for evidence in item.evidence:
            console.print(
                f"    evidence={evidence.youtube_video_id}:"
                f"{evidence.field_path} {evidence.exact_excerpt!r}",
                markup=False,
            )
        console.print(f"    artifact={item.artifact_path}", markup=False)
        diagnostic_path = item.artifact_path.with_suffix(".attempt.json")
        if diagnostic_path.is_file():
            console.print(
                f"    diagnostic_artifact={diagnostic_path}",
                markup=False,
            )
    for failure in result.failures:
        console.print(
            f"  profile={failure.profile_id} decision=failed "
            f"cache_hit={failure.cache_hit} "
            f"error={failure.error_type}: {failure.error_message}",
            markup=False,
        )
        console.print(
            f"    diagnostic_artifact={failure.artifact_path}",
            markup=False,
        )
