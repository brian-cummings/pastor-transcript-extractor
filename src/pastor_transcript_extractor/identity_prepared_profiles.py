from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping


# Bump when preparation semantics change beyond the pinned upstream versions.
PREPARED_PROFILE_VERSION = "identity_prepared_profiles_v1"


class PreparedProfileCache:
    """Verified preparation snapshots; never identity or media authority.

    Member successes are independently addressed so a changed profile snapshot
    does not discard compatible acoustic preparation. All eligibility and media
    gates belong to the caller and must run before consuming a cached result.
    """

    def __init__(self, cache_root: Path):
        self.root = cache_root / "prepared-profiles"

    def has_profile(self, profile_id: int) -> bool:
        return next((self.root / f"profile-{profile_id}").glob("*.json"), None) is not None

    def load(
        self, kind: str, inputs: Mapping[str, Any], *, profile_id: int | None = None
    ) -> dict[str, Any] | None:
        path = self._path(kind, inputs, profile_id=profile_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return None
            expected = payload.pop("result_sha256", None)
            if (
                expected != _digest(payload)
                or payload.get("version") != PREPARED_PROFILE_VERSION
                or payload.get("kind") != kind
                or payload.get("inputs_sha256") != _digest(inputs)
                or not isinstance(payload.get("result"), dict)
            ):
                return None
            return payload["result"]
        except (OSError, UnicodeError, ValueError, TypeError):
            # A cache miss rebuilds through the normal gates; corrupt cache data
            # cannot supply evidence or authorize a profile match.
            return None

    def save(
        self, kind: str, inputs: Mapping[str, Any], result: Mapping[str, Any],
        *, profile_id: int | None = None,
    ) -> None:
        path = self._path(kind, inputs, profile_id=profile_id)
        payload = {
            "version": PREPARED_PROFILE_VERSION,
            "kind": kind,
            "inputs_sha256": _digest(inputs),
            "inputs": inputs,
            "result": result,
        }
        payload["result_sha256"] = _digest(payload)
        serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if path.exists():
            if path.read_bytes() == serialized.encode("utf-8"):
                return
            # Do not overwrite historical snapshots, including corrupt ones.
            # A verified conflicting result is a producer defect, not a miss.
            if self.load(kind, inputs, profile_id=profile_id) is not None:
                raise RuntimeError(f"prepared profile cache collision: {path}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                    suffix=".partial", delete=False) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(serialized)
            # Linking publishes atomically without replacing immutable evidence.
            try:
                os.link(temporary_path, path)
            except FileExistsError:
                if self.load(kind, inputs, profile_id=profile_id) != dict(result):
                    raise RuntimeError(f"prepared profile cache collision: {path}")
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _path(
        self, kind: str, inputs: Mapping[str, Any], *, profile_id: int | None
    ) -> Path:
        if kind not in {"profile", "member"}:
            raise ValueError("unknown prepared profile cache kind")
        if kind == "profile" and (profile_id is None or profile_id < 1):
            raise ValueError("profile snapshot requires a positive profile id")
        directory = f"profile-{profile_id}" if kind == "profile" else "members"
        key = _digest({"version": PREPARED_PROFILE_VERSION, "inputs": inputs})
        return self.root / directory / f"{key}.json"


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()
