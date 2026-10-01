from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Iterable, Mapping
import zipfile

from pastor_transcript_extractor.config import AppPaths
from pastor_transcript_extractor.filesystem_capacity import filesystem_capacity
from pastor_transcript_extractor.media_archive import archive_maintenance_lock


ARCHIVE_MANIFEST_NAME = "_pte-storage-manifest.json"
ARCHIVE_SCHEMA_VERSION = 1
MAINTENANCE_SCHEMA_VERSION = 1
DIAGNOSTIC_RUN_PATTERN = re.compile(r"^\d{8}T\d{6}Z$")
REVIEW_EVIDENCE_DIRECTORIES = (
    "reviews",
    "fixtures",
    "observation-reviews",
    "revocations",
    "drafts",
)


class StorageMaintenanceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StorageMember:
    path: str
    byte_size: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class StorageUnit:
    category: str
    unit_id: str
    action: str
    reason: str
    members: tuple[StorageMember, ...]

    @property
    def byte_size(self) -> int:
        return sum(member.byte_size for member in self.members)


@dataclass(frozen=True, slots=True)
class StorageMaintenancePlan:
    evaluation_root: str
    repository_root: str
    archive_root: str | None
    keep_diagnostic_runs: int
    units: tuple[StorageUnit, ...]
    blocked: tuple[str, ...]
    retained: tuple[dict[str, object], ...]

    @property
    def candidate_files(self) -> int:
        return sum(len(unit.members) for unit in self.units)

    @property
    def candidate_bytes(self) -> int:
        return sum(unit.byte_size for unit in self.units)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": MAINTENANCE_SCHEMA_VERSION,
            "evaluation_root": self.evaluation_root,
            "repository_root": self.repository_root,
            "archive_root": self.archive_root,
            "policy": {
                "keep_diagnostic_runs": self.keep_diagnostic_runs,
                "diagnostic_policy": "discard_older_runs",
                "legacy_span_policy": "archive_unreferenced_speaker_span_v1",
            },
            "summary": {
                "archive_units": sum(
                    unit.action == "archive_verify_remove_local" for unit in self.units
                ),
                "discard_units": sum(unit.action == "discard_local" for unit in self.units),
                "candidate_files": self.candidate_files,
                "candidate_bytes": self.candidate_bytes,
                "blocked": len(self.blocked),
            },
            "units": [
                {
                    **{key: value for key, value in asdict(unit).items() if key != "members"},
                    "file_count": len(unit.members),
                    "byte_size": unit.byte_size,
                    "members": [asdict(member) for member in unit.members],
                }
                for unit in self.units
            ],
            "blocked": list(self.blocked),
            "retained": list(self.retained),
        }


@dataclass(frozen=True, slots=True)
class StorageUnitResult:
    category: str
    unit_id: str
    archive_path: str | None
    outcome: str
    removed_files: int
    removed_bytes: int
    archive_sha256: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class StorageMaintenanceResult:
    units: tuple[StorageUnitResult, ...]

    @property
    def failures(self) -> tuple[StorageUnitResult, ...]:
        return tuple(unit for unit in self.units if unit.outcome == "failed")

    @property
    def removed_files(self) -> int:
        return sum(unit.removed_files for unit in self.units)

    @property
    def removed_bytes(self) -> int:
        return sum(unit.removed_bytes for unit in self.units)


@dataclass(frozen=True, slots=True)
class ArchiveVerification:
    archive_path: str
    category: str
    unit_id: str
    member_count: int
    byte_size: int
    archive_sha256: str


@dataclass(frozen=True, slots=True)
class RestoreResult:
    restored: int
    already_present: int
    conflicts: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _stream_sha256(stream) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _safe_unit_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    if not normalized:
        raise StorageMaintenanceError(f"invalid empty archive unit id: {value!r}")
    return normalized


