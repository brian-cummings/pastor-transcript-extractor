from __future__ import annotations

import unittest

from pastor_transcript_extractor.identity_attribution import extract_grounded_attributions


def metadata(title: str, *, raw: dict | None = None) -> dict:
    return {
        "source_kind": "database_backfill",
        "video": {"title": title},
        "raw_metadata": raw or {},
    }


def proposed(*segments: tuple[float, float, str], sermon_start: float = 120.0) -> dict:
    return {
        "sermon_window": {"start_seconds": sermon_start, "end_seconds": 1800.0},
        "segments": [
            {"start_seconds": start, "end_seconds": end, "text": text}
            for start, end, text in segments
        ],
    }


def analyze(metadata_payload: dict, proposed_payload: dict, target: str = "Dr. Samuel Bulgin"):
    return extract_grounded_attributions(
        metadata_payload=metadata_payload,
        proposed_payload=proposed_payload,
        target_name=target,
        metadata_artifact_id=17,
        metadata_content_sha256="abc123",
    )


class GroundedAttributionTests(unittest.TestCase):
    def test_guest_named_in_title_is_exact_and_contradicting(self) -> None:
        title = '"Living with Integrity" By Elder Robert McLean- May 30, 2026'
        result = analyze(metadata(title), proposed())

        self.assertIn("metadata_non_target_match", result.outcomes)
        self.assertIn("explicit_guest_attribution", result.outcomes)
        self.assertNotIn("explicit_target_attribution", result.outcomes)
        observation = result.observations[0]
        self.assertEqual("non_target", observation["person_kind"])
        self.assertEqual("video.title", observation["provenance"]["field_path"])
        self.assertEqual("database_backfill", observation["provenance"]["metadata_source_kind"])
        self.assertEqual(title, observation["provenance"]["exact_excerpt"])

    def test_target_named_in_title_is_supporting_but_does_not_confirm_identity(self) -> None:
        title = 'Duluth Seventh-Day Adventist Church - Pastor Andrew Korp - "What Jesus Noticed"'
        result = analyze(metadata(title), proposed(), target="Andrew Korp")

        self.assertIn("metadata_target_match", result.outcomes)
        self.assertIn("explicit_target_attribution", result.outcomes)
        self.assertNotIn("conflicting_attribution", result.outcomes)
        self.assertEqual("target", result.correlation_groups[0]["person_kind"])

    def test_generic_title_uses_grounded_spoken_introduction_line(self) -> None:
        text = "Good morning. Our speaker today is Pastor Andrew Korp. Please welcome him."
        result = analyze(
            metadata("Sabbath Worship Service"),
            proposed((90.0, 110.0, text)),
            target="Andrew Korp",
        )

        self.assertIn("spoken_introduction_target", result.outcomes)
        self.assertIn("explicit_target_attribution", result.outcomes)
        self.assertNotIn("metadata_target_match", result.outcomes)
        observation = result.observations[0]
        self.assertEqual("S000001", observation["provenance"]["line_id"])
        self.assertEqual(text, observation["provenance"]["exact_excerpt"])

    def test_spoken_guest_introduction_is_contradicting(self) -> None:
        result = analyze(
            metadata("Sabbath Worship Service"),
            proposed((70.0, 100.0, "Our speaker for today is Elder Robert McLean.")),
        )

        self.assertIn("spoken_introduction_guest", result.outcomes)
        self.assertIn("explicit_guest_attribution", result.outcomes)

    def test_explicit_handoff_is_scanned_when_no_sermon_window_exists(self) -> None:
        payload = proposed(
            (0.0, 30.0, "Welcome and announcements."),
            (2300.0, 2330.0, "Our speaker today is Elder Robert McLean."),
        )
        payload["sermon_window"]["start_seconds"] = None
        result = analyze(metadata("Worship Service"), payload)

        self.assertIn("spoken_introduction_guest", result.outcomes)
        self.assertEqual("S000002", result.observations[0]["provenance"]["line_id"])

    def test_repeated_credit_fields_form_one_correlation_group(self) -> None:
        result = analyze(
            metadata(
                "Pastor Andrew Korp - Grace",
                raw={
                    "title": "Pastor Andrew Korp - Grace",
                    "description": "Today's sermon is presented by Andrew Korp.",
                    "chapters": [{"title": "Message - Pastor Andrew Korp"}],
                },
            ),
            proposed(),
            target="Andrew Korp",
        )

        self.assertGreaterEqual(len(result.observations), 4)
        self.assertEqual(1, len(result.correlation_groups))
        self.assertEqual(1, result.correlation_groups[0]["counts_as_independent_evidence"])

    def test_conflicting_explicit_credits_are_reported_without_resolution(self) -> None:
        result = analyze(
            metadata("Pastor Andrew Korp - The Promise"),
            proposed((80.0, 100.0, "Our speaker today is Elder Robert McLean.")),
            target="Andrew Korp",
        )

        self.assertIn("conflicting_attribution", result.outcomes)
        self.assertIn("explicit_target_attribution", result.outcomes)
        self.assertIn("explicit_guest_attribution", result.outcomes)
        self.assertEqual(2, len(result.correlation_groups))

    def test_name_reference_without_attribution_cue_is_ignored(self) -> None:
        result = analyze(
            metadata("Sabbath Worship Service"),
            proposed((100.0, 140.0, "Please pray for Pastor Andrew Korp and his family.")),
            target="Andrew Korp",
        )

        self.assertEqual(("no_attribution_evidence",), result.outcomes)
        self.assertEqual((), result.observations)

    def test_topic_style_and_theology_never_create_identity_evidence(self) -> None:
        result = analyze(
            metadata("The Gospel of Grace"),
            proposed((110.0, 160.0, "Turn in your Bibles to Romans. Grace changes everything.")),
            target="Andrew Korp",
        )

        self.assertEqual(("no_attribution_evidence",), result.outcomes)
        self.assertEqual(0, len(result.correlation_groups))

    def test_organization_after_message_credit_is_not_misread_as_person(self) -> None:
        result = analyze(
            metadata("Worship Service"),
            proposed((100.0, 130.0, "The message will be presented by three students from Shaw Creek.")),
        )

        self.assertEqual(("no_attribution_evidence",), result.outcomes)

    def test_memorial_honoree_is_a_name_match_but_not_an_explicit_speaker_credit(self) -> None:
        result = analyze(metadata("Celebration of Life Dr. Willard Munger"), proposed())

        self.assertIn("metadata_non_target_match", result.outcomes)
        self.assertNotIn("explicit_guest_attribution", result.outcomes)

    def test_nearby_thanks_name_does_not_inherit_another_persons_credit(self) -> None:
        result = analyze(
            metadata(
                "Worship Service",
                raw={"description": "Message by Elder Robert McLean. Special thanks to Andrew Korp."},
            ),
            proposed(),
            target="Andrew Korp",
        )

        target = next(item for item in result.observations if item["person_kind"] == "target")
        guest = next(item for item in result.observations if item["person_kind"] == "non_target")
        self.assertFalse(target["explicit_speaker_attribution"])
        self.assertTrue(guest["explicit_speaker_attribution"])
        self.assertNotIn("conflicting_attribution", result.outcomes)

    def test_attached_month_suffix_is_not_part_of_the_person_name(self) -> None:
        result = analyze(metadata("A Message By Pastor George Bulgin-June 20, 2026"), proposed())

        self.assertEqual("george bulgin", result.correlation_groups[0]["normalized_person_name"])

    def test_overlapping_caption_repetitions_collapse_to_one_spoken_observation(self) -> None:
        result = analyze(
            metadata("Worship Service"),
            proposed(
                (100.0, 103.0, "Our speaker today is Elder Robert McLean."),
                (103.0, 106.0, "Our speaker today is Elder Robert McLean. Please welcome him."),
            ),
        )

        self.assertEqual(1, len(result.observations))
        self.assertEqual(1, result.correlation_groups[0]["observation_count"])


if __name__ == "__main__":
    unittest.main()
