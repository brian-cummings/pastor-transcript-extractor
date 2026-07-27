from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import statistics
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.speaker_pair_diagnostics import (
    evaluate_reviewed_pair_results,
    validate_reviewed_pair_fixture,
)


BAKEOFF_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_STABLE_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class BakeoffModel:
    """A reviewed candidate definition, not an approved recognition model."""

    stable_key: str
    backend: str
    model_path: str
    model_sha256: str
    runtime_package: str
    runtime_version: str
    source_url: str
    license_name: str
    license_url: str
    preprocessing: Mapping[str, Any]

    @property
    def model_name(self) -> str:
        return Path(self.model_path).name

    @property
    def execution_fingerprint(self) -> str:
        """Fingerprint every input capable of changing acoustic output."""
        return _sha256_json(
            {
                "backend": self.backend,
                "model_name": self.model_name,
                "model_sha256": self.model_sha256,
                "runtime": {
                    "package": self.runtime_package,
                    "version": self.runtime_version,
                },
                "preprocessing": self.preprocessing,
            }
        )

    @property
    def result_namespace(self) -> str:
        return f"{self.stable_key}--{self.execution_fingerprint[:16]}"

    def matches_result(self, result: Mapping[str, Any]) -> bool:
        model = result.get("model")
        execution = result.get("bakeoff_execution")
        return (
            isinstance(model, Mapping)
            and isinstance(execution, Mapping)
            and execution.get("execution_fingerprint") == self.execution_fingerprint
            and execution.get("stable_key") == self.stable_key
            and all(
                (
                    model.get("backend") == self.backend,
                    model.get("model_name") == self.model_name,
                    model.get("model_sha256") == self.model_sha256,
                    model.get("runtime_version") == self.runtime_version,
                )
            )
        )


