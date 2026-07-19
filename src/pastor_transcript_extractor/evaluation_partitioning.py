from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


PARTITION_POLICY_VERSION = "source_family_partition_v1"


class EvaluationPartition(StrEnum):
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    HELD_OUT = "held_out"


class SourceFamilyRegistryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PartitionPolicy:
    version: str
    salt: str
    development_percent: int
    validation_percent: int


@dataclass(frozen=True, slots=True)
class SourceFamily:
    source_family_id: str
    source_urls: tuple[str, ...]
    partition: EvaluationPartition
    partition_origin: str


@dataclass(frozen=True, slots=True)
class SourceFamilyRegistry:
    version: str
    policy: PartitionPolicy
    families: tuple[SourceFamily, ...]

    def resolve_source_url(self, source_url: str) -> SourceFamily | None:
        normalized = normalize_source_url(source_url)
        for family in self.families:
            if normalized in family.source_urls:
                return family
        return None


@dataclass(frozen=True, slots=True)
class RecordingPartitionAssignment:
    video_id: str
    source_family_id: str
    recording_condition_group_id: str
    partition: EvaluationPartition
    condition_metadata: Mapping[str, str]


def normalize_source_url(source_url: str) -> str:
    return source_url.strip().rstrip("/").lower()


def suggested_partition(source_family_id: str, policy: PartitionPolicy) -> EvaluationPartition:
    digest = hashlib.sha256(f"{policy.salt}:{source_family_id}".encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    if bucket < policy.development_percent:
        return EvaluationPartition.DEVELOPMENT
    if bucket < policy.development_percent + policy.validation_percent:
        return EvaluationPartition.VALIDATION
    return EvaluationPartition.HELD_OUT


def recording_condition_group_id(
    *,
    source_family_id: str,
    recording_format: str,
    production_era: str,
    caption_source: str,
) -> str:
    payload = {
        "caption_source": caption_source,
        "production_era": production_era,
        "recording_format": recording_format,
        "source_family_id": source_family_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "recording-condition-" + hashlib.sha256(encoded).hexdigest()[:16]


def production_era_for_date(recording_date: datetime | None) -> str:
    if recording_date is None:
        return "unknown"
    start_year = recording_date.year - (recording_date.year % 5)
    return f"{start_year}-{start_year + 4}"


def assign_recording_partition(
    *,
    registry: SourceFamilyRegistry,
    video_id: str,
    source_url: str,
    caption_source: str,
    recording_date: datetime | None,
    recording_format: str = "unknown",
) -> RecordingPartitionAssignment:
    family = registry.resolve_source_url(source_url)
    if family is None:
        raise SourceFamilyRegistryError(f"source URL is not registered: {source_url}")
    condition_metadata = {
        "caption_source": caption_source,
        "production_era": production_era_for_date(recording_date),
        "recording_format": recording_format,
    }
    return RecordingPartitionAssignment(
        video_id=video_id,
        source_family_id=family.source_family_id,
        recording_condition_group_id=recording_condition_group_id(
            source_family_id=family.source_family_id,
            **condition_metadata,
        ),
        partition=family.partition,
        condition_metadata=condition_metadata,
    )


def load_source_family_registry(path: Path) -> SourceFamilyRegistry:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SourceFamilyRegistryError(f"{path}: invalid JSON: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise SourceFamilyRegistryError("source-family registry schema_version must be 1")
    version = _nonempty_string(payload, "registry_version")
    policy_payload = _object(payload, "partition_policy")
    policy = PartitionPolicy(
        version=_nonempty_string(policy_payload, "version"),
        salt=_nonempty_string(policy_payload, "salt"),
        development_percent=_percentage(policy_payload, "development_percent"),
        validation_percent=_percentage(policy_payload, "validation_percent"),
    )
    if policy.version != PARTITION_POLICY_VERSION:
        raise SourceFamilyRegistryError(
            f"unsupported partition policy {policy.version!r}; expected {PARTITION_POLICY_VERSION!r}"
        )
    if policy.development_percent + policy.validation_percent >= 100:
        raise SourceFamilyRegistryError(
            "development_percent + validation_percent must leave a held-out partition"
        )

    raw_families = payload.get("source_families")
    if not isinstance(raw_families, list) or not raw_families:
        raise SourceFamilyRegistryError("source_families must be a non-empty list")
    families: list[SourceFamily] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for index, raw in enumerate(raw_families):
        if not isinstance(raw, dict):
            raise SourceFamilyRegistryError(f"source_families[{index}] must be an object")
        family_id = _nonempty_string(raw, "source_family_id")
        if family_id in seen_ids:
            raise SourceFamilyRegistryError(f"duplicate source_family_id: {family_id}")
        seen_ids.add(family_id)
        raw_urls = raw.get("source_urls")
        if not isinstance(raw_urls, list) or not raw_urls:
            raise SourceFamilyRegistryError(f"{family_id}.source_urls must be a non-empty list")
        urls = tuple(sorted(normalize_source_url(_list_string(item, family_id)) for item in raw_urls))
        duplicates = seen_urls.intersection(urls)
        if duplicates:
            raise SourceFamilyRegistryError(f"source URLs belong to multiple families: {sorted(duplicates)}")
        seen_urls.update(urls)
        try:
            partition = EvaluationPartition(_nonempty_string(raw, "partition"))
        except ValueError as error:
            raise SourceFamilyRegistryError(f"invalid partition for {family_id}") from error
        partition_origin = _nonempty_string(raw, "partition_origin")
        if partition_origin == "deterministic" and partition != suggested_partition(family_id, policy):
            raise SourceFamilyRegistryError(
                f"deterministic partition for {family_id} does not match policy"
            )
        families.append(SourceFamily(family_id, urls, partition, partition_origin))
    families.sort(key=lambda family: family.source_family_id)
    return SourceFamilyRegistry(version, policy, tuple(families))


def _object(payload: dict[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field)
    if not isinstance(value, dict):
        raise SourceFamilyRegistryError(f"{field} must be an object")
    return value


def _nonempty_string(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SourceFamilyRegistryError(f"{field} must be a non-empty string")
    return value.strip()


def _percentage(payload: Mapping[str, Any], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
        raise SourceFamilyRegistryError(f"{field} must be an integer from 0 through 100")
    return value


def _list_string(value: object, family_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceFamilyRegistryError(f"{family_id}.source_urls entries must be non-empty strings")
    return value
