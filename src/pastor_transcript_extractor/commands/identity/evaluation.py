from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import typer
from rich.console import Console

from pastor_transcript_extractor.commands.apps import identity_app
from pastor_transcript_extractor.config import build_paths
from pastor_transcript_extractor.media_artifacts import resolve_normalized_audio_path
from pastor_transcript_extractor.speaker_model_bakeoff import (
    BakeoffModel,
    build_bakeoff_preflight,
    evaluate_experimental_policy_candidate,
    execute_bakeoff_plan,
    load_bakeoff_manifest,
    load_experimental_policy_candidate,
    load_namespaced_bakeoff_results,
)
from pastor_transcript_extractor.speaker_observation_consistency import (
    build_observation_consistency_plan,
    collect_reviewed_observation_examples,
    evaluate_observation_consistency_examples,
    write_observation_consistency_report,
)
from pastor_transcript_extractor.speaker_pair_diagnostics import (
    AudioSpanCache,
    DecisionPolicy,
    EmbeddingCache,
    SherpaOnnxEmbeddingBackend,
    SpanSpec,
    analyze_observation_pair,
    evaluate_reviewed_pair_results,
    validate_reviewed_pair_fixture,
    write_pair_result,
)
from pastor_transcript_extractor.speaker_pair_review import (
    audit_review_selection_artifacts,
)
from pastor_transcript_extractor.speaker_review_invalidation import (
    evaluation_root_for_pair_artifact,
    filter_active_pair_artifacts,
    load_review_revocations,
    pair_artifact_is_revoked,
)
from pastor_transcript_extractor.storage import Database


DEFAULT_SPEAKER_MODEL_SHA256 = (
    "357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b"
)
console = Console()


