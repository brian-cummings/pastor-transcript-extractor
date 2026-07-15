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
from typing import Any, Protocol, Sequence

from pastor_transcript_extractor.models import SpeakerObservation


SPAN_EXTRACTOR_VERSION = "speaker_span_v1"
ANALYZER_VERSION = "speaker_pair_diagnostic_v1"


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

    def prepare(
        self,
        *,
        observation: SpeakerObservation,
        source_audio_path: Path,
        span: SpanSpec,
    ) -> CachedSpan:
        key_payload = {
            "extractor_version": SPAN_EXTRACTOR_VERSION,
            "observation_fingerprint": observation.input_fingerprint,
            "source_audio_path": str(source_audio_path),
            "start_seconds": span.start_seconds,
            "end_seconds": span.end_seconds,
            "format": "pcm_s16le_mono_16000hz",
        }
        key = _sha256_json(key_payload)
        wav_path = self.root / "spans" / f"{key}.wav"
        manifest_path = self.root / "spans" / f"{key}.json"
        if wav_path.exists() and manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if _sha256_file(wav_path) != manifest.get("span", {}).get("wav_sha256"):
                raise RuntimeError(f"cached span checksum mismatch: {wav_path}")
            return CachedSpan(**{**manifest["span"], "cache_hit": True})
        if not source_audio_path.exists():
            raise AcousticEvidenceUnavailableError(f"local audio is unavailable: {source_audio_path}")
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        duration = span.end_seconds - span.start_seconds
        subprocess.run(
            [
                self.ffmpeg,
                "-hide_banner",
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
            capture_output=True,
            text=True,
        )
        measured_duration, rms_dbfs, clipped_fraction = _wav_quality(wav_path)
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
        )
        manifest = {"schema_version": 1, "cache_key": key, "input": key_payload, "span": asdict(cached)}
        manifest["span"].pop("cache_hit")
        _write_json(manifest_path, manifest)
        return cached


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
    specs_a = select_diagnostic_spans(
        observation_a, count=span_count, duration_seconds=span_duration_seconds
    )
    specs_b = select_diagnostic_spans(
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
        valid_a = [span for span in prepared_a if span.rms_dbfs >= min_rms_dbfs]
        valid_b = [span for span in prepared_b if span.rms_dbfs >= min_rms_dbfs]
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
            return {
                **result,
                "outcome": PairOutcome.INSUFFICIENT_EVIDENCE,
                "reason": "decision_policy_unavailable",
            }
        if (
            metrics["within_a"]["median"] < policy.min_within_median
            or metrics["within_b"]["median"] < policy.min_within_median
        ):
            return {
                **result,
                "outcome": PairOutcome.INSUFFICIENT_EVIDENCE,
                "reason": "within_observation_inconsistent",
            }
        if (
            metrics["cross"]["p10"] >= policy.same_min_cross_p10
            and metrics["cross"]["median"] >= policy.same_min_cross_median
        ):
            return {**result, "outcome": PairOutcome.SAME_SPEAKER, "reason": "approved_policy_same_band"}
        if metrics["cross"]["p90"] <= policy.different_max_cross_p90:
            return {
                **result,
                "outcome": PairOutcome.DIFFERENT_SPEAKER,
                "reason": "approved_policy_different_band",
            }
        return {**result, "outcome": PairOutcome.INSUFFICIENT_EVIDENCE, "reason": "ambiguous_similarity"}
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


def _wav_quality(path: Path) -> tuple[float, float, float]:
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
    return frames / rate, rms_dbfs, clipped


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
