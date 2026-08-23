from __future__ import annotations

from array import array
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import wave
from typing import Any, Mapping, Protocol, Sequence

from pastor_transcript_extractor.models import SpeakerObservation
from pastor_transcript_extractor.media_artifacts import ArchivedMediaUnavailableError


SPAN_EXTRACTOR_VERSION = "speaker_span_v2"
ANALYZER_VERSION = "speaker_pair_diagnostic_v1"
SPEECH_ACTIVITY_MEASURER_VERSION = "frame_rms_activity_v1"
PAIR_DIAGNOSTIC_CACHE_VERSION = "speaker_pair_diagnostic_cache_v1"


class PairOutcome(StrEnum):
    SAME_SPEAKER = "same_speaker"
    DIFFERENT_SPEAKER = "different_speaker"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    ANALYSIS_FAILED = "analysis_failed"


class AcousticEvidenceUnavailableError(RuntimeError):
    """The requested comparison lacks usable evidence; the analyzer itself did not fail."""


@dataclass(frozen=True, slots=True)
class ModelSpec:
    backend: str
    model_name: str
    model_sha256: str
    runtime_version: str

    @property
    def fingerprint(self) -> str:
        return _sha256_json(asdict(self))


@dataclass(frozen=True, slots=True)
class SpanSpec:
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True, slots=True)
class CachedSpan:
    observation_fingerprint: str
    start_seconds: float
    end_seconds: float
    wav_path: str
    wav_sha256: str
    duration_seconds: float
    rms_dbfs: float
    clipped_fraction: float
    cache_hit: bool
    non_silent_fraction: float | None = None


@dataclass(frozen=True, slots=True)
class RecordingActivityProfile:
    policy_version: str
    source_audio_sha256: str
    frame_duration_ms: float
    reference_percentile: float
    reference_dbfs: float
    silence_threshold_dbfs: float
    frame_count: int
    cache_hit: bool


@dataclass(frozen=True, slots=True)
class DecisionPolicy:
    """An experimental, externally calibrated abstention policy.

    The library deliberately defines no default instance. A model is not a
    decision policy, and diagnostics without a reviewed policy must abstain.
    """

    version: str
    min_valid_spans: int
    min_within_median: float
    same_min_cross_p10: float
    same_min_cross_median: float
    different_max_cross_p90: float

    def __post_init__(self) -> None:
        if self.min_valid_spans < 2:
            raise ValueError("min_valid_spans must be at least 2")
        if self.same_min_cross_p10 <= self.different_max_cross_p90:
            raise ValueError("same-speaker boundary must exceed different-speaker boundary")

    @classmethod
    def from_path(cls, path: Path) -> DecisionPolicy:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("review_status") != "approved":
            raise ValueError("speaker decision policy must be explicitly approved")
        return cls(**{key: payload[key] for key in cls.__dataclass_fields__})


class EmbeddingBackend(Protocol):
    spec: ModelSpec

    def embed(self, wav_path: Path) -> Sequence[float]: ...


class SherpaOnnxEmbeddingBackend:
    def __init__(self, model_path: Path, *, expected_sha256: str, num_threads: int = 2):
        actual_sha256 = _sha256_file(model_path)
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"model checksum mismatch: expected {expected_sha256}, got {actual_sha256}"
            )
        try:
            import sherpa_onnx
        except ImportError as error:  # pragma: no cover - environment-dependent
            raise RuntimeError("install the acoustic-experiment optional dependencies") from error
        self._sherpa = sherpa_onnx
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(model_path), num_threads=num_threads, debug=False, provider="cpu"
            )
        )
        self.spec = ModelSpec(
            backend="sherpa-onnx",
            model_name=model_path.name,
            model_sha256=actual_sha256,
            runtime_version=getattr(sherpa_onnx, "__version__", "unknown"),
        )

    def embed(self, wav_path: Path) -> Sequence[float]:
        with wave.open(str(wav_path), "rb") as source:
            if source.getnchannels() != 1 or source.getsampwidth() != 2:
                raise ValueError("cached span must be mono 16-bit PCM")
            sample_rate = source.getframerate()
            samples = array("h")
            samples.frombytes(source.readframes(source.getnframes()))
        stream = self._extractor.create_stream()
        stream.accept_waveform(sample_rate, [sample / 32768.0 for sample in samples])
        stream.input_finished()
        if not self._extractor.is_ready(stream):
            raise ValueError("audio span is too short for the embedding model")
        embedding = tuple(float(value) for value in self._extractor.compute(stream))
        if not embedding or not all(math.isfinite(value) for value in embedding):
            raise ValueError("model produced an invalid embedding")
        return embedding


def select_diagnostic_spans(
    observation: SpeakerObservation,
    *,
    count: int = 5,
    duration_seconds: float = 12.0,
    edge_fraction: float = 0.15,
) -> tuple[SpanSpec, ...]:
    """Choose deterministic, separated spans from the interior of an observation."""
    if count < 2 or duration_seconds <= 0:
        raise ValueError("at least two positive-duration spans are required")
    start = observation.start_seconds
    end = observation.end_seconds
    interior_start = start + ((end - start) * edge_fraction)
    interior_end = end - ((end - start) * edge_fraction)
    available = interior_end - interior_start
    if available < duration_seconds * count:
        return ()
    travel = available - duration_seconds
    starts = [interior_start + (travel * index / (count - 1)) for index in range(count)]
    return tuple(
        SpanSpec(round(value, 3), round(value + duration_seconds, 3)) for value in starts
    )


