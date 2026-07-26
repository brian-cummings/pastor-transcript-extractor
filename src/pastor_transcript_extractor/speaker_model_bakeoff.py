from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

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
    }


def _case_slices(
    fixtures: Sequence[dict[str, Any]], cases: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    case_by_pair = {str(case["pair_id"]): case for case in cases}
    strata: dict[str, dict[str, int]] = {}
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
        for tag in fixture["variation_tags"]:
            _increment_nested(tags, str(tag), status)
    return {
        "by_selection_stratum": dict(sorted(strata.items())),
        "by_variation_tag": dict(sorted(tags.items())),
    }


def _increment_nested(target: dict[str, dict[str, int]], key: str, status: str) -> None:
    target.setdefault(key, {})
    target[key][status] = target[key].get(status, 0) + 1


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
