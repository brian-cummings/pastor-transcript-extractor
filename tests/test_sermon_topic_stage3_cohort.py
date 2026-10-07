import json
import unittest
from pathlib import Path

from pastor_transcript_extractor.sermon_topics import TOPIC_PACK_VERSION


COHORT_PATH = (
    Path(__file__).parents[1]
    / "evaluation"
    / "sermon-topics"
    / "stage3-whole-sermon-cohort-v1.json"
)


class SermonTopicStage3CohortTests(unittest.TestCase):
    def test_cohort_is_balanced_unique_and_bound_to_current_pack(self) -> None:
        cohort = json.loads(COHORT_PATH.read_text(encoding="utf-8"))
        pastors = cohort["pastors"]
        sermons = [sermon for pastor in pastors for sermon in pastor["sermons"]]
        video_ids = [sermon["video_id"] for sermon in sermons]
        youtube_ids = [sermon["youtube_video_id"] for sermon in sermons]

        self.assertEqual(TOPIC_PACK_VERSION, cohort["question_pack_version"])
        self.assertEqual(4, len(pastors))
        self.assertTrue(all(len(pastor["sermons"]) == 3 for pastor in pastors))
        self.assertEqual(12, len(sermons))
        self.assertEqual(12, len(set(video_ids)))
        self.assertEqual(12, len(set(youtube_ids)))
        self.assertEqual(
            {1200, 4394, 4430, 4589},
            set(cohort["selection_contract"]["double_review_video_ids"]),
        )
        self.assertEqual(
            0,
            sum(not sermon["v3_topic_analysis_present"] for sermon in sermons),
        )
        self.assertTrue(all(sermon.get("series_key") for sermon in sermons))
        self.assertEqual(
            4,
            sum(sermon.get("period_key") is not None for sermon in sermons),
        )


if __name__ == "__main__":
    unittest.main()
