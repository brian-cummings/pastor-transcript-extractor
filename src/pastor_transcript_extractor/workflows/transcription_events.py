from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeAlias


STAGE_QUEUED_PREP = "q-prep"
STAGE_DOWNLOADING = "dl"
STAGE_NORMALIZING = "norm"
STAGE_QUEUED_TRANSCRIBE = "q-xcribe"
STAGE_TRANSCRIBING = "xcribe"
STAGE_DONE = "done"
STAGE_FAILED = "failed"
STAGE_LABELS = {
    "queued": STAGE_QUEUED_PREP,
    "downloading": STAGE_DOWNLOADING,
    "normalizing": STAGE_NORMALIZING,
    "queued_transcribing": STAGE_QUEUED_TRANSCRIBE,
    "transcribing": STAGE_TRANSCRIBING,
    "done": STAGE_DONE,
    "failed": STAGE_FAILED,
}


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    selected_count: int = 0
    claimed_count: int = 0
    processed_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    failed_video_ids: frozenset[int] = frozenset()
    below_minimum_count: int = 0
    above_maximum_count: int = 0
    future_count: int = 0


@dataclass(frozen=True, slots=True)
class TranscriptionMessage:
    text: str


@dataclass(frozen=True, slots=True)
class TranscriptionBatchStarted:
    total: int
    workers: int


@dataclass(frozen=True, slots=True)
class TranscriptionVideoQueued:
    index: int
    total: int
    video_id: int
    title: str


@dataclass(frozen=True, slots=True)
class TranscriptionTaskSubmitted:
    video_id: int
    title: str


@dataclass(frozen=True, slots=True)
class TranscriptionStageChanged:
    video_id: int
    stage: str


@dataclass(frozen=True, slots=True)
class TranscriptionProgressed:
    video_id: int
    percent: int


@dataclass(frozen=True, slots=True)
class TranscriptionVideoFinished:
    finished: int
    total: int
    video_id: int
    title: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TranscriptionBatchFinished:
    result: TranscriptionResult


@dataclass(frozen=True, slots=True)
class TranscriptionRetrying:
    count: int


TranscriptionEvent: TypeAlias = (
    TranscriptionMessage
    | TranscriptionBatchStarted
    | TranscriptionVideoQueued
    | TranscriptionTaskSubmitted
    | TranscriptionStageChanged
    | TranscriptionProgressed
    | TranscriptionVideoFinished
    | TranscriptionBatchFinished
    | TranscriptionRetrying
)
TranscriptionEventCallback = Callable[[TranscriptionEvent], None]