def load_bakeoff_manifest(path: Path) -> tuple[BakeoffModel, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != BAKEOFF_SCHEMA_VERSION:
        raise ValueError("unsupported speaker model bake-off manifest schema")
    if payload.get("selection_status") != "experimental_candidates":
        raise ValueError("bake-off manifest must not imply that a model is approved")
    entries = payload.get("models")
    if not isinstance(entries, list) or not entries:
        raise ValueError("bake-off manifest requires at least one model")

    models: list[BakeoffModel] = []
    keys: set[str] = set()
    execution_fingerprints: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("every model manifest entry must be an object")
        stable_key = entry.get("stable_key")
        if not isinstance(stable_key, str) or not _STABLE_KEY_PATTERN.fullmatch(stable_key):
            raise ValueError("model stable_key must be filesystem-safe")
        if stable_key in keys:
            raise ValueError(f"duplicate model stable_key: {stable_key}")
        checksum = entry.get("model_sha256")
        if not isinstance(checksum, str) or not _SHA256_PATTERN.fullmatch(checksum):
            raise ValueError(f"model {stable_key} requires a lowercase SHA-256 checksum")
        runtime = entry.get("runtime")
        source = entry.get("source")
        license_payload = entry.get("license")
        preprocessing = entry.get("preprocessing")
        if not isinstance(runtime, dict) or not runtime.get("package") or not runtime.get("version"):
            raise ValueError(f"model {stable_key} requires an exact runtime package and version")
        if not isinstance(source, dict) or not _is_https_url(source.get("url")):
            raise ValueError(f"model {stable_key} requires an HTTPS source URL")
        if (
            not isinstance(license_payload, dict)
            or not license_payload.get("verified")
            or not license_payload.get("name")
            or not _is_https_url(license_payload.get("url"))
        ):
            raise ValueError(f"model {stable_key} requires a verified license and HTTPS URL")
        if not isinstance(preprocessing, dict) or not preprocessing:
            raise ValueError(f"model {stable_key} requires explicit preprocessing")
        model_path = entry.get("model_path")
        backend = entry.get("backend")
        if not isinstance(model_path, str) or not Path(model_path).name:
            raise ValueError(f"model {stable_key} requires a model_path")
        if not isinstance(backend, str) or not backend:
            raise ValueError(f"model {stable_key} requires a backend")

        model = BakeoffModel(
            stable_key=stable_key,
            backend=backend,
            model_path=model_path,
            model_sha256=checksum,
            runtime_package=str(runtime["package"]),
            runtime_version=str(runtime["version"]),
            source_url=str(source["url"]),
            license_name=str(license_payload["name"]),
            license_url=str(license_payload["url"]),
            preprocessing=preprocessing,
        )
        if model.execution_fingerprint in execution_fingerprints:
            raise ValueError("multiple model entries describe the same acoustic execution")
        keys.add(stable_key)
        execution_fingerprints.add(model.execution_fingerprint)
        models.append(model)
    return tuple(models)


def build_bakeoff_plan(
    fixtures: Sequence[dict[str, Any]],
    models: Sequence[BakeoffModel],
    *,
    result_root: Path,
) -> dict[str, Any]:
    """Build deterministic, source-agnostic jobs without executing a model."""
    _validate_inputs(fixtures, models)
    jobs: list[dict[str, Any]] = []
    for model in sorted(models, key=lambda item: item.stable_key):
        for fixture in sorted(fixtures, key=lambda item: str(item["pair_id"])):
            pair_id = str(fixture["pair_id"])
            if not _STABLE_KEY_PATTERN.fullmatch(pair_id):
                raise ValueError(f"pair_id is not filesystem-safe: {pair_id}")
            jobs.append(
                {
                    "pair_id": pair_id,
                    "observations": {
                        side: fixture["observations"][side]["input_fingerprint"]
                        for side in ("a", "b")
                    },
                    "model": {
                        "stable_key": model.stable_key,
                        "model_path": model.model_path,
                        "model_sha256": model.model_sha256,
                        "execution_fingerprint": model.execution_fingerprint,
                    },
                    "result_path": str(
                        result_root / model.result_namespace / f"{pair_id}.json"
                    ),
                }
            )
    plan = {
        "schema_version": BAKEOFF_SCHEMA_VERSION,
        "purpose": "speaker_model_bakeoff",
        "registry_mutation_allowed": False,
        "winner_selection_allowed": False,
        "jobs": jobs,
    }
    plan["plan_sha256"] = _sha256_json(plan)
    return plan


def stamp_bakeoff_result(result: Mapping[str, Any], model: BakeoffModel) -> dict[str, Any]:
    """Bind a diagnostic result to the complete declared acoustic execution."""
    model_payload = result.get("model")
    if not isinstance(model_payload, Mapping) or not all(
        (
            model_payload.get("backend") == model.backend,
            model_payload.get("model_name") == model.model_name,
            model_payload.get("model_sha256") == model.model_sha256,
            model_payload.get("runtime_version") == model.runtime_version,
        )
    ):
        raise ValueError("diagnostic result does not match the requested bake-off model")
    stamped = dict(result)
    stamped["bakeoff_execution"] = {
        "schema_version": BAKEOFF_SCHEMA_VERSION,
        "stable_key": model.stable_key,
        "execution_fingerprint": model.execution_fingerprint,
    }
    stamped["registry_mutation_allowed"] = False
    return stamped


def audit_model_files(
    models: Sequence[BakeoffModel], *, repository_root: Path
) -> dict[str, Any]:
    """Verify local candidates without downloading or executing anything."""
    entries: list[dict[str, Any]] = []
    for model in sorted(models, key=lambda item: item.stable_key):
        path = Path(model.model_path)
        if not path.is_absolute():
            path = repository_root / path
        if not path.is_file():
            status = "missing"
            actual_sha256 = None
        else:
            actual_sha256 = _sha256_file(path)
            status = "verified" if actual_sha256 == model.model_sha256 else "checksum_mismatch"
        entries.append(
            {
                "stable_key": model.stable_key,
                "path": str(path),
                "expected_sha256": model.model_sha256,
                "actual_sha256": actual_sha256,
                "status": status,
            }
        )
    return {
        "models": entries,
        "all_models_verified": all(entry["status"] == "verified" for entry in entries),
    }


def audit_runtime_packages(
    models: Sequence[BakeoffModel],
    *,
    installed_versions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Verify the exact local runtime declared by every candidate."""
    expected = {
        model.runtime_package: model.runtime_version
        for model in models
    }
    entries: list[dict[str, Any]] = []
    for package, expected_version in sorted(expected.items()):
        try:
            actual_version = (
                installed_versions[package]
                if installed_versions is not None
                else metadata.version(package)
            )
        except (KeyError, metadata.PackageNotFoundError):
            actual_version = None
        entries.append(
            {
                "package": package,
                "expected_version": expected_version,
                "actual_version": actual_version,
                "status": (
                    "verified"
                    if actual_version == expected_version
                    else ("missing" if actual_version is None else "version_mismatch")
                ),
            }
        )
    return {
        "runtimes": entries,
        "all_runtimes_verified": all(
            entry["status"] == "verified" for entry in entries
        ),
    }


def build_bakeoff_preflight(
    fixtures: Sequence[dict[str, Any]],
    models: Sequence[BakeoffModel],
    *,
    repository_root: Path,
    result_root: Path,
    installed_versions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the mandatory, persisted safety gate for every bake-off run."""
    model_audit = audit_model_files(models, repository_root=repository_root)
    runtime_audit = audit_runtime_packages(
        models,
        installed_versions=installed_versions,
    )
    partition_audit = audit_fixture_partitions(fixtures)
    plan = build_bakeoff_plan(fixtures, models, result_root=result_root)
    blocking_reasons: list[str] = []
    if not model_audit["all_models_verified"]:
        blocking_reasons.append("model_files_unverified")
    if not runtime_audit["all_runtimes_verified"]:
        blocking_reasons.append("runtime_versions_unverified")
    if partition_audit["observation_leaks"]:
        blocking_reasons.append("cross_partition_observation_leak")
    return {
        "schema_version": BAKEOFF_SCHEMA_VERSION,
        "purpose": "speaker_model_bakeoff_preflight",
        "model_audit": model_audit,
        "runtime_audit": runtime_audit,
        "partition_audit": partition_audit,
        "plan": plan,
        "blocking_reasons": blocking_reasons,
        "execution_allowed": not blocking_reasons,
    }


def execute_bakeoff_plan(
    fixtures: Sequence[dict[str, Any]],
    models: Sequence[BakeoffModel],
    *,
    plan: Mapping[str, Any],
    analyze_fixture: Callable[[dict[str, Any], BakeoffModel], Mapping[str, Any]],
    progress: Callable[[int, int, str, str], None] | None = None,
) -> dict[str, Any]:
    """Execute or replay deterministic jobs without choosing a winner."""
    expected_plan = build_bakeoff_plan(
        fixtures,
        models,
        result_root=_plan_result_root(plan),
    )
    if plan != expected_plan:
        raise ValueError("bake-off plan does not match fixtures, models, and result root")
    fixture_by_pair = {str(item["pair_id"]): item for item in fixtures}
    model_by_key = {item.stable_key: item for item in models}
    results: list[dict[str, Any]] = []
    completed = 0
    replayed = 0
    jobs = list(plan["jobs"])
    for index, job in enumerate(jobs, start=1):
        pair_id = str(job["pair_id"])
        stable_key = str(job["model"]["stable_key"])
        fixture = fixture_by_pair[pair_id]
        model = model_by_key[stable_key]
        result_path = Path(str(job["result_path"]))
        if result_path.exists():
            result = _load_bakeoff_result(result_path)
            replayed += 1
        else:
            diagnostic = analyze_fixture(fixture, model)
            result = stamp_bakeoff_result(diagnostic, model)
            result["pair_id"] = pair_id
            _validate_bakeoff_result(result, fixture, model)
            _write_bakeoff_result(result_path, result)
            completed += 1
        _validate_bakeoff_result(result, fixture, model)
        results.append(result)
        if progress is not None:
            progress(index, len(jobs), stable_key, pair_id)
    return {
        "plan_sha256": plan["plan_sha256"],
        "jobs_total": len(jobs),
        "jobs_completed": completed,
        "jobs_replayed": replayed,
        "results": results,
        "report": evaluate_bakeoff(fixtures, results, models),
    }


def evaluate_bakeoff(
    fixtures: Sequence[dict[str, Any]],
    results: Sequence[dict[str, Any]],
    models: Sequence[BakeoffModel],
    *,
    required_decisions_per_outcome: int = 300,
    required_variation_tags: Sequence[str] = (
        "different_date",
        "different_microphone",
        "different_room",
        "varied_audio_quality",
    ),
) -> dict[str, Any]:
    """Compare candidates without selecting a winner or mutating identity state."""
    _validate_inputs(fixtures, models)
    grouped_results: dict[str, list[dict[str, Any]]] = {
        model.stable_key: [] for model in models
    }
    for result in results:
        if result.get("registry_mutation_allowed") is not False:
            raise ValueError("bake-off results must explicitly prohibit registry mutation")
        matches = [model for model in models if model.matches_result(result)]
        if len(matches) != 1:
            raise ValueError("every result must match exactly one manifest execution")
        grouped_results[matches[0].stable_key].append(result)

    model_reports: dict[str, Any] = {}
    for model in sorted(models, key=lambda item: item.stable_key):
        evaluation = evaluate_reviewed_pair_results(
            fixtures,
            grouped_results[model.stable_key],
            required_decisions_per_outcome=required_decisions_per_outcome,
            required_variation_tags=required_variation_tags,
        )
        model_reports[model.stable_key] = {
            "execution_fingerprint": model.execution_fingerprint,
            "result_namespace": model.result_namespace,
            "evaluation": evaluation,
            "raw_similarity": _raw_similarity_summary(
                fixtures,
                grouped_results[model.stable_key],
            ),
            "slices": _case_slices(fixtures, evaluation["cases"]),
        }

    return {
        "schema_version": BAKEOFF_SCHEMA_VERSION,
        "purpose": "speaker_model_bakeoff",
        "fixture_inventory": _fixture_inventory(fixtures),
        "partition_audit": audit_fixture_partitions(fixtures),
        "models": model_reports,
        "comparison": {
            "winner_selected": False,
            "reason": "model selection requires reviewed evidence and an explicit human decision",
        },
        "registry_mutation_allowed": False,
    }


def audit_fixture_partitions(fixtures: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Detect the same immutable observation appearing across evaluation partitions."""
    observation_partitions: dict[str, set[str]] = {}
    unassigned_pairs: list[str] = []
    partition_counts: dict[str, int] = {}
    for fixture in fixtures:
        partition = fixture.get("evaluation_partition")
        pair_id = str(fixture.get("pair_id"))
        if not isinstance(partition, str) or not partition:
            unassigned_pairs.append(pair_id)
            continue
        partition_counts[partition] = partition_counts.get(partition, 0) + 1
        for side in ("a", "b"):
            fingerprint = str(fixture["observations"][side]["input_fingerprint"])
            observation_partitions.setdefault(fingerprint, set()).add(partition)
    leaks = [
        {"observation_fingerprint": fingerprint, "partitions": sorted(partitions)}
        for fingerprint, partitions in sorted(observation_partitions.items())
        if len(partitions) > 1
    ]
    return {
        "partition_counts": dict(sorted(partition_counts.items())),
        "unassigned_pairs": sorted(unassigned_pairs),
        "observation_leaks": leaks,
        "held_out_evaluation_safe": not leaks and not unassigned_pairs,
    }


def _fixture_inventory(fixtures: Sequence[dict[str, Any]]) -> dict[str, Any]:
    observation_uses: dict[str, int] = {}
    expected_outcomes: dict[str, int] = {}
    variation_tags: dict[str, int] = {}
    selection_strata: dict[str, int] = {}
    source_relations: dict[str, int] = {}
    for fixture in fixtures:
        expected = str(fixture["expected_outcome"])
        expected_outcomes[expected] = expected_outcomes.get(expected, 0) + 1
        for side in ("a", "b"):
            fingerprint = str(fixture["observations"][side]["input_fingerprint"])
            observation_uses[fingerprint] = observation_uses.get(fingerprint, 0) + 1
        for tag in fixture["variation_tags"]:
            tag = str(tag)
            variation_tags[tag] = variation_tags.get(tag, 0) + 1
        manifest = fixture.get("selection_manifest")
        stratum = (
            str(manifest.get("selection_stratum"))
            if isinstance(manifest, dict) and manifest.get("selection_stratum")
            else "manual_or_unspecified"
        )
        selection_strata[stratum] = selection_strata.get(stratum, 0) + 1
        relation = (
            str(manifest.get("source_relation"))
            if isinstance(manifest, dict) and manifest.get("source_relation")
            else "legacy_or_unspecified"
        )
        source_relations[relation] = source_relations.get(relation, 0) + 1
    reuse_histogram: dict[str, int] = {}
    for uses in observation_uses.values():
        key = str(uses)
        reuse_histogram[key] = reuse_histogram.get(key, 0) + 1
    return {
        "fixture_count": len(fixtures),
        "unique_observation_count": len(observation_uses),
        "reused_observation_count": sum(uses > 1 for uses in observation_uses.values()),
        "maximum_observation_uses": max(observation_uses.values(), default=0),
        "observation_reuse_histogram": dict(sorted(reuse_histogram.items())),
        "expected_outcomes": dict(sorted(expected_outcomes.items())),
        "variation_tags": dict(sorted(variation_tags.items())),
        "selection_strata": dict(sorted(selection_strata.items())),
        "source_relations": dict(sorted(source_relations.items())),
    }


def _case_slices(
    fixtures: Sequence[dict[str, Any]], cases: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    case_by_pair = {str(case["pair_id"]): case for case in cases}
    strata: dict[str, dict[str, int]] = {}
    source_relations: dict[str, dict[str, int]] = {}
    tags: dict[str, dict[str, int]] = {}
    for fixture in fixtures:
        pair_id = str(fixture["pair_id"])
        status = str(case_by_pair[pair_id]["status"])
        manifest = fixture.get("selection_manifest")
        stratum = (
            str(manifest.get("selection_stratum"))
            if isinstance(manifest, dict) and manifest.get("selection_stratum")
            else "manual_or_unspecified"
        )
        _increment_nested(strata, stratum, status)
        relation = (
            str(manifest.get("source_relation"))
            if isinstance(manifest, dict) and manifest.get("source_relation")
            else "legacy_or_unspecified"
        )
        _increment_nested(source_relations, relation, status)
        for tag in fixture["variation_tags"]:
            _increment_nested(tags, str(tag), status)
    return {
        "by_selection_stratum": dict(sorted(strata.items())),
        "by_source_relation": dict(sorted(source_relations.items())),
        "by_variation_tag": dict(sorted(tags.items())),
    }


def _increment_nested(target: dict[str, dict[str, int]], key: str, status: str) -> None:
    target.setdefault(key, {})
    target[key][status] = target[key].get(status, 0) + 1


def _raw_similarity_summary(
    fixtures: Sequence[dict[str, Any]],
    results: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    fixture_by_observations = {
        frozenset(
            str(fixture["observations"][side]["input_fingerprint"])
            for side in ("a", "b")
        ): fixture
        for fixture in fixtures
    }
    values: dict[str, list[float]] = {
        "same_speaker": [],
        "different_speaker": [],
    }
    for result in results:
        observations = result.get("observations")
        metrics = result.get("metrics")
        if not isinstance(observations, Mapping) or not isinstance(metrics, Mapping):
            continue
        fixture = fixture_by_observations.get(
            frozenset(str(observations.get(side, "")) for side in ("a", "b"))
        )
        cross = metrics.get("cross")
        if fixture is None or not isinstance(cross, Mapping):
            continue
        median = cross.get("median")
        if isinstance(median, (int, float)):
            values[str(fixture["expected_outcome"])].append(float(median))
    same = values["same_speaker"]
    different = values["different_speaker"]
    return {
        "cross_median_by_expected_outcome": {
            "same_speaker": _value_distribution(same),
            "different_speaker": _value_distribution(different),
        },
        "worst_case_gap": (
            min(same) - max(different)
            if same and different
            else None
        ),
        "pairwise_separation_fraction": (
            sum(same_value > different_value for same_value in same for different_value in different)
            / (len(same) * len(different))
            if same and different
            else None
        ),
    }


def _value_distribution(values: Sequence[float]) -> dict[str, float | int | None]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0] if ordered else None,
        "median": statistics.median(ordered) if ordered else None,
        "max": ordered[-1] if ordered else None,
    }


def _plan_result_root(plan: Mapping[str, Any]) -> Path:
    jobs = plan.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("bake-off plan requires at least one job")
    result_path = Path(str(jobs[0]["result_path"]))
    return result_path.parent.parent


def _load_bakeoff_result(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    result_sha256 = payload.pop("result_sha256", None)
    if result_sha256 != _sha256_json(payload):
        raise ValueError(f"{path}: result checksum mismatch")
    return payload


def _write_bakeoff_result(path: Path, result: Mapping[str, Any]) -> None:
    payload = dict(result)
    payload["result_sha256"] = _sha256_json(result)
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise ValueError(f"refusing to overwrite changed bake-off result: {path}")
        return
    path.write_text(encoded, encoding="utf-8")


def _validate_bakeoff_result(
    result: Mapping[str, Any],
    fixture: Mapping[str, Any],
    model: BakeoffModel,
) -> None:
    if not model.matches_result(result):
        raise ValueError("bake-off result does not match its planned model execution")
    if result.get("registry_mutation_allowed") is not False:
        raise ValueError("bake-off result must prohibit registry mutation")
    if result.get("pair_id") != fixture.get("pair_id"):
        raise ValueError("bake-off result pair_id does not match fixture")
    for side in ("a", "b"):
        if (
            result.get("observations", {}).get(side)
            != fixture["observations"][side]["input_fingerprint"]
        ):
            raise ValueError("bake-off result observation does not match fixture")
        actual_hashes = [
            span.get("wav_sha256")
            for span in result.get("spans", {}).get(side, [])
        ]
        expected_hashes = [
            span["wav_sha256"]
            for span in fixture["observations"][side]["reviewed_spans"]
        ]
        if actual_hashes != expected_hashes:
            raise ValueError("bake-off result does not replay exact reviewed spans")


def _validate_inputs(
    fixtures: Sequence[dict[str, Any]], models: Sequence[BakeoffModel]
) -> None:
    if not models:
        raise ValueError("bake-off requires at least one model")
    model_keys = [model.stable_key for model in models]
    if len(set(model_keys)) != len(model_keys):
        raise ValueError("bake-off model stable_keys must be unique")
    execution_fingerprints = [model.execution_fingerprint for model in models]
    if len(set(execution_fingerprints)) != len(execution_fingerprints):
        raise ValueError("bake-off acoustic executions must be unique")
    pair_ids: list[str] = []
    for fixture in fixtures:
        validate_reviewed_pair_fixture(fixture)
        pair_ids.append(str(fixture.get("pair_id")))
    if len(set(pair_ids)) != len(pair_ids):
        raise ValueError("bake-off fixture pair_ids must be unique")


def _is_https_url(value: object) -> bool:
    return isinstance(value, str) and value.startswith("https://")


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