def _load_json_artifacts(paths: Sequence[Path]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{path}: expected a JSON object")
        payloads.append(payload)
    roots = {
        root
        for path in paths
        if (root := evaluation_root_for_pair_artifact(path)) is not None
    }
    for root in roots:
        payloads = filter_active_pair_artifacts(
            payloads,
            load_review_revocations(root),
        )
    return payloads


@identity_app.command(
    "compare-speakers",
    help="Run a read-only, abstention-first acoustic comparison of two speaker observations.",
)
def compare_speakers(
    video_a: str = typer.Argument(..., help="First YouTube video ID."),
    video_b: str = typer.Argument(..., help="Second YouTube video ID."),
    model_path: Path = typer.Option(
        Path("evaluation/speaker-pairs/models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"),
        help="Local ONNX speaker-embedding model.",
    ),
    model_sha256: str = typer.Option(
        DEFAULT_SPEAKER_MODEL_SHA256,
        help="Required checksum for the local model.",
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"),
        help="Ignored cache for exact WAV spans and embeddings.",
    ),
    output_path: Path | None = typer.Option(
        None, help="Result JSON path; defaults to the ignored speaker-pair run directory."
    ),
    policy_path: Path | None = typer.Option(
        None,
        help="Explicitly approved decision policy; without one the comparison always abstains.",
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    database = Database(paths.database, readonly=True)
    videos = [database.get_video_by_youtube_id(value) for value in (video_a, video_b)]
    missing = [value for value, video in zip((video_a, video_b), videos) if video is None]
    if missing:
        raise typer.BadParameter(f"Unknown YouTube video ID(s): {', '.join(missing)}")
    observations = [database.get_latest_speaker_observation_for_video(video.id) for video in videos]
    audio_paths = [resolve_normalized_audio_path(database, video.id) for video in videos]
    try:
        backend = SherpaOnnxEmbeddingBackend(
            model_path.expanduser().resolve(), expected_sha256=model_sha256
        )
        policy = (
            DecisionPolicy.from_path(policy_path.expanduser().resolve())
            if policy_path
            else None
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    cache_root = cache_dir.expanduser().resolve()
    result = analyze_observation_pair(
        observation_a=observations[0],
        observation_b=observations[1],
        audio_path_a=audio_paths[0],
        audio_path_b=audio_paths[1],
        span_cache=AudioSpanCache(cache_root),
        embedding_cache=EmbeddingCache(cache_root),
        backend=backend,
        policy=policy,
    )
    result["videos"] = {"a": video_a, "b": video_b}
    destination = (
        output_path.expanduser().resolve()
        if output_path
        else Path("evaluation/speaker-pairs/runs").resolve() / f"{video_a}--{video_b}.json"
    )
    write_pair_result(destination, result)
    console.print(f"{result['outcome']}: {result['reason']}")
    console.print(f"Wrote deterministic diagnostic evidence to {destination}")


@identity_app.command(
    "evaluate-observation-consistency",
    help=(
        "Plan or run threshold-free within-observation acoustic calibration "
        "against human qualification labels."
    ),
)
def evaluate_observation_consistency(
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"),
        help="Speaker-pair drafts and review events root.",
    ),
    model_path: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/models/"
            "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
        ),
        help="Local ONNX speaker-embedding model.",
    ),
    model_sha256: str = typer.Option(
        DEFAULT_SPEAKER_MODEL_SHA256,
        help="Required checksum for the local model.",
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"),
        help="Ignored embedding cache.",
    ),
    output_path: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/runs/"
            "observation-consistency-v1.json"
        ),
        help="Threshold-free calibration report.",
    ),
    execute: bool = typer.Option(
        False,
        "--execute",
        help="Run acoustic embeddings; without this flag only print the plan.",
    ),
) -> None:
    root = evaluation_root.expanduser().resolve()
    drafts = _load_json_artifacts(sorted((root / "drafts").glob("*.json")))
    reviews = _load_json_artifacts(
        sorted((root / "reviews").glob("*/*.json"))
    )
    examples, conflicts = collect_reviewed_observation_examples(
        drafts=drafts,
        reviews=reviews,
    )
    plan = build_observation_consistency_plan(
        examples=examples,
        conflicts=conflicts,
    )
    counts = plan["qualification_counts"]
    console.print(
        "Observation consistency calibration: "
        f"examples={plan['reviewed_example_count']} "
        f"single={counts['qualified_single_speaker']} "
        f"multiple={counts['multiple_speakers']} "
        f"invalid={counts['invalid_audio']} "
        f"conflicts={plan['conflict_count']}"
    )
    if not execute:
        console.print(
            "Plan only; no embeddings or report artifacts were created."
        )
        return
    try:
        backend = SherpaOnnxEmbeddingBackend(
            model_path.expanduser().resolve(),
            expected_sha256=model_sha256,
        )
        report = evaluate_observation_consistency_examples(
            examples=examples,
            conflicts=conflicts,
            embedding_cache=EmbeddingCache(
                cache_dir.expanduser().resolve()
            ),
            backend=backend,
        )
        destination = output_path.expanduser().resolve()
        write_observation_consistency_report(destination, report)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        f"Scored {report['scored_case_count']} reviewed observation(s)."
    )
    console.print(
        "Threshold-free only; automatic qualification and registry mutation "
        "remain disabled."
    )
    console.print(f"Wrote observation consistency report to {destination}")


