"""Population and sermon text for the pastor fit experiment (section 3 of the spec).

The population is each profile's latest `profile-scripture-usage` run: its input sermons and
the extraction files they were analyzed from. Text is the sermon window, loaded the way sermon
analysis loads it, with the existing rolling-caption normalizer applied to legacy captions.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3

from ..caption_normalization import normalize_caption_fragments, should_normalize_rolling_captions
from ..sermon_analysis import _load_sermon_source

PROFILE_ANALYZER = 'profile-scripture-usage'

_POPULATION_SQL = """
WITH latest AS (
    SELECT profile_id, MAX(id) AS run_id
    FROM speaker_profile_analysis_runs
    WHERE analyzer_key = ?
    GROUP BY profile_id
)
SELECT latest.profile_id, videos.id, videos.youtube_video_id, videos.source_id, runs.source_path
FROM latest
JOIN speaker_profile_analysis_inputs AS inputs ON inputs.profile_analysis_run_id = latest.run_id
JOIN sermon_analysis_runs AS runs ON runs.id = inputs.sermon_analysis_run_id
JOIN videos ON videos.id = inputs.video_id
ORDER BY latest.profile_id, videos.id
"""


@dataclass(frozen=True)
class Sermon:
    video_id: int
    youtube_video_id: str
    profile_id: int
    source_id: int
    extraction_path: str


def load_population(database: Path) -> list[Sermon]:
    connection = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
    try:
        rows = connection.execute(_POPULATION_SQL, (PROFILE_ANALYZER,)).fetchall()
    finally:
        connection.close()
    seen: set[int] = set()
    sermons = []
    for profile_id, video_id, youtube_id, source_id, path in rows:
        if video_id in seen:
            raise ValueError(f'Video {video_id} belongs to more than one analyzed profile')
        seen.add(video_id)
        sermons.append(Sermon(int(video_id), str(youtube_id), int(profile_id), int(source_id), str(path)))
    if not sermons:
        raise ValueError('No analyzed profiles found')
    return sermons


def population_fingerprint(sermons: list[Sermon]) -> str:
    rows = sorted((s.profile_id, s.video_id, s.source_id) for s in sermons)
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def sermon_text(sermon: Sermon) -> tuple[str, dict]:
    """Return the sermon-window text and how it was produced."""
    return window_text(Path(sermon.extraction_path))


def window_text(path: Path) -> tuple[str, dict]:
    """Sermon-window text of one extraction JSON, with legacy rolling captions normalized."""
    raw = path.read_bytes()
    payload = json.loads(raw)
    segments, _, _ = _load_sermon_source(path)
    normalized = should_normalize_rolling_captions(payload)
    if normalized:
        text = normalize_caption_fragments((s.index, s.text) for s in segments).text
    else:
        text = '\n'.join(' '.join(s.text.split()) for s in segments)
    return text, {'extraction_sha256': hashlib.sha256(raw).hexdigest(),
                  'transcript_source': payload.get('transcript_source'),
                  'rolling_caption_normalized': normalized}
