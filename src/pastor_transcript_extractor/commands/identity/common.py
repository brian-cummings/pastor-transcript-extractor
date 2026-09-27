from __future__ import annotations

import json
from pathlib import Path


def held_out_speaker_fixture_fingerprints(
    fixture_dir: Path,
) -> frozenset[str]:
    """Return observation fingerprints reserved for held-out evaluation."""
    fingerprints: set[str] = set()
    for path in sorted(fixture_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        manifest = payload.get("selection_manifest")
        partitions = (
            manifest.get("evaluation_partitions")
            if isinstance(manifest, dict)
            else None
        )
        is_held_out = payload.get("evaluation_partition") == "held_out" or (
            isinstance(partitions, dict) and "held_out" in partitions.values()
        )
        observations = payload.get("observations")
        if not is_held_out or not isinstance(observations, dict):
            continue
        for side in ("a", "b"):
            observation = observations.get(side)
            fingerprint = (
                observation.get("input_fingerprint")
                if isinstance(observation, dict)
                else None
            )
            if isinstance(fingerprint, str) and fingerprint:
                fingerprints.add(fingerprint)
    return frozenset(fingerprints)


# Temporary compatibility export for callers that imported the old CLI helper.
_held_out_speaker_fixture_fingerprints = held_out_speaker_fixture_fingerprints