class AudioSpanCache:
    def __init__(self, root: Path, *, ffmpeg: str = "ffmpeg"):
        self.root = root
        self.ffmpeg = ffmpeg
        self._source_hashes: dict[tuple[str, int, int], str] = {}
        self._observation_source_hashes: dict[str, str] = {}
        self._span_manifest_index: dict[
            tuple[str, str, str, float, float, str | None],
            tuple[Path, dict[str, Any]],
        ] | None = None
        self._verified_span_files: set[tuple[str, int, int, str]] = set()

    def prepare(
        self,
        *,
        observation: SpeakerObservation,
        source_audio_path: Path,
        span: SpanSpec,
        expected_source_audio_sha256: str | None = None,
        generation_policy_version: str | None = None,
    ) -> CachedSpan:
        cached = self._find_cached_span(
            observation=observation,
            source_audio_path=source_audio_path,
            span=span,
            expected_source_audio_sha256=expected_source_audio_sha256,
            generation_policy_version=generation_policy_version,
        )
        if cached is not None:
            return cached
        source_audio_sha256 = self._source_audio_sha256(source_audio_path)
        if (
            expected_source_audio_sha256 is not None
            and source_audio_sha256 != expected_source_audio_sha256
        ):
            raise AcousticEvidenceUnavailableError(
                "normalized audio checksum does not match its authoritative artifact"
            )
        key_payload = {
            "extractor_version": SPAN_EXTRACTOR_VERSION,
            "observation_fingerprint": observation.input_fingerprint,
            "source_audio_path": str(source_audio_path),
            "source_audio_sha256": source_audio_sha256,
            "start_seconds": span.start_seconds,
            "end_seconds": span.end_seconds,
            "format": "pcm_s16le_mono_16000hz",
            "generation_policy_version": generation_policy_version,
        }
        key = _sha256_json(key_payload)
        wav_path = self.root / "spans" / f"{key}.wav"
        manifest_path = self.root / "spans" / f"{key}.json"
        if wav_path.exists() and manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if _sha256_file(wav_path) != manifest.get("span", {}).get("wav_sha256"):
                raise RuntimeError(f"cached span checksum mismatch: {wav_path}")
            span_payload = dict(manifest["span"])
            if span_payload.get("non_silent_fraction") is None:
                span_payload["non_silent_fraction"] = measure_non_silent_fraction(wav_path)
                manifest["span"] = span_payload
                _write_json(manifest_path, manifest)
            return CachedSpan(**{**span_payload, "cache_hit": True})
        if not source_audio_path.exists():
            raise AcousticEvidenceUnavailableError(f"local audio is unavailable: {source_audio_path}")
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        duration = span.end_seconds - span.start_seconds
        subprocess.run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{span.start_seconds:.3f}",
                "-t",
                f"{duration:.3f}",
                "-i",
                str(source_audio_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(wav_path),
            ],
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
        measured_duration, rms_dbfs, clipped_fraction, non_silent_fraction = _wav_quality(
            wav_path
        )
        cached = CachedSpan(
            observation_fingerprint=observation.input_fingerprint,
            start_seconds=span.start_seconds,
            end_seconds=span.end_seconds,
            wav_path=str(wav_path),
            wav_sha256=_sha256_file(wav_path),
            duration_seconds=measured_duration,
            rms_dbfs=rms_dbfs,
            clipped_fraction=clipped_fraction,
            cache_hit=False,
            non_silent_fraction=non_silent_fraction,
        )
        manifest = {"schema_version": 1, "cache_key": key, "input": key_payload, "span": asdict(cached)}
        manifest["span"].pop("cache_hit")
        _write_json(manifest_path, manifest)
        if self._span_manifest_index is not None:
            manifest_key = self._span_manifest_key(key_payload)
            if manifest_key is not None:
                self._span_manifest_index[manifest_key] = (
                    manifest_path,
                    manifest,
                )
        return cached

    def _find_cached_span(
        self,
        *,
        observation: SpeakerObservation,
        source_audio_path: Path,
        span: SpanSpec,
        expected_source_audio_sha256: str | None = None,
        generation_policy_version: str | None = None,
    ) -> CachedSpan | None:
        """Use source-bound cached inputs without touching an offline archive."""
        self._ensure_span_manifest_index()
        assert self._span_manifest_index is not None
        manifest_key = (
            observation.input_fingerprint,
            (
                expected_source_audio_sha256
                or self._observation_source_audio_sha256(observation)
            ),
            str(source_audio_path),
            span.start_seconds,
            span.end_seconds,
            generation_policy_version,
        )
        indexed = self._span_manifest_index.get(manifest_key)
        if indexed is None:
            return None
        _manifest_path, manifest = indexed
        try:
            span_payload = dict(manifest["span"])
            wav_path = Path(span_payload["wav_path"])
            expected_sha256 = str(span_payload["wav_sha256"])
        except (KeyError, TypeError):
            return None
        if not self._verify_cached_span_file(wav_path, expected_sha256):
            return None
        if span_payload.get("non_silent_fraction") is None:
            span_payload["non_silent_fraction"] = measure_non_silent_fraction(
                wav_path
            )
        return CachedSpan(**{**span_payload, "cache_hit": True})

    def _ensure_span_manifest_index(self) -> None:
        if self._span_manifest_index is not None:
            return
        index: dict[
            tuple[str, str, str, float, float, str | None],
            tuple[Path, dict[str, Any]],
        ] = {}
        directory = self.root / "spans"
        if directory.is_dir():
            for manifest_path in sorted(directory.glob("*.json")):
                try:
                    manifest = json.loads(
                        manifest_path.read_text(encoding="utf-8")
                    )
                    item = manifest["input"]
                except (OSError, KeyError, TypeError, json.JSONDecodeError):
                    continue
                manifest_key = self._span_manifest_key(item)
                if manifest_key is not None:
                    index.setdefault(manifest_key, (manifest_path, manifest))
        self._span_manifest_index = index

    @staticmethod
    def _span_manifest_key(
        item: Mapping[str, Any],
    ) -> tuple[str, str, str, float, float, str | None] | None:
        if not isinstance(item, Mapping):
            return None
        if item.get("extractor_version") != SPAN_EXTRACTOR_VERSION:
            return None
        observation_fingerprint = item.get("observation_fingerprint")
        source_audio_sha256 = item.get("source_audio_sha256")
        source_audio_path = item.get("source_audio_path")
        start_seconds = item.get("start_seconds")
        end_seconds = item.get("end_seconds")
        generation_policy_version = item.get("generation_policy_version")
        if (
            not isinstance(observation_fingerprint, str)
            or not isinstance(source_audio_sha256, str)
            or not isinstance(source_audio_path, str)
            or not isinstance(start_seconds, (int, float))
            or not isinstance(end_seconds, (int, float))
            or (
                generation_policy_version is not None
                and not isinstance(generation_policy_version, str)
            )
        ):
            return None
        return (
            observation_fingerprint,
            source_audio_sha256,
            source_audio_path,
            float(start_seconds),
            float(end_seconds),
            generation_policy_version,
        )

    def _verify_cached_span_file(
        self, path: Path, expected_sha256: str
    ) -> bool:
        try:
            file_stat = path.stat()
        except OSError:
            return False
        key = (
            str(path),
            file_stat.st_size,
            file_stat.st_mtime_ns,
            expected_sha256,
        )
        if key in self._verified_span_files:
            return True
        if _sha256_file(path) != expected_sha256:
            return False
        self._verified_span_files.add(key)
        return True

    def _observation_source_audio_sha256(
        self, observation: SpeakerObservation
    ) -> str:
        cached = self._observation_source_hashes.get(
            observation.input_fingerprint
        )
        if cached is not None:
            return cached
        try:
            payload = json.loads(
                Path(observation.artifact_path).read_text(encoding="utf-8")
            )
            provenance = payload.get("normalized_audio_provenance")
            if isinstance(provenance, dict) and isinstance(
                provenance.get("content_sha256"), str
            ):
                value = provenance["content_sha256"]
                self._observation_source_hashes[
                    observation.input_fingerprint
                ] = value
                return value
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
        self._observation_source_hashes[
            observation.input_fingerprint
        ] = observation.content_sha256
        return observation.content_sha256

    def _source_audio_sha256(self, path: Path) -> str:
        try:
            file_stat = path.stat()
        except OSError as error:
            if path.is_symlink():
                raise ArchivedMediaUnavailableError(None, path.resolve(strict=False)) from error
            raise AcousticEvidenceUnavailableError(
                f"local audio is unavailable: {path}"
            ) from error
        key = (str(path.expanduser().resolve()), file_stat.st_size, file_stat.st_mtime_ns)
        content_sha256 = self._source_hashes.get(key)
        if content_sha256 is None:
            content_sha256 = _sha256_file(path)
            self._source_hashes[key] = content_sha256
        return content_sha256

    def recording_activity_profile(
        self,
        source_audio_path: Path,
        *,
        policy_version: str,
        frame_duration_ms: float,
        reference_percentile: float,
        threshold_offset_db: float,
        minimum_threshold_dbfs: float,
        maximum_threshold_dbfs: float,
    ) -> RecordingActivityProfile:
        if not 0.0 < reference_percentile < 1.0:
            raise ValueError(
                "activity reference percentile must be between zero and one"
            )
        if minimum_threshold_dbfs > maximum_threshold_dbfs:
            raise ValueError("activity threshold bounds are reversed")
        source_sha256 = self._source_audio_sha256(source_audio_path)
        profile_input = {
            "policy_version": policy_version,
            "source_audio_sha256": source_sha256,
            "frame_duration_ms": frame_duration_ms,
            "reference_percentile": reference_percentile,
            "threshold_offset_db": threshold_offset_db,
            "minimum_threshold_dbfs": minimum_threshold_dbfs,
            "maximum_threshold_dbfs": maximum_threshold_dbfs,
        }
        cache_key = _sha256_json(profile_input)
        profile_path = self.root / "activity-profiles" / f"{cache_key}.json"
        if profile_path.exists():
            payload = json.loads(profile_path.read_text(encoding="utf-8"))
            if payload.get("input") != profile_input:
                raise RuntimeError(
                    f"recording activity profile collision: {profile_path}"
                )
            return RecordingActivityProfile(
                **payload["profile"],
                cache_hit=True,
            )
        frame_levels = _wav_frame_levels_dbfs(
            source_audio_path,
            frame_duration_ms=frame_duration_ms,
        )
        reference_dbfs = _percentile(
            sorted(frame_levels),
            reference_percentile,
        )
        silence_threshold_dbfs = max(
            minimum_threshold_dbfs,
            min(
                maximum_threshold_dbfs,
                reference_dbfs - threshold_offset_db,
            ),
        )
        profile = RecordingActivityProfile(
            policy_version=policy_version,
            source_audio_sha256=source_sha256,
            frame_duration_ms=frame_duration_ms,
            reference_percentile=reference_percentile,
            reference_dbfs=reference_dbfs,
            silence_threshold_dbfs=silence_threshold_dbfs,
            frame_count=len(frame_levels),
            cache_hit=False,
        )
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(
            profile_path,
            {
                "schema_version": 1,
                "input": profile_input,
                "profile": {
                    key: value
                    for key, value in asdict(profile).items()
                    if key != "cache_hit"
                },
            },
        )
        return profile

    def measure_span_activity(
        self,
        span: CachedSpan,
        *,
        silence_threshold_dbfs: float,
        frame_duration_ms: float,
    ) -> float:
        return measure_non_silent_fraction(
            Path(span.wav_path),
            frame_duration_ms=frame_duration_ms,
            silence_threshold_dbfs=silence_threshold_dbfs,
        )


