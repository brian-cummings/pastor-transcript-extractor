"""The one frozen sermon: whole text from the pilot's saved leaf table, with block ranges for coordinates and watch links."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pastor_transcript_extractor.bound_claims.common import read_json, watch_url

SEPARATOR = '\n\n'


@dataclass(frozen=True)
class Sermon:
    video_id: int
    title: str
    url: str
    source_sha256: str
    text: str
    blocks: tuple[tuple[str, int, int, float], ...]  # coordinate, start char, end char, start seconds

    def block_at(self, position: int) -> tuple[str, float]:
        for coordinate, start, end, seconds in self.blocks:
            if start <= position < end + len(SEPARATOR):
                return coordinate, seconds
        raise ValueError(f'Position {position} is outside the sermon text')

    def link_at(self, position: int) -> str:
        return watch_url(self.url, self.block_at(position)[1])


def load(leaf_path: Path, video_id: int) -> Sermon:
    found = [item for item in read_json(leaf_path)['sermons'] if item['video_id'] == video_id]
    if len(found) != 1:
        raise ValueError(f'Video {video_id} is not in the saved leaf table')
    item, parts, blocks, cursor = found[0], [], [], 0
    for block in item['blocks']:
        blocks.append((block['coordinate'], cursor, cursor + len(block['text']), block['start_seconds']))
        parts.append(block['text'])
        cursor += len(block['text']) + len(SEPARATOR)
    return Sermon(video_id=video_id, title=item['title'], url=item['url'], source_sha256=item['source_sha256'],
                  text=SEPARATOR.join(parts), blocks=tuple(blocks))
