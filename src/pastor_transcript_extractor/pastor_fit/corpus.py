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

# Every profile's latest run counts. A merged profile keeps its old run, and the profile it was merged into
# lists the same videos once it is re-analyzed, so each profile is resolved through its latest redirect and
# each video is kept once, from the newest run that lists it (load_population).
_POPULATION_SQL = """
WITH latest AS (
    SELECT profile_id, MAX(id) AS run_id
    FROM speaker_profile_analysis_runs
    WHERE analyzer_key = ?
    GROUP BY profile_id
)
SELECT latest.profile_id, latest.run_id, videos.id, videos.youtube_video_id, videos.source_id, runs.source_path
FROM latest
JOIN speaker_profile_analysis_inputs AS inputs ON inputs.profile_analysis_run_id = latest.run_id
JOIN sermon_analysis_runs AS runs ON runs.id = inputs.sermon_analysis_run_id
JOIN videos ON videos.id = inputs.video_id
ORDER BY latest.profile_id, videos.id
"""

_REDIRECT_SQL = """
SELECT from_profile_id, action, to_profile_id FROM speaker_profile_redirect_events AS e
WHERE id = (SELECT MAX(id) FROM speaker_profile_redirect_events WHERE from_profile_id = e.from_profile_id)
"""


def profile_resolver(connection: sqlite3.Connection):
    """Map a profile id to the profile it now resolves to, following each profile's latest redirect event
    (as `Database.resolve_speaker_profile_id` does)."""
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    latest = ({int(source): (action, target) for source, action, target in connection.execute(_REDIRECT_SQL)}
              if 'speaker_profile_redirect_events' in tables else {})

    def resolve(profile_id: int) -> int:
        seen = set()
        while profile_id in latest and latest[profile_id][0] == 'redirect' and latest[profile_id][1] is not None:
            if profile_id in seen:
                raise ValueError(f'Speaker profile redirect cycle at {profile_id}')
            seen.add(profile_id)
            profile_id = int(latest[profile_id][1])
        return profile_id

    return resolve


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
        resolve = profile_resolver(connection)
    finally:
        connection.close()
    # One entry per video: the newest run that lists it wins (it reflects current membership), and the
    # profile is the one that run's profile resolves to, so a merged profile's videos count under the survivor.
    newest: dict[int, tuple[int, Sermon]] = {}
    for profile_id, run_id, video_id, youtube_id, source_id, path in rows:
        sermon = Sermon(int(video_id), str(youtube_id), resolve(int(profile_id)), int(source_id), str(path))
        if int(video_id) not in newest or int(run_id) > newest[int(video_id)][0]:
            newest[int(video_id)] = (int(run_id), sermon)
    sermons = sorted((sermon for _, sermon in newest.values()), key=lambda s: (s.profile_id, s.video_id))
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