@identity_app.command(
    "run-speaker-model-bakeoff",
    help="Preflight and execute the resumable exact-span speaker-model bake-off.",
)
def run_speaker_model_bakeoff(
    fixture_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/fixtures"),
        help="Approved exact-span speaker-pair fixtures.",
    ),
    manifest_path: Path = typer.Option(
        Path("evaluation/speaker-pairs/bakeoff-models.json"),
        help="Experimental candidate model manifest.",
    ),
    result_root: Path = typer.Option(
        Path("evaluation/speaker-pairs/runs/by-model"),
        help="Model-fingerprint-qualified deterministic result root.",
    ),
    cache_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/cache"),
        help="Ignored exact-span and embedding cache.",
    ),
    preflight_path: Path = typer.Option(
        Path("evaluation/speaker-pairs/reports/bakeoff-preflight.json"),
        help="Persisted preflight and execution plan.",
    ),
    report_path: Path = typer.Option(
        Path("evaluation/speaker-pairs/reports/bakeoff-latest.json"),
        help="Threshold-free model comparison report.",
    ),
    preflight_only: bool = typer.Option(
        False,
        "--preflight-only",
        help="Validate and persist the plan without running acoustic models.",
    ),
    evaluation_scope: str = typer.Option(
        "development",
        "--evaluation-scope",
        help=(
            "Fixture partition to execute: development, validation, held_out, or all. "
            "Development also includes legacy unassigned fixtures."
        ),
    ),
    base_dir: Path | None = typer.Option(None, help="Override app data directory."),
) -> None:
    repository_root = Path.cwd().resolve()
    fixture_root = fixture_dir.expanduser().resolve()
    manifest = manifest_path.expanduser().resolve()
    results_destination = result_root.expanduser().resolve()
    try:
        fixture_paths = sorted(fixture_root.glob("*.json"))
        if not fixture_paths:
            raise ValueError(f"no reviewed pair fixtures found in {fixture_root}")
        all_fixtures = _load_json_artifacts(fixture_paths)
        fixtures = _select_bakeoff_fixtures(all_fixtures, evaluation_scope)
        models = load_bakeoff_manifest(manifest)
        preflight = build_bakeoff_preflight(
            fixtures,
            models,
            repository_root=repository_root,
            result_root=results_destination,
        )
        preflight["fixture_scope"] = {
            "requested": evaluation_scope,
            "selected_fixture_count": len(fixtures),
            "corpus_fixture_count": len(all_fixtures),
            "legacy_unassigned_included": evaluation_scope == "development",
        }
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error

    preflight_destination = preflight_path.expanduser().resolve()
    preflight_destination.parent.mkdir(parents=True, exist_ok=True)
    preflight_destination.write_text(
        json.dumps(preflight, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    console.print(
        f"Preflight: fixtures={len(fixtures)}/{len(all_fixtures)} "
        f"scope={evaluation_scope} models={len(models)} "
        f"jobs={len(preflight['plan']['jobs'])}; "
        f"report={preflight_destination}"
    )
    if not preflight["execution_allowed"]:
        raise typer.BadParameter(
            "bake-off preflight blocked execution: "
            + ", ".join(preflight["blocking_reasons"])
        )
    if preflight_only:
        console.print("Preflight passed; acoustic execution was not requested.")
        return

    paths = build_paths(base_dir)
    if not paths.database.exists():
        raise typer.BadParameter(
            f"Application database does not exist: {paths.database}"
        )
    database = Database(paths.database, readonly=True)
    backends: dict[str, SherpaOnnxEmbeddingBackend] = {}
    try:
        for model in models:
            _validate_bakeoff_preprocessing(model, fixtures)
            model_file = Path(model.model_path)
            if not model_file.is_absolute():
                model_file = repository_root / model_file
            backend = SherpaOnnxEmbeddingBackend(
                model_file,
                expected_sha256=model.model_sha256,
            )
            _validate_bakeoff_backend(model, backend)
            backends[model.stable_key] = backend
    except (OSError, RuntimeError, ValueError) as error:
        raise typer.BadParameter(f"bake-off backend preflight failed: {error}") from error

    span_cache = AudioSpanCache(cache_dir.expanduser().resolve())
    embedding_cache = EmbeddingCache(cache_dir.expanduser().resolve())

    def analyze_fixture(
        fixture: dict[str, object],
        model: BakeoffModel,
    ) -> dict[str, object]:
        observations = [
            database.get_speaker_observation_by_fingerprint(
                str(fixture["observations"][side]["input_fingerprint"])
            )
            for side in ("a", "b")
        ]
        audio_paths = [
            (
                resolve_normalized_audio_path(database, observation.video_id)
                if observation is not None
                else None
            )
            for observation in observations
        ]
        span_specs = [
            [
                SpanSpec(
                    float(span["start_seconds"]),
                    float(span["end_seconds"]),
                )
                for span in fixture["observations"][side]["reviewed_spans"]
            ]
            for side in ("a", "b")
        ]
        result = analyze_observation_pair(
            observation_a=observations[0],
            observation_b=observations[1],
            audio_path_a=audio_paths[0],
            audio_path_b=audio_paths[1],
            span_cache=span_cache,
            embedding_cache=embedding_cache,
            backend=backends[model.stable_key],
            policy=None,
            span_specs_a=span_specs[0],
            span_specs_b=span_specs[1],
        )
        # Even a technical failure must remain tied to the exact intended
        # reviewed evidence so it is reported as analysis_failed, not missing.
        result.setdefault(
            "observations",
            {
                side: fixture["observations"][side]["input_fingerprint"]
                for side in ("a", "b")
            },
        )
        result.setdefault(
            "spans",
            {
                side: list(fixture["observations"][side]["reviewed_spans"])
                for side in ("a", "b")
            },
        )
        return result

    def show_progress(index: int, total: int, model_key: str, pair_id: str) -> None:
        console.print(f"[{index}/{total}] {model_key}: {pair_id}")

    try:
        execution = execute_bakeoff_plan(
            fixtures,
            models,
            plan=preflight["plan"],
            analyze_fixture=analyze_fixture,
            progress=show_progress,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    destination = report_path.expanduser().resolve()
    execution["report"]["fixture_scope"] = preflight["fixture_scope"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(execution["report"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    console.print(
        f"Bake-off complete: new={execution['jobs_completed']} "
        f"replayed={execution['jobs_replayed']}; report={destination}"
    )


@identity_app.command(
    "evaluate-speaker-policy-candidate",
    help="Replay a non-approved policy on development bake-off metrics only.",
)
def evaluate_speaker_policy_candidate(
    policy_path: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/policies/"
            "campplus-development-candidate-v1.json"
        ),
        help="Development-derived experimental policy candidate.",
    ),
    fixture_dir: Path = typer.Option(
        Path("evaluation/speaker-pairs/fixtures"),
        help="Approved exact-span speaker-pair fixtures.",
    ),
    manifest_path: Path = typer.Option(
        Path("evaluation/speaker-pairs/bakeoff-models.json"),
        help="Experimental candidate model manifest.",
    ),
    result_root: Path = typer.Option(
        Path("evaluation/speaker-pairs/runs/by-model"),
        help="Existing model-fingerprint-qualified bake-off results.",
    ),
    report_path: Path = typer.Option(
        Path(
            "evaluation/speaker-pairs/reports/"
            "campplus-development-candidate-v1.json"
        ),
        help="Development-only experimental policy report.",
    ),
) -> None:
    try:
        fixture_paths = sorted(fixture_dir.expanduser().resolve().glob("*.json"))
        all_fixtures = _load_json_artifacts(fixture_paths)
        fixtures = _select_bakeoff_fixtures(all_fixtures, "development")
        models = load_bakeoff_manifest(manifest_path.expanduser().resolve())
        candidate, model = load_experimental_policy_candidate(
            policy_path.expanduser().resolve(),
            fixtures=fixtures,
            models=models,
        )
        results = load_namespaced_bakeoff_results(
            result_root.expanduser().resolve(),
            model,
            pair_ids=[str(fixture["pair_id"]) for fixture in fixtures],
        )
        report = evaluate_experimental_policy_candidate(
            fixtures,
            results,
            candidate,
            model,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    destination = report_path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    counts = report["evaluation"]["counts"]
    console.print(
        f"Development replay: true_same={counts['true_same']} "
        f"true_different={counts['true_different']} "
        f"false_same={counts['false_same']} "
        f"false_different={counts['false_different']} "
        f"abstained={counts['insufficient_evidence']} "
        f"failed={counts['analysis_failed']}; report={destination}"
    )
    console.print("Policy remains experimental, non-gating, and unapproved.")


def _select_bakeoff_fixtures(
    fixtures: Sequence[dict[str, object]],
    evaluation_scope: str,
) -> list[dict[str, object]]:
    allowed = {"development", "validation", "held_out", "all"}
    if evaluation_scope not in allowed:
        raise ValueError(
            "evaluation scope must be one of: development, validation, held_out, all"
        )
    if evaluation_scope == "all":
        selected = list(fixtures)
    elif evaluation_scope == "development":
        selected = [
            fixture
            for fixture in fixtures
            if fixture.get("evaluation_partition") in {None, "development"}
        ]
    else:
        selected = [
            fixture
            for fixture in fixtures
            if fixture.get("evaluation_partition") == evaluation_scope
        ]
    if not selected:
        raise ValueError(f"no fixtures are assigned to evaluation scope {evaluation_scope}")
    return selected


def _validate_bakeoff_backend(
    model: BakeoffModel,
    backend: SherpaOnnxEmbeddingBackend,
) -> None:
    if (
        backend.spec.backend != model.backend
        or backend.spec.model_name != model.model_name
        or backend.spec.model_sha256 != model.model_sha256
        or backend.spec.runtime_version != model.runtime_version
    ):
        raise ValueError(
            f"{model.stable_key} backend does not match its manifest execution"
        )


def _validate_bakeoff_preprocessing(
    model: BakeoffModel,
    fixtures: Sequence[dict[str, object]],
) -> None:
    supported = {
        "sample_rate_hz": 16_000,
        "channels": 1,
        "sample_format": "pcm_s16le",
        "span_extractor_version": "speaker_span_v1",
    }
    for key, expected in supported.items():
        if model.preprocessing.get(key) != expected:
            raise ValueError(
                f"{model.stable_key} uses unsupported {key}: "
                f"{model.preprocessing.get(key)!r}"
            )
    duration = model.preprocessing.get("span_duration_seconds")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise ValueError(f"{model.stable_key} requires a positive span duration")
    for fixture in fixtures:
        for side in ("a", "b"):
            for span in fixture["observations"][side]["reviewed_spans"]:
                actual = float(span["end_seconds"]) - float(span["start_seconds"])
                if abs(actual - float(duration)) > 0.001:
                    raise ValueError(
                        f"{fixture['pair_id']} reviewed span duration does not match "
                        f"{model.stable_key} preprocessing"
                    )


@identity_app.command(
    "validate-pair-fixtures",
    help="Validate explicitly reviewed same/different-speaker evaluation fixtures.",
)
def validate_pair_fixtures(
    fixture_dir: Path = typer.Argument(Path("evaluation/speaker-pairs/fixtures")),
) -> None:
    root = fixture_dir.expanduser().resolve()
    paths = sorted(root.glob("*.json"))
    if not paths:
        raise typer.BadParameter(f"No speaker-pair fixtures found in {root}")
    pair_ids: set[str] = set()
    revocations = load_review_revocations(root.parent)
    validated_count = 0
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if pair_artifact_is_revoked(payload, revocations):
                continue
            validate_reviewed_pair_fixture(payload)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise typer.BadParameter(f"{path}: {error}") from error
        pair_id = str(payload.get("pair_id", ""))
        if not pair_id or pair_id in pair_ids:
            raise typer.BadParameter(f"{path}: pair_id must be present and unique")
        pair_ids.add(pair_id)
        validated_count += 1
    console.print(f"Validated {validated_count} active reviewed speaker-pair fixture(s).")


@identity_app.command(
    "audit-speaker-review-selection",
    help="Verify automatic review drafts used the exact observations selected.",
)
def audit_speaker_review_selection(
    evaluation_root: Path = typer.Option(
        Path("evaluation/speaker-pairs"),
        help="Speaker-pair drafts and review events root.",
    ),
) -> None:
    try:
        audit = audit_review_selection_artifacts(evaluation_root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    console.print(
        "Speaker review selection audit: "
        f"drafts={audit.draft_count} automatic={audit.automatic_count} "
        f"reviewed={audit.reviewed_count} exact={audit.exact_verified_count} "
        f"legacy_checked={audit.legacy_checked_count} "
        f"unverifiable={audit.unverifiable_count} "
        f"mismatches={len(audit.issues)}"
    )
    for issue in audit.issues:
        console.print(
            f"Mismatch {issue.pair_id}: reason={issue.reason_code} "
            f"reviewed={issue.reviewed} draft={issue.draft_path}"
        )
    console.print("Audit is read-only; no review evidence was changed.")


@identity_app.command(
    "evaluate-pair-results",
    help="Measure pairwise errors and abstention against exact reviewed audio spans.",
)
def evaluate_pair_results(
    fixture_dir: Path = typer.Option(Path("evaluation/speaker-pairs/fixtures")),
    result_dir: Path = typer.Option(Path("evaluation/speaker-pairs/runs")),
    output_path: Path = typer.Option(Path("evaluation/speaker-pairs/reports/latest.json")),
) -> None:
    try:
        fixture_paths = sorted(fixture_dir.expanduser().resolve().glob("*.json"))
        result_paths = sorted(result_dir.expanduser().resolve().glob("*.json"))
        fixtures = _load_json_artifacts(fixture_paths)
        results = [json.loads(path.read_text(encoding="utf-8")) for path in result_paths]
        if not fixtures:
            raise ValueError("no reviewed pair fixtures found")
        report = evaluate_reviewed_pair_results(fixtures, results)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise typer.BadParameter(str(error)) from error
    destination = output_path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    counts = report["counts"]
    console.print(
        f"false_same={counts['false_same']} false_different={counts['false_different']} "
        f"abstained={counts['insufficient_evidence']} failed={counts['analysis_failed']}"
    )
    console.print(f"promotion_ready={report['gates']['promotion_ready']}; report={destination}")
