from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path
from typing import Sequence

from pastor_transcript_extractor.speaker_pair_diagnostics import CachedSpan


PROFILE_REVIEW_WORKFLOW_VERSION = "anonymous_speaker_profile_review_v1"


@dataclass(frozen=True, slots=True)
class ProfileReviewRepresentative:
    profile_id: int
    observation_fingerprint: str
    spans: tuple[CachedSpan, ...]


def write_profile_review_packet(
    *,
    observation_fingerprint: str,
    spans: Sequence[CachedSpan],
    representatives: Sequence[ProfileReviewRepresentative],
    output_root: Path,
) -> Path:
    sections = [
        _audio_section(
            "Observation under review",
            spans,
            detail="Qualify this observation before assigning membership.",
        )
    ]
    for representative in sorted(
        representatives, key=lambda item: item.profile_id
    ):
        sections.append(
            _audio_section(
                f"Anonymous profile #{representative.profile_id}",
                representative.spans,
                detail="One explicitly reviewed member observation.",
            )
        )
    packet = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Anonymous speaker profile review</title>
  <style>
    body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 920px; margin: 2rem auto; padding: 0 1rem; }}
    section {{ border: 1px solid #ccc; border-radius: 8px; margin: 1rem 0; padding: 1rem; }}
    li {{ margin: .8rem 0; display: grid; grid-template-columns: 6rem 1fr; align-items: center; }}
    audio {{ width: 100%; }}
    .warning {{ background: #fff4d6; border-left: 4px solid #b77900; padding: .8rem; }}
  </style>
</head>
<body>
  <h1>Anonymous speaker profile review</h1>
  <p class="warning">Use only the reviewed voices. A source-family filter, when used, only bounds the queue and is not identity evidence. Acoustic predictions are not shown.</p>
  <p>First decide whether every clip under review contains one consistent principal speaker. Attach it only when the voice matches an existing profile; otherwise create a new anonymous profile or leave it unresolved.</p>
  {''.join(sections)}
</body>
</html>
"""
    output_path = (
        output_root
        / "profile-review"
        / f"{observation_fingerprint[:24]}.html"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.read_text(encoding="utf-8") == packet:
        return output_path
    output_path.write_text(packet, encoding="utf-8")
    return output_path


def _audio_section(
    title: str,
    spans: Sequence[CachedSpan],
    *,
    detail: str,
) -> str:
    players = []
    for index, span in enumerate(spans, start=1):
        source = Path(span.wav_path).expanduser().resolve().as_uri()
        players.append(
            f'<li><span>Clip {index}</span><audio controls preload="metadata" '
            f'src="{html.escape(source, quote=True)}"></audio></li>'
        )
    return (
        f"<section><h2>{html.escape(title)}</h2><p>{html.escape(detail)}</p>"
        f"<ol>{''.join(players)}</ol></section>"
    )