class EmbeddingCache:
    def __init__(self, root: Path):
        self.root = root

    def get_or_compute(
        self, span: CachedSpan, backend: EmbeddingBackend
    ) -> tuple[tuple[float, ...], bool]:
        key = _sha256_json(
            {
                "analyzer_version": ANALYZER_VERSION,
                "wav_sha256": span.wav_sha256,
                "model": asdict(backend.spec),
            }
        )
        path = self.root / "embeddings" / f"{key}.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            return tuple(float(value) for value in payload["embedding"]), True
        embedding = tuple(float(value) for value in backend.embed(Path(span.wav_path)))
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(
            path,
            {
                "schema_version": 1,
                "cache_key": key,
                "wav_sha256": span.wav_sha256,
                "model": asdict(backend.spec),
                "embedding": embedding,
            },
        )
        return embedding, False


class PairDiagnosticCache:
    """Content-addressed cache for complete candidate/exemplar diagnostics."""

    def __init__(self, root: Path):
        self.root = root
        self.hits = 0
        self.misses = 0
        self.primed = 0

    def get(
        self,
        *,
        base: Mapping[str, Any],
        observation_a: str,
        observation_b: str,
        spans_a: Sequence[CachedSpan],
        spans_b: Sequence[CachedSpan],
    ) -> dict[str, Any] | None:
        key = self._key(
            base=base,
            observation_a=observation_a,
            observation_b=observation_b,
            spans_a=[_span_evidence(span) for span in spans_a],
            spans_b=[_span_evidence(span) for span in spans_b],
        )
        path = self._path(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            self.misses += 1
            return None
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"pair diagnostic cache verification failed: {path}"
            )
        result = payload.get("result")
        if (
            payload.get("schema_version") != 1
            or payload.get("cache_version") != PAIR_DIAGNOSTIC_CACHE_VERSION
            or payload.get("cache_key") != key
            or not isinstance(result, dict)
            or payload.get("result_sha256") != _sha256_json(result)
        ):
            raise RuntimeError(f"pair diagnostic cache verification failed: {path}")
        self.hits += 1
        return dict(result)

    def put(self, result: Mapping[str, Any]) -> Path | None:
        cache_input = self._input_from_result(result)
        if cache_input is None:
            return None
        key = _sha256_json(cache_input)
        path = self._path(key)
        payload = {
            "schema_version": 1,
            "cache_version": PAIR_DIAGNOSTIC_CACHE_VERSION,
            "cache_key": key,
            "result_sha256": _sha256_json(result),
            "result": dict(result),
        }
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != payload:
                raise RuntimeError(f"pair diagnostic cache collision: {path}")
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(path, payload)
        return path

    def prime_from_shadow_associations(
        self, report_paths: Sequence[Path]
    ) -> None:
        seen_cache_keys: set[str] = set()
        for report_path in sorted(
            (path.expanduser().resolve() for path in report_paths), key=str
        ):
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if not isinstance(report, dict):
                continue
            expected_result = report.get("result_sha256")
            unhashed = dict(report)
            unhashed.pop("result_sha256", None)
            if (
                report.get("artifact_kind")
                != "speaker_profile_shadow_association"
                or report.get("shadow_mode") is not True
                or report.get("registry_mutation_allowed") is not False
                or not isinstance(expected_result, str)
                or _sha256_json(unhashed) != expected_result
            ):
                continue
            profiles = report.get("profiles")
            if not isinstance(profiles, list):
                continue
            for profile in profiles:
                comparisons = (
                    profile.get("comparisons")
                    if isinstance(profile, dict)
                    else None
                )
                if not isinstance(comparisons, list):
                    continue
                for comparison in comparisons:
                    if (
                        not isinstance(comparison, dict)
                        or comparison.get("reviewed_constraint") is True
                    ):
                        continue
                    result = {
                        key: value
                        for key, value in comparison.items()
                        if key
                        not in {
                            "exemplar_observation_id",
                            "exemplar_fingerprint",
                            "exemplar_normalized_audio_sha256",
                        }
                    }
                    cache_input = self._input_from_result(result)
                    if cache_input is None:
                        continue
                    cache_key = _sha256_json(cache_input)
                    if cache_key in seen_cache_keys:
                        continue
                    seen_cache_keys.add(cache_key)
                    before = self.put(result)
                    if before is not None:
                        self.primed += 1

    def _path(self, key: str) -> Path:
        return self.root / "pair-diagnostics" / f"{key}.json"

    @staticmethod
    def _key(
        *,
        base: Mapping[str, Any],
        observation_a: str,
        observation_b: str,
        spans_a: Sequence[Mapping[str, Any]],
        spans_b: Sequence[Mapping[str, Any]],
    ) -> str:
        return _sha256_json(
            {
                "cache_version": PAIR_DIAGNOSTIC_CACHE_VERSION,
                "analyzer_version": base.get("analyzer_version"),
                "model": base.get("model"),
                "policy": base.get("policy"),
                "observations": {"a": observation_a, "b": observation_b},
                "spans": {"a": list(spans_a), "b": list(spans_b)},
            }
        )

    @classmethod
    def _input_from_result(
        cls, result: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        observations = result.get("observations")
        spans = result.get("spans")
        if (
            result.get("analyzer_version") != ANALYZER_VERSION
            or not isinstance(observations, Mapping)
            or not isinstance(spans, Mapping)
            or not isinstance(observations.get("a"), str)
            or not isinstance(observations.get("b"), str)
            or not isinstance(spans.get("a"), list)
            or not isinstance(spans.get("b"), list)
            or not isinstance(result.get("metrics"), Mapping)
        ):
            return None
        return {
            "cache_version": PAIR_DIAGNOSTIC_CACHE_VERSION,
            "analyzer_version": result.get("analyzer_version"),
            "model": result.get("model"),
            "policy": result.get("policy"),
            "observations": dict(observations),
            "spans": {"a": list(spans["a"]), "b": list(spans["b"])},
        }


def build_embedding_centroid(
    *,
    observation: SpeakerObservation,
    audio_path: Path,
    span_specs: Sequence[SpanSpec],
    span_cache: AudioSpanCache,
    embedding_cache: EmbeddingCache,
    backend: EmbeddingBackend,
) -> tuple[float, ...]:
    """Build a normalized retrieval centroid from already-qualified spans."""
    if not span_specs:
        raise ValueError("embedding centroid requires qualified spans")
    vectors = [
        embedding_cache.get_or_compute(
            span_cache.prepare(
                observation=observation,
                source_audio_path=audio_path,
                span=span,
            ),
            backend,
        )[0]
        for span in span_specs
    ]
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1 or not dimensions or 0 in dimensions:
        raise ValueError("embedding centroid vectors have incompatible dimensions")
    centroid = tuple(
        sum(vector[index] for vector in vectors) / len(vectors)
        for index in range(len(vectors[0]))
    )
    norm = math.sqrt(sum(value * value for value in centroid))
    if norm <= 0.0 or not math.isfinite(norm):
        raise ValueError("embedding centroid has invalid norm")
    return tuple(value / norm for value in centroid)


def analyze_observation_pair(
    *,
    observation_a: SpeakerObservation | None,
    observation_b: SpeakerObservation | None,
    audio_path_a: Path | None,
    audio_path_b: Path | None,
    span_cache: AudioSpanCache,
    embedding_cache: EmbeddingCache,
    backend: EmbeddingBackend,
    policy: DecisionPolicy | None = None,
    span_count: int = 5,
    span_duration_seconds: float = 12.0,
    min_rms_dbfs: float = -52.0,
    span_specs_a: Sequence[SpanSpec] | None = None,
    span_specs_b: Sequence[SpanSpec] | None = None,
    span_specs_are_activity_qualified: bool = False,
    pair_diagnostic_cache: PairDiagnosticCache | None = None,
) -> dict[str, Any]:
    base = {
        "schema_version": 1,
        "analyzer_version": ANALYZER_VERSION,
        "model": asdict(backend.spec),
        "policy_version": policy.version if policy else None,
        "policy": asdict(policy) if policy else None,
        "registry_mutation_allowed": False,
    }
    if observation_a is None or observation_b is None:
        return {**base, "outcome": PairOutcome.INSUFFICIENT_EVIDENCE, "reason": "observation_unavailable"}
    if audio_path_a is None or audio_path_b is None:
        return {**base, "outcome": PairOutcome.INSUFFICIENT_EVIDENCE, "reason": "local_audio_unavailable"}
    specs_a = tuple(span_specs_a) if span_specs_a is not None else select_diagnostic_spans(
        observation_a, count=span_count, duration_seconds=span_duration_seconds
    )
    specs_b = tuple(span_specs_b) if span_specs_b is not None else select_diagnostic_spans(
        observation_b, count=span_count, duration_seconds=span_duration_seconds
    )
    if not specs_a or not specs_b:
        return {**base, "outcome": PairOutcome.INSUFFICIENT_EVIDENCE, "reason": "observation_too_short"}
    try:
        prepared_a = [
            span_cache.prepare(
                observation=observation_a, source_audio_path=audio_path_a, span=spec
            )
            for spec in specs_a
        ]
        prepared_b = [
            span_cache.prepare(
                observation=observation_b, source_audio_path=audio_path_b, span=spec
            )
            for spec in specs_b
        ]
        valid_a = (
            prepared_a
            if span_specs_are_activity_qualified
            else [span for span in prepared_a if span.rms_dbfs >= min_rms_dbfs]
        )
        valid_b = (
            prepared_b
            if span_specs_are_activity_qualified
            else [span for span in prepared_b if span.rms_dbfs >= min_rms_dbfs]
        )
        minimum = policy.min_valid_spans if policy else 2
        if len(valid_a) < minimum or len(valid_b) < minimum:
            return {
                **base,
                "outcome": PairOutcome.INSUFFICIENT_EVIDENCE,
                "reason": "too_few_valid_spans",
                "spans": {
                    "a": [_span_evidence(value) for value in prepared_a],
                    "b": [_span_evidence(value) for value in prepared_b],
                },
            }
        if pair_diagnostic_cache is not None:
            cached_result = pair_diagnostic_cache.get(
                base=base,
                observation_a=observation_a.input_fingerprint,
                observation_b=observation_b.input_fingerprint,
                spans_a=valid_a,
                spans_b=valid_b,
            )
            if cached_result is not None:
                return cached_result
        embedded_a = [embedding_cache.get_or_compute(span, backend) for span in valid_a]
        embedded_b = [embedding_cache.get_or_compute(span, backend) for span in valid_b]
        vectors_a = [value[0] for value in embedded_a]
        vectors_b = [value[0] for value in embedded_b]
        within_a = _pairwise(vectors_a, vectors_a, triangular=True)
        within_b = _pairwise(vectors_b, vectors_b, triangular=True)
        cross = _pairwise(vectors_a, vectors_b)
        metrics = {
            "within_a": _distribution(within_a),
            "within_b": _distribution(within_b),
            "cross": _distribution(cross),
        }
        result: dict[str, Any] = {
            **base,
            "observations": {
                "a": observation_a.input_fingerprint,
                "b": observation_b.input_fingerprint,
            },
            "spans": {
                "a": [_span_evidence(value) for value in valid_a],
                "b": [_span_evidence(value) for value in valid_b],
            },
            "metrics": metrics,
        }
        if policy is None:
            outcome_result = {
                **result,
                "outcome": PairOutcome.INSUFFICIENT_EVIDENCE,
                "reason": "decision_policy_unavailable",
            }
            if pair_diagnostic_cache is not None:
                pair_diagnostic_cache.put(outcome_result)
            return outcome_result
        outcome, reason = apply_decision_policy(metrics, policy)
        outcome_result = {**result, "outcome": outcome, "reason": reason}
        if pair_diagnostic_cache is not None:
            pair_diagnostic_cache.put(outcome_result)
        return outcome_result
    except AcousticEvidenceUnavailableError as error:
        return {
            **base,
            "outcome": PairOutcome.INSUFFICIENT_EVIDENCE,
            "reason": "local_audio_unavailable",
            "detail": str(error),
        }
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        return {
            **base,
            "outcome": PairOutcome.ANALYSIS_FAILED,
            "reason": "technical_failure",
            "error_type": type(error).__name__,
            "error": str(error),
        }


def apply_decision_policy(
    metrics: Mapping[str, Any],
    policy: DecisionPolicy,
    *,
    decision_reason_prefix: str = "approved_policy",
) -> tuple[PairOutcome, str]:
    """Apply a policy to immutable metrics without recomputing embeddings."""
    within_a = metrics.get("within_a")
    within_b = metrics.get("within_b")
    cross = metrics.get("cross")
    if not all(isinstance(value, Mapping) for value in (within_a, within_b, cross)):
        raise ValueError("speaker decision metrics are incomplete")
    if (
        float(within_a["median"]) < policy.min_within_median
        or float(within_b["median"]) < policy.min_within_median
    ):
        return PairOutcome.INSUFFICIENT_EVIDENCE, "within_observation_inconsistent"
    if (
        float(cross["p10"]) >= policy.same_min_cross_p10
        and float(cross["median"]) >= policy.same_min_cross_median
    ):
        return PairOutcome.SAME_SPEAKER, f"{decision_reason_prefix}_same_band"
    if float(cross["p90"]) <= policy.different_max_cross_p90:
        return PairOutcome.DIFFERENT_SPEAKER, f"{decision_reason_prefix}_different_band"
    return PairOutcome.INSUFFICIENT_EVIDENCE, "ambiguous_similarity"


def validate_reviewed_pair_fixture(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != 1:
        raise ValueError("speaker-pair fixture schema_version must be 1")
    if payload.get("review_status") != "approved":
        raise ValueError("speaker-pair ground truth must be explicitly approved")
    if payload.get("expected_outcome") not in {
        PairOutcome.SAME_SPEAKER,
        PairOutcome.DIFFERENT_SPEAKER,
    }:
        raise ValueError("expected_outcome must be same_speaker or different_speaker")
    for side in ("a", "b"):
        observation = payload.get("observations", {}).get(side)
        if not isinstance(observation, dict) or not observation.get("input_fingerprint"):
            raise ValueError(f"fixture observation {side} requires an immutable fingerprint")
        spans = observation.get("reviewed_spans")
        if not isinstance(spans, list) or len(spans) < 2:
            raise ValueError(f"fixture observation {side} requires at least two reviewed spans")
        for span in spans:
            if not isinstance(span.get("wav_sha256"), str) or len(span["wav_sha256"]) != 64:
                raise ValueError("every reviewed span requires its exact WAV sha256")
    if not payload.get("reviewer") or not payload.get("reviewed_at"):
        raise ValueError("fixture requires reviewer and reviewed_at")
    tags = payload.get("variation_tags")
    if not isinstance(tags, list):
        raise ValueError("fixture requires explicit variation_tags (an empty list is allowed)")


def evaluate_reviewed_pair_results(
    fixtures: Sequence[dict[str, Any]],
    results: Sequence[dict[str, Any]],
    *,
    required_decisions_per_outcome: int = 300,
    required_variation_tags: Sequence[str] = (
        "different_date",
        "different_microphone",
        "different_room",
        "varied_audio_quality",
    ),
) -> dict[str, Any]:
    """Evaluate exact reviewed spans without treating abstentions as recognition errors."""
    for fixture in fixtures:
        validate_reviewed_pair_fixture(fixture)
    indexed_results: dict[frozenset[str], list[dict[str, Any]]] = {}
    for result in results:
        observations = result.get("observations")
        if not isinstance(observations, dict) or not observations.get("a") or not observations.get("b"):
            continue
        key = frozenset((str(observations["a"]), str(observations["b"])))
        indexed_results.setdefault(key, []).append(result)

    counts = {
        "fixtures": len(fixtures),
        "true_same": 0,
        "true_different": 0,
        "false_same": 0,
        "false_different": 0,
        "insufficient_evidence": 0,
        "analysis_failed": 0,
        "missing_or_nonreplayable_result": 0,
    }
    cases: list[dict[str, Any]] = []
    covered_tags: set[str] = set()
    model_fingerprints: set[str] = set()
    policy_fingerprints: set[str] = set()
    for fixture in fixtures:
        observation_a = str(fixture["observations"]["a"]["input_fingerprint"])
        observation_b = str(fixture["observations"]["b"]["input_fingerprint"])
        matches = indexed_results.get(frozenset((observation_a, observation_b)), [])
        case = {"pair_id": fixture.get("pair_id"), "expected": fixture["expected_outcome"]}
        if len(matches) != 1:
            counts["missing_or_nonreplayable_result"] += 1
            cases.append({**case, "status": "missing_result" if not matches else "ambiguous_results"})
            continue
        result = matches[0]
        side_map = {"a": "a", "b": "b"}
        if result["observations"]["a"] == observation_b:
            side_map = {"a": "b", "b": "a"}
        hashes_match = all(
            [span["wav_sha256"] for span in result.get("spans", {}).get(side_map[side], [])]
            == [span["wav_sha256"] for span in fixture["observations"][side]["reviewed_spans"]]
            for side in ("a", "b")
        )
        if not hashes_match:
            counts["missing_or_nonreplayable_result"] += 1
            cases.append({**case, "status": "reviewed_span_mismatch"})
            continue
        covered_tags.update(str(tag) for tag in fixture["variation_tags"])
        model_fingerprints.add(_sha256_json(result.get("model")))
        policy_fingerprints.add(_sha256_json(result.get("policy")))
        actual = result.get("outcome")
        if actual == PairOutcome.INSUFFICIENT_EVIDENCE:
            counts["insufficient_evidence"] += 1
            status = "abstained"
        elif actual == PairOutcome.ANALYSIS_FAILED:
            counts["analysis_failed"] += 1
            status = "failed"
        elif actual == PairOutcome.SAME_SPEAKER:
            if fixture["expected_outcome"] == PairOutcome.SAME_SPEAKER:
                counts["true_same"] += 1
                status = "correct"
            else:
                counts["false_same"] += 1
                status = "false_same"
        elif actual == PairOutcome.DIFFERENT_SPEAKER:
            if fixture["expected_outcome"] == PairOutcome.DIFFERENT_SPEAKER:
                counts["true_different"] += 1
                status = "correct"
            else:
                counts["false_different"] += 1
                status = "false_different"
        else:
            counts["missing_or_nonreplayable_result"] += 1
            status = "invalid_outcome"
        cases.append({**case, "actual": actual, "status": status})

    same_decisions = counts["true_same"] + counts["false_same"]
    different_decisions = counts["true_different"] + counts["false_different"]
    decisions = same_decisions + different_decisions
    evaluated = len(fixtures) - counts["missing_or_nonreplayable_result"]
    missing_tags = sorted(set(required_variation_tags) - covered_tags)
    observed_zero_error_gate = counts["false_same"] == 0 and counts["false_different"] == 0
    promotion_ready = all(
        (
            observed_zero_error_gate,
            counts["analysis_failed"] == 0,
            counts["missing_or_nonreplayable_result"] == 0,
            same_decisions >= required_decisions_per_outcome,
            different_decisions >= required_decisions_per_outcome,
            not missing_tags,
            len(model_fingerprints) == 1,
            len(policy_fingerprints) == 1,
            policy_fingerprints != {_sha256_json(None)},
        )
    )
    return {
        "schema_version": 1,
        "counts": counts,
        "rates": {
            "decision_coverage": decisions / evaluated if evaluated else 0.0,
            "same_decision_precision": counts["true_same"] / same_decisions if same_decisions else None,
            "different_decision_precision": (
                counts["true_different"] / different_decisions if different_decisions else None
            ),
            "zero_error_95pct_upper_bound_same": (
                3.0 / same_decisions
                if same_decisions and counts["false_same"] == 0
                else None
            ),
            "zero_error_95pct_upper_bound_different": (
                3.0 / different_decisions
                if different_decisions and counts["false_different"] == 0
                else None
            ),
        },
        "gates": {
            "observed_zero_error_gate": observed_zero_error_gate,
            "required_decisions_per_outcome": required_decisions_per_outcome,
            "missing_variation_tags": missing_tags,
            "single_model_and_policy": (
                len(model_fingerprints) == 1
                and len(policy_fingerprints) == 1
                and policy_fingerprints != {_sha256_json(None)}
            ),
            "promotion_ready": promotion_ready,
        },
        "cases": cases,
    }


def write_pair_result(path: Path, result: dict[str, Any]) -> None:
    payload = dict(result)
    payload["result_sha256"] = _sha256_json(result)
    _write_json(path, payload)


def _pairwise(
    left: Sequence[Sequence[float]],
    right: Sequence[Sequence[float]],
    *,
    triangular: bool = False,
) -> list[float]:
    values: list[float] = []
    for left_index, left_value in enumerate(left):
        for right_index, right_value in enumerate(right):
            if triangular and right_index <= left_index:
                continue
            values.append(_cosine(left_value, right_value))
    return values


def observation_consistency_metrics(
    embeddings: Sequence[Sequence[float]],
) -> dict[str, Any]:
    """Describe whether distributed clips form one compact voice cluster."""
    if len(embeddings) < 3:
        raise ValueError("observation consistency requires at least three embeddings")
    pairwise = _pairwise(embeddings, embeddings, triangular=True)
    clip_coherence = [
        statistics.median(
            _cosine(embedding, other)
            for other_index, other in enumerate(embeddings)
            if other_index != index
        )
        for index, embedding in enumerate(embeddings)
    ]
    split = _strongest_two_cluster_split(embeddings)
    return {
        "pairwise_similarity": _distribution(pairwise),
        "clip_coherence": _distribution(clip_coherence),
        "weakest_clip_coherence": min(clip_coherence),
        "pairwise_spread": max(pairwise) - min(pairwise),
        "strongest_two_cluster_split": split,
    }


def analyze_cached_observation_consistency(
    *,
    spans: Sequence[CachedSpan],
    embedding_cache: EmbeddingCache,
    backend: EmbeddingBackend,
    min_rms_dbfs: float = -52.0,
) -> dict[str, Any]:
    valid = [span for span in spans if span.rms_dbfs >= min_rms_dbfs]
    if len(valid) < 3:
        return {
            "status": "insufficient_evidence",
            "reason": "too_few_valid_spans",
            "valid_span_count": len(valid),
        }
    try:
        embedded = [
            embedding_cache.get_or_compute(span, backend)
            for span in valid
        ]
        metrics = observation_consistency_metrics(
            [embedding for embedding, _ in embedded]
        )
        return {
            "status": "scored",
            "valid_span_count": len(valid),
            "embedding_cache_hits": sum(cache_hit for _, cache_hit in embedded),
            "metrics": metrics,
        }
    except (OSError, RuntimeError, ValueError) as error:
        return {
            "status": "analysis_failed",
            "reason": "technical_failure",
            "error_type": type(error).__name__,
            "error": str(error),
        }


def _strongest_two_cluster_split(
    embeddings: Sequence[Sequence[float]],
) -> dict[str, Any]:
    best: tuple[float, tuple[int, ...], tuple[int, ...], float, float] | None = None
    size = len(embeddings)
    # Keep clip zero in the left cluster to avoid evaluating mirror partitions.
    for mask in range(0, 1 << (size - 1)):
        left = (0,) + tuple(
            index
            for index in range(1, size)
            if mask & (1 << (index - 1))
        )
        right = tuple(index for index in range(size) if index not in left)
        if not right or len(left) == size:
            continue
        within = [
            *_pairwise(
                [embeddings[index] for index in left],
                [embeddings[index] for index in left],
                triangular=True,
            ),
            *_pairwise(
                [embeddings[index] for index in right],
                [embeddings[index] for index in right],
                triangular=True,
            ),
        ]
        if not within:
            continue
        cross = _pairwise(
            [embeddings[index] for index in left],
            [embeddings[index] for index in right],
        )
        within_median = statistics.median(within)
        cross_median = statistics.median(cross)
        separation = within_median - cross_median
        candidate = (
            separation,
            left,
            right,
            within_median,
            cross_median,
        )
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None:
        raise ValueError("no valid two-cluster split")
    return {
        "separation": best[0],
        "left_clip_indexes": list(best[1]),
        "right_clip_indexes": list(best[2]),
        "within_median": best[3],
        "cross_median": best[4],
    }


def _span_evidence(span: CachedSpan) -> dict[str, object]:
    evidence = asdict(span)
    evidence.pop("cache_hit")
    evidence.pop("wav_path")
    return evidence


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("embeddings must have equal non-zero dimensions")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("zero-norm embedding")
    return dot / (left_norm * right_norm)


def _distribution(values: Sequence[float]) -> dict[str, float | int]:
    if not values:
        raise ValueError("similarity distribution is empty")
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p10": _percentile(ordered, 0.10),
        "median": statistics.median(ordered),
        "p90": _percentile(ordered, 0.90),
        "max": ordered[-1],
    }


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * (position - lower))


