from __future__ import annotations

from datetime import datetime, timezone
import json
import tempfile
import unittest
from pathlib import Path

from pastor_transcript_extractor.evaluation_partitioning import (
    EvaluationPartition,
    SourceFamilyRegistryError,
    assign_recording_partition,
    extend_source_family_registry,
    load_source_family_registry,
    suggested_partition,
)


def registry_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "registry_version": "test-v1",
        "partition_policy": {
            "version": "source_family_partition_v1",
            "salt": "test-salt",
            "development_percent": 60,
            "validation_percent": 20,
        },
        "source_families": [
            {
                "source_family_id": "family-a",
                "source_urls": ["https://example.test/channel/"],
                "partition": "development",
                "partition_origin": "historical_tuning_exposure",
            }
        ],
    }


class EvaluationPartitioningTests(unittest.TestCase):
    def _load(self, payload: dict[str, object]):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return load_source_family_registry(path)

    def test_resolves_normalized_source_url_and_assigns_whole_family(self) -> None:
        registry = self._load(registry_payload())

        captions = assign_recording_partition(
            registry=registry,
            video_id="a",
            source_url="HTTPS://EXAMPLE.TEST/channel",
            caption_source="captions",
            recording_date=datetime(2026, 7, 18, tzinfo=timezone.utc),
        )
        local_asr = assign_recording_partition(
            registry=registry,
            video_id="b",
            source_url="https://example.test/channel/",
            caption_source="local_asr",
            recording_date=None,
        )

        self.assertEqual(EvaluationPartition.DEVELOPMENT, captions.partition)
        self.assertEqual(captions.partition, local_asr.partition)
        self.assertEqual(captions.source_family_id, local_asr.source_family_id)
        self.assertNotEqual(
            captions.recording_condition_group_id,
            local_asr.recording_condition_group_id,
        )

    def test_partition_suggestion_is_stable_and_order_independent(self) -> None:
        registry = self._load(registry_payload())

        first = suggested_partition("new-family", registry.policy)
        replay = suggested_partition("new-family", registry.policy)

        self.assertEqual(first, replay)

    def test_rejects_source_url_leakage_between_families(self) -> None:
        payload = registry_payload()
        payload["source_families"].append(  # type: ignore[union-attr]
            {
                "source_family_id": "family-b",
                "source_urls": ["https://example.test/channel"],
                "partition": "validation",
                "partition_origin": "manual",
            }
        )

        with self.assertRaisesRegex(SourceFamilyRegistryError, "multiple families"):
            self._load(payload)

    def test_deterministic_origin_must_match_policy(self) -> None:
        payload = registry_payload()
        family = payload["source_families"][0]  # type: ignore[index]
        registry = self._load(registry_payload())
        suggested = suggested_partition("family-a", registry.policy)
        wrong = next(partition for partition in EvaluationPartition if partition != suggested)
        family["partition"] = wrong.value  # type: ignore[index]
        family["partition_origin"] = "deterministic"  # type: ignore[index]

        with self.assertRaisesRegex(SourceFamilyRegistryError, "does not match policy"):
            self._load(payload)

    def test_unregistered_source_cannot_silently_enter_a_partition(self) -> None:
        registry = self._load(registry_payload())

        with self.assertRaisesRegex(SourceFamilyRegistryError, "not registered"):
            assign_recording_partition(
                registry=registry,
                video_id="unknown",
                source_url="https://example.test/other",
                caption_source="captions",
                recording_date=None,
            )

    def test_registry_extension_groups_aliases_and_assigns_new_families_deterministically(self) -> None:
        payload = registry_payload()
        registry = self._load(payload)

        extension = extend_source_family_registry(
            registry,
            payload,
            [
                ("https://example.test/channel", "youtube:channel:existing"),
                ("https://example.test/channel-alias", "youtube:channel:existing"),
                ("https://youtube.test/channel/new", "youtube:channel:UC_New"),
            ],
        )
        replay = extend_source_family_registry(
            self._load(extension.payload),
            extension.payload,
            [
                ("https://example.test/channel", "youtube:channel:existing"),
                ("https://example.test/channel-alias", "youtube:channel:existing"),
                ("https://youtube.test/channel/new", "youtube:channel:UC_New"),
            ],
        )

        self.assertEqual(1, extension.families_added)
        self.assertEqual(1, extension.aliases_added)
        self.assertEqual(0, replay.families_added)
        self.assertEqual(0, replay.aliases_added)
        extended = self._load(extension.payload)
        new_family = next(
            family for family in extended.families if family.source_family_id == "youtube-channel-uc-new"
        )
        self.assertEqual(
            suggested_partition(new_family.source_family_id, extended.policy),
            new_family.partition,
        )

    def test_repository_registry_keeps_exposed_baseline_families_in_development(self) -> None:
        registry = load_source_family_registry(Path("evaluation/source-families.json"))

        self.assertGreaterEqual(len(registry.families), 7)
        historical = [
            family
            for family in registry.families
            if family.partition_origin == "historical_tuning_exposure"
        ]
        self.assertEqual(7, len(historical))
        self.assertEqual(
            {EvaluationPartition.DEVELOPMENT},
            {family.partition for family in historical},
        )


if __name__ == "__main__":
    unittest.main()
