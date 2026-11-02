from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.identity_prepared_profiles import PreparedProfileCache


class PreparedProfileCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.cache = PreparedProfileCache(Path(temporary.name))
        self.inputs = {"profile_id": 12, "members": [1, 2, 3]}
        self.result = {"selected_observation_ids": [1, 2, 3]}

    def test_snapshots_are_content_addressed_and_idempotent(self):
        self.assertFalse(self.cache.has_profile(12))
        self.cache.save("profile", self.inputs, self.result, profile_id=12)
        self.cache.save("profile", self.inputs, self.result, profile_id=12)
        self.assertTrue(self.cache.has_profile(12))
        self.assertEqual(self.result, self.cache.load("profile", self.inputs, profile_id=12))
        changed = {**self.inputs, "members": [1, 2, 4]}
        self.assertIsNone(self.cache.load("profile", changed, profile_id=12))
        self.cache.save("profile", changed, self.result, profile_id=12)
        self.assertEqual(2, len(list(self.cache.root.glob("profile-*/*.json"))))

    def test_conflicting_verified_result_is_not_overwritten(self):
        self.cache.save("profile", self.inputs, self.result, profile_id=12)
        with self.assertRaisesRegex(RuntimeError, "collision"):
            self.cache.save("profile", self.inputs, {"changed": True}, profile_id=12)
        self.assertEqual(self.result, self.cache.load("profile", self.inputs, profile_id=12))

    def test_malformed_and_tampered_snapshots_do_not_supply_results(self):
        self.cache.save("profile", self.inputs, self.result, profile_id=12)
        path = next(self.cache.root.glob("profile-*/*.json"))
        original = path.read_text()
        modified = json.loads(original)
        modified["result"] = {"selected_observation_ids": [999]}
        for text in (json.dumps(modified), "[]", "not json", "\udcff"):
            with self.subTest(text=repr(text)):
                path.write_bytes(text.encode("utf-8", errors="surrogatepass"))
                self.assertIsNone(self.cache.load("profile", self.inputs, profile_id=12))
                # Preserve even invalid historical artifacts.
                self.cache.save("profile", self.inputs, self.result, profile_id=12)
                self.assertEqual(text.encode("utf-8", errors="surrogatepass"), path.read_bytes())

    def test_members_are_independently_reusable_across_profiles(self):
        inputs = {"observation_fingerprint": "a", "audio_sha256": "b"}
        self.cache.save("member", inputs, {"spans": [[1, 2]]})
        self.assertEqual({"spans": [[1, 2]]}, self.cache.load("member", inputs))
        self.assertIsNone(self.cache.load("member", {**inputs, "audio_sha256": "changed"}))


if __name__ == "__main__":
    unittest.main()