def measure_non_silent_fraction(
    path: Path,
    *,
    frame_duration_ms: float = 30.0,
    silence_threshold_dbfs: float = -50.0,
) -> float:
    """Measure non-silent PCM frames without claiming that they contain speech."""
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("activity measurement requires mono 16-bit PCM")
        rate = source.getframerate()
        samples = array("h")
        samples.frombytes(source.readframes(source.getnframes()))
    return _non_silent_fraction(
        samples,
        rate,
        frame_duration_ms=frame_duration_ms,
        silence_threshold_dbfs=silence_threshold_dbfs,
    )


def _wav_frame_levels_dbfs(
    path: Path,
    *,
    frame_duration_ms: float,
) -> list[float]:
    if frame_duration_ms <= 0:
        raise ValueError("frame duration must be positive")
    levels: list[float] = []
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError(
                "recording activity profiling requires mono 16-bit PCM"
            )
        rate = source.getframerate()
        if rate <= 0:
            raise ValueError("recording activity sample rate must be positive")
        frame_size = max(
            1,
            round(rate * frame_duration_ms / 1000.0),
        )
        while raw := source.readframes(frame_size):
            samples = array("h")
            samples.frombytes(raw)
            mean_square = sum(
                float(value) * float(value) for value in samples
            ) / len(samples)
            rms = math.sqrt(mean_square)
            levels.append(
                20.0 * math.log10(max(rms / 32768.0, 1e-12))
            )
    if not levels:
        raise ValueError("recording activity source is empty")
    return levels