def _regular_members(root: Path, evaluation_root: Path) -> tuple[StorageMember, ...]:
    members: list[StorageMember] = []
    if not root.exists():
        return ()
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        current = Path(directory)
        for name in tuple(directory_names):
            path = current / name
            if path.is_symlink():
                raise StorageMaintenanceError(f"archive candidate contains symlink: {path}")
        for name in sorted(file_names):
            path = current / name
            if path.is_symlink() or not path.is_file() or not _inside(path, evaluation_root):
                raise StorageMaintenanceError(f"archive candidate is not a safe regular file: {path}")
            stat = path.stat()
            members.append(
                StorageMember(
                    path.relative_to(evaluation_root).as_posix(),
                    stat.st_size,
                    stat.st_mtime_ns,
                )
            )
    return tuple(sorted(members, key=lambda member: member.path))


def _walk_wav_hashes(value: object) -> Iterable[str]:
    if isinstance(value, Mapping):
        wav_sha256 = value.get("wav_sha256")
        if isinstance(wav_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", wav_sha256):
            yield wav_sha256
        for child in value.values():
            yield from _walk_wav_hashes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_wav_hashes(child)


def _wav_hashes_below(root: Path, directory_names: Iterable[str]) -> set[str]:
    hashes: set[str] = set()
    for directory_name in directory_names:
        directory = root / directory_name
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.json")):
            if path.is_symlink():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            hashes.update(_walk_wav_hashes(payload))
    return hashes


def reviewed_wav_hashes(
    repository_root: Path,
    *,
    generated_evaluation_root: Path | None = None,
) -> set[str]:
    hashes = _wav_hashes_below(
        repository_root / "evaluation" / "speaker-pairs",
        REVIEW_EVIDENCE_DIRECTORIES,
    )
    if generated_evaluation_root is not None:
        # Generated drafts moved out of the repository during evaluation-storage
        # migration but remain live selection history until explicitly resolved.
        hashes.update(
            _wav_hashes_below(
                generated_evaluation_root / "speaker-pairs",
                ("drafts",),
            )
        )
    return hashes


def _legacy_span_unit(
    evaluation_root: Path,
    repository_root: Path,
    blocked: list[str],
    retained: list[dict[str, object]],
) -> StorageUnit | None:
    span_root = evaluation_root / "speaker-pairs" / "cache" / "spans"
    protected_hashes = reviewed_wav_hashes(
        repository_root,
        generated_evaluation_root=evaluation_root,
    )
    members: dict[str, StorageMember] = {}
    protected_files = protected_bytes = legacy_files = legacy_bytes = 0
    if not span_root.is_dir():
        return None
    for manifest_path in sorted(span_root.glob("*.json")):
        if manifest_path.is_symlink():
            blocked.append(f"legacy span manifest is a symlink: {manifest_path}")
            continue
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            blocked.append(f"invalid span manifest {manifest_path}: {error}")
            continue
        item = payload.get("input")
        span = payload.get("span")
        if not isinstance(item, dict) or item.get("extractor_version") != "speaker_span_v1":
            continue
        if not isinstance(span, dict) or not isinstance(span.get("wav_sha256"), str):
            blocked.append(f"legacy span manifest lacks a WAV checksum: {manifest_path}")
            continue
        cache_key = payload.get("cache_key")
        if not isinstance(cache_key, str) or manifest_path.stem != cache_key:
            blocked.append(f"legacy span cache key mismatch: {manifest_path}")
            continue
        wav_path = span_root / f"{cache_key}.wav"
        if not wav_path.is_file() or wav_path.is_symlink():
            blocked.append(f"legacy span WAV is missing or unsafe: {wav_path}")
            continue
        pair_size = manifest_path.stat().st_size + wav_path.stat().st_size
        legacy_files += 2
        legacy_bytes += pair_size
        if span["wav_sha256"] in protected_hashes:
            protected_files += 2
            protected_bytes += pair_size
            continue
        for path in (manifest_path, wav_path):
            stat = path.stat()
            relative = path.relative_to(evaluation_root).as_posix()
            members[relative] = StorageMember(relative, stat.st_size, stat.st_mtime_ns)
    retained.append(
        {
            "category": "speaker-pairs",
            "reason": "review_or_draft_pinned_legacy_spans",
            "files": protected_files,
            "bytes": protected_bytes,
        }
    )
    retained.append(
        {
            "category": "speaker-pairs",
            "reason": "legacy_span_inventory",
            "files": legacy_files,
            "bytes": legacy_bytes,
        }
    )
    if not members:
        return None
    fingerprint = hashlib.sha256()
    for member in sorted(members.values(), key=lambda item: item.path):
        fingerprint.update(member.path.encode("utf-8"))
        fingerprint.update(b"\0")
        fingerprint.update(str(member.byte_size).encode("ascii"))
        fingerprint.update(b"\0")
    return StorageUnit(
        category="speaker-pairs",
        unit_id=f"unreferenced-speaker-span-v1-{fingerprint.hexdigest()[:16]}",
        action="archive_verify_remove_local",
        reason="superseded extractor cache not pinned by review evidence or pending drafts",
        members=tuple(sorted(members.values(), key=lambda member: member.path)),
    )


def plan_storage_maintenance(
    paths: AppPaths,
    *,
    repository_root: Path,
    archive_root: Path | None,
    keep_diagnostic_runs: int = 3,
) -> StorageMaintenancePlan:
    if keep_diagnostic_runs < 1:
        raise ValueError("keep_diagnostic_runs must be at least one")
    evaluation_root = paths.evaluation.expanduser().resolve()
    repository_root = repository_root.expanduser().resolve()
    blocked: list[str] = []
    retained: list[dict[str, object]] = []
    units: list[StorageUnit] = []

    diagnostics_root = evaluation_root / "diagnostics"
    diagnostic_runs = sorted(
        (
            path
            for path in diagnostics_root.iterdir()
            if path.is_dir() and DIAGNOSTIC_RUN_PATTERN.fullmatch(path.name)
        ),
        key=lambda path: path.name,
    ) if diagnostics_root.is_dir() else []
    retained_runs = diagnostic_runs[-keep_diagnostic_runs:]
    for path in retained_runs:
        retained.append(
            {
                "category": "diagnostics",
                "reason": "within_newest_diagnostic_run_retention_window",
                "path": str(path),
            }
        )
    for run in diagnostic_runs[:-keep_diagnostic_runs]:
        try:
            members = _regular_members(run, evaluation_root)
        except StorageMaintenanceError as error:
            blocked.append(str(error))
            continue
        if members:
            units.append(
                StorageUnit(
                    category="diagnostics",
                    unit_id=run.name,
                    action="discard_local",
                    reason="derived diagnostic run outside the local retention window",
                    members=members,
                )
            )

    legacy_unit = _legacy_span_unit(
        evaluation_root,
        repository_root,
        blocked,
        retained,
    )
    if legacy_unit is not None:
        units.append(legacy_unit)

    return StorageMaintenancePlan(
        evaluation_root=str(evaluation_root),
        repository_root=str(repository_root),
        archive_root=(str(archive_root.expanduser().resolve()) if archive_root else None),
        keep_diagnostic_runs=keep_diagnostic_runs,
        units=tuple(units),
        blocked=tuple(blocked),
        retained=tuple(retained),
    )


def write_maintenance_manifest(
    plan: StorageMaintenancePlan,
    path: Path,
    *,
    result: StorageMaintenanceResult | None = None,
) -> None:
    payload = plan.to_dict()
    if result is not None:
        payload["result"] = {
            "removed_files": result.removed_files,
            "removed_bytes": result.removed_bytes,
            "failures": len(result.failures),
            "units": [asdict(unit) for unit in result.units],
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _member_path(evaluation_root: Path, member: StorageMember) -> Path:
    relative = PurePosixPath(member.path)
    if relative.is_absolute() or ".." in relative.parts:
        raise StorageMaintenanceError(f"unsafe maintenance member path: {member.path}")
    path = evaluation_root / Path(*relative.parts)
    if not _inside(path, evaluation_root):
        raise StorageMaintenanceError(f"maintenance member escapes evaluation root: {path}")
    return path


def _hashed_members(
    evaluation_root: Path,
    members: tuple[StorageMember, ...],
) -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    for member in members:
        path = _member_path(evaluation_root, member)
        if path.is_symlink() or not path.is_file():
            raise StorageMaintenanceError(f"archive source is missing or unsafe: {path}")
        stat = path.stat()
        if stat.st_size != member.byte_size or stat.st_mtime_ns != member.modified_ns:
            raise StorageMaintenanceError(f"archive source changed after planning: {path}")
        result.append(
            {
                "path": member.path,
                "byte_size": member.byte_size,
                "sha256": _sha256(path),
            }
        )
    return tuple(result)


def _archive_manifest(unit: StorageUnit, members: tuple[dict[str, object], ...]) -> dict[str, object]:
    return {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "category": unit.category,
        "unit_id": unit.unit_id,
        "reason": unit.reason,
        "members": list(members),
    }


def _archive_destination(archive_root: Path, unit: StorageUnit) -> Path:
    category = _safe_unit_id(unit.category)
    unit_id = _safe_unit_id(unit.unit_id)
    return archive_root / category / f"{unit_id}.zip"


def _read_archive_manifest(archive: zipfile.ZipFile) -> dict[str, object]:
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise StorageMaintenanceError("archive contains duplicate member names")
    if ARCHIVE_MANIFEST_NAME not in names:
        raise StorageMaintenanceError("archive lacks its storage manifest")
    try:
        payload = json.loads(archive.read(ARCHIVE_MANIFEST_NAME))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise StorageMaintenanceError(f"invalid archive manifest: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != ARCHIVE_SCHEMA_VERSION:
        raise StorageMaintenanceError("unsupported archive manifest schema")
    return payload


def verify_storage_archive(path: Path) -> ArchiveVerification:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise StorageMaintenanceError(f"archive is missing or unsafe: {path}")
    with zipfile.ZipFile(path, "r") as archive:
        manifest = _read_archive_manifest(archive)
        members = manifest.get("members")
        if not isinstance(members, list):
            raise StorageMaintenanceError("archive manifest members must be a list")
        expected_names = {ARCHIVE_MANIFEST_NAME}
        byte_size = 0
        for member in members:
            if not isinstance(member, dict):
                raise StorageMaintenanceError("archive manifest contains an invalid member")
            name = member.get("path")
            expected_size = member.get("byte_size")
            expected_sha256 = member.get("sha256")
            if not isinstance(name, str) or not isinstance(expected_size, int) or not isinstance(expected_sha256, str):
                raise StorageMaintenanceError("archive manifest member metadata is invalid")
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or name == ARCHIVE_MANIFEST_NAME:
                raise StorageMaintenanceError(f"unsafe archive member path: {name}")
            try:
                info = archive.getinfo(name)
            except KeyError as error:
                raise StorageMaintenanceError(f"archive member is missing: {name}") from error
            if info.is_dir() or info.file_size != expected_size:
                raise StorageMaintenanceError(f"archive member size mismatch: {name}")
            with archive.open(info, "r") as stream:
                if _stream_sha256(stream) != expected_sha256:
                    raise StorageMaintenanceError(f"archive member checksum mismatch: {name}")
            expected_names.add(name)
            byte_size += expected_size
        if set(archive.namelist()) != expected_names:
            raise StorageMaintenanceError("archive contains unmanifested members")
        category = manifest.get("category")
        unit_id = manifest.get("unit_id")
        if not isinstance(category, str) or not isinstance(unit_id, str):
            raise StorageMaintenanceError("archive identity is invalid")
    return ArchiveVerification(
        archive_path=str(path),
        category=category,
        unit_id=unit_id,
        member_count=len(members),
        byte_size=byte_size,
        archive_sha256=_sha256(path),
    )


def _existing_archive_covers(
    destination: Path,
    unit: StorageUnit,
    members: tuple[dict[str, object], ...],
) -> bool:
    verification = verify_storage_archive(destination)
    if verification.category != unit.category or verification.unit_id != unit.unit_id:
        return False
    with zipfile.ZipFile(destination, "r") as archive:
        manifest = _read_archive_manifest(archive)
    archived = {
        str(member["path"]): (int(member["byte_size"]), str(member["sha256"]))
        for member in manifest["members"]
        if isinstance(member, dict)
    }
    return all(
        archived.get(str(member["path"]))
        == (int(member["byte_size"]), str(member["sha256"]))
        for member in members
    )


def _write_archive(
    destination: Path,
    evaluation_root: Path,
    unit: StorageUnit,
    members: tuple[dict[str, object], ...],
) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if _existing_archive_covers(destination, unit, members):
            return "reused_verified_archive"
        raise StorageMaintenanceError(f"archive path collision: {destination}")
    partial = destination.with_name(f".{destination.name}.pte-partial")
    if partial.exists() or partial.is_symlink():
        partial.unlink()
    manifest = _archive_manifest(unit, members)
    try:
        with zipfile.ZipFile(
            partial,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=1,
            allowZip64=True,
        ) as archive:
            for member in members:
                path = evaluation_root / Path(*PurePosixPath(str(member["path"])).parts)
                archive.write(path, arcname=str(member["path"]))
            archive.writestr(
                ARCHIVE_MANIFEST_NAME,
                json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
            )
        verify_storage_archive(partial)
        os.replace(partial, destination)
        verify_storage_archive(destination)
    finally:
        if partial.exists() or partial.is_symlink():
            partial.unlink()
    return "archived"


def _validate_sources_unchanged(evaluation_root: Path, unit: StorageUnit) -> None:
    for planned in unit.members:
        path = _member_path(evaluation_root, planned)
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            raise StorageMaintenanceError(f"cleanup source became unsafe: {path}")
        stat = path.stat()
        if stat.st_size != planned.byte_size or stat.st_mtime_ns != planned.modified_ns:
            raise StorageMaintenanceError(f"cleanup source changed after planning: {path}")


def _remove_sources(
    evaluation_root: Path,
    unit: StorageUnit,
) -> tuple[int, int]:
    _validate_sources_unchanged(evaluation_root, unit)
    removed_files = removed_bytes = 0
    parents: set[Path] = set()
    for planned in unit.members:
        path = _member_path(evaluation_root, planned)
        if not path.exists():
            continue
        path.unlink()
        removed_files += 1
        removed_bytes += planned.byte_size
        parents.add(path.parent)
    for parent in sorted(parents, key=lambda value: len(value.parts), reverse=True):
        current = parent
        while current != evaluation_root and _inside(current, evaluation_root):
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
    return removed_files, removed_bytes


def apply_storage_maintenance(
    plan: StorageMaintenancePlan,
    *,
    app_root: Path,
    wait_for_lock: bool = True,
) -> StorageMaintenanceResult:
    if plan.blocked:
        raise StorageMaintenanceError("maintenance plan contains blocked or unsafe inputs")
    evaluation_root = Path(plan.evaluation_root).resolve()
    archive_units = tuple(
        unit for unit in plan.units if unit.action == "archive_verify_remove_local"
    )
    archive_root = Path(plan.archive_root).resolve() if plan.archive_root else None
    if archive_units and archive_root is None:
        raise StorageMaintenanceError("no artifact archive destination is configured")
    if archive_root is not None and _inside(archive_root, evaluation_root):
        raise StorageMaintenanceError("archive root must be outside the evaluation root")
    results: list[StorageUnitResult] = []
    with archive_maintenance_lock(app_root, wait_for_lock=wait_for_lock):
        probe: Path | None = None
        try:
            if archive_root is not None and not archive_root.is_dir():
                # Never manufacture a missing mount path. The configured media
                # archive root must already be mounted; only its direct
                # evaluation-storage child may be created here.
                if not archive_root.parent.is_dir():
                    raise StorageMaintenanceError(
                        f"archive destination is unavailable: {archive_root}"
                    )
                archive_root.mkdir()
            if archive_root is not None and archive_units:
                probe = archive_root / f".pte-storage-write-probe-{os.getpid()}"
                with probe.open("xb") as stream:
                    stream.write(b"pte-storage-probe")
                    stream.flush()
                    os.fsync(stream.fileno())
                probe.unlink()
                probe = None
                required_bytes = sum(
                    unit.byte_size
                    for unit in archive_units
                    if not _archive_destination(archive_root, unit).exists()
                )
                capacity = filesystem_capacity(archive_root)
                if capacity.available_bytes < required_bytes:
                    raise StorageMaintenanceError(
                        "archive destination has insufficient free space: "
                        f"available={capacity.available_bytes}, required={required_bytes}"
                    )
        except OSError as error:
            raise StorageMaintenanceError(
                f"archive destination is unavailable: {type(error).__name__}: {error}"
            ) from error
        finally:
            if probe is not None and (probe.exists() or probe.is_symlink()):
                probe.unlink(missing_ok=True)
        for unit in plan.units:
            destination = (
                _archive_destination(archive_root, unit)
                if archive_root is not None and unit.action == "archive_verify_remove_local"
                else None
            )
            try:
                if unit.action == "discard_local":
                    removed_files, removed_bytes = _remove_sources(evaluation_root, unit)
                    results.append(
                        StorageUnitResult(
                            unit.category,
                            unit.unit_id,
                            None,
                            "discarded",
                            removed_files,
                            removed_bytes,
                        )
                    )
                    continue
                if unit.action != "archive_verify_remove_local" or destination is None:
                    raise StorageMaintenanceError(
                        f"unsupported storage action: {unit.action}"
                    )
                members = _hashed_members(evaluation_root, unit.members)
                outcome = _write_archive(destination, evaluation_root, unit, members)
                verification = verify_storage_archive(destination)
                removed_files, removed_bytes = _remove_sources(evaluation_root, unit)
                results.append(
                    StorageUnitResult(
                        unit.category,
                        unit.unit_id,
                        str(destination),
                        outcome,
                        removed_files,
                        removed_bytes,
                        verification.archive_sha256,
                    )
                )
            except (OSError, StorageMaintenanceError, zipfile.BadZipFile) as error:
                results.append(
                    StorageUnitResult(
                        unit.category,
                        unit.unit_id,
                        str(destination) if destination is not None else None,
                        "failed",
                        0,
                        0,
                        None,
                        f"{type(error).__name__}: {error}",
                    )
                )
    return StorageMaintenanceResult(tuple(results))


def restore_storage_archive(
    archive_path: Path,
    *,
    evaluation_root: Path,
    apply: bool = False,
) -> RestoreResult:
    verify_storage_archive(archive_path)
    evaluation_root = evaluation_root.expanduser().resolve()
    restored = already_present = 0
    conflicts: list[str] = []
    with zipfile.ZipFile(archive_path.expanduser().resolve(), "r") as archive:
        manifest = _read_archive_manifest(archive)
        for member in manifest["members"]:
            relative = PurePosixPath(str(member["path"]))
            destination = evaluation_root / Path(*relative.parts)
            if not _inside(destination, evaluation_root):
                conflicts.append(f"unsafe restore destination: {destination}")
                continue
            if destination.exists() or destination.is_symlink():
                if (
                    destination.is_file()
                    and not destination.is_symlink()
                    and destination.stat().st_size == member["byte_size"]
                    and _sha256(destination) == member["sha256"]
                ):
                    already_present += 1
                else:
                    conflicts.append(f"restore collision: {destination}")
                continue
            if not apply:
                restored += 1
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not _inside(destination.parent, evaluation_root):
                conflicts.append(f"unsafe restore parent: {destination.parent}")
                continue
            partial = destination.with_name(f".{destination.name}.pte-restore-partial")
            try:
                with archive.open(str(member["path"]), "r") as source, partial.open("xb") as output:
                    digest = hashlib.sha256()
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                        digest.update(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if partial.stat().st_size != member["byte_size"] or digest.hexdigest() != member["sha256"]:
                    raise StorageMaintenanceError(f"restored member verification failed: {destination}")
                os.replace(partial, destination)
                restored += 1
            except Exception:
                if partial.exists() or partial.is_symlink():
                    partial.unlink()
                raise
    return RestoreResult(restored, already_present, tuple(conflicts))