def _wav_quality(path: Path) -> tuple[float, float, float, float]:
    with wave.open(str(path), "rb") as source:
        frames = source.getnframes()
        rate = source.getframerate()
        samples = array("h")
        samples.frombytes(source.readframes(frames))
    if not samples or rate <= 0:
        raise ValueError("extracted audio span is empty")
    mean_square = sum(float(value) * float(value) for value in samples) / len(samples)
    rms = math.sqrt(mean_square)
    rms_dbfs = 20.0 * math.log10(max(rms / 32768.0, 1e-12))
    clipped = sum(abs(value) >= 32760 for value in samples) / len(samples)
    return (
        frames / rate,
        rms_dbfs,
        clipped,
        _non_silent_fraction(samples, rate),
    )


def _non_silent_fraction(
    samples: Sequence[int],
    sample_rate: int,
    *,
    frame_duration_ms: float = 30.0,
    silence_threshold_dbfs: float = -50.0,
) -> float:
    if not samples or sample_rate <= 0:
        raise ValueError("audio samples are empty")
    if frame_duration_ms <= 0:
        raise ValueError("frame duration must be positive")
    frame_size = max(1, round(sample_rate * frame_duration_ms / 1000.0))
    active_frames = 0
    total_frames = 0
    for start in range(0, len(samples), frame_size):
        frame = samples[start : start + frame_size]
        mean_square = sum(float(value) * float(value) for value in frame) / len(frame)
        rms = math.sqrt(mean_square)
        rms_dbfs = 20.0 * math.log10(max(rms / 32768.0, 1e-12))
        active_frames += rms_dbfs >= silence_threshold_dbfs
        total_frames += 1
    return active_frames / total_frames


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
