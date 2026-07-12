from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from pastor_transcript_extractor.config import LlmConfig
from pastor_transcript_extractor.local_llm import LocalLlmError, OllamaClient


class FakeHttpResponse:
    def __init__(self, payload: object) -> None:
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> FakeHttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def config() -> LlmConfig:
    return LlmConfig(
        enabled=True,
        base_url="http://127.0.0.1:11434",
        model="fixture:4b",
        timeout_seconds=1.0,
        prompt_version="test-v1",
        context_size=4096,
    )


class OllamaClientTests(unittest.TestCase):
    def test_health_reports_unavailable_server_without_raising(self) -> None:
        with patch("pastor_transcript_extractor.local_llm.urlopen", side_effect=URLError("offline")):
            health = OllamaClient(config()).check_health()

        self.assertFalse(health.reachable)
        self.assertFalse(health.model_available)
        self.assertFalse(health.structured_output)
        self.assertIn("unreachable", health.detail)

    def test_health_reports_missing_configured_model(self) -> None:
        response = FakeHttpResponse({"models": [{"name": "another:4b"}]})
        with patch("pastor_transcript_extractor.local_llm.urlopen", return_value=response):
            health = OllamaClient(config()).check_health()

        self.assertTrue(health.reachable)
        self.assertFalse(health.model_available)
        self.assertIn("not installed", health.detail)

    def test_health_proves_schema_constrained_generation(self) -> None:
        responses = [
            FakeHttpResponse({"models": [{"model": "fixture:4b"}]}),
            FakeHttpResponse(
                {
                    "model": "fixture:4b",
                    "message": {"content": '{"status":"ok"}'},
                }
            ),
        ]
        with patch("pastor_transcript_extractor.local_llm.urlopen", side_effect=responses):
            health = OllamaClient(config()).check_health()

        self.assertTrue(health.reachable)
        self.assertTrue(health.model_available)
        self.assertTrue(health.structured_output)
        self.assertEqual("ready", health.detail)

    def test_generate_json_rejects_malformed_model_content(self) -> None:
        response = FakeHttpResponse({"message": {"content": "not-json"}})
        with patch("pastor_transcript_extractor.local_llm.urlopen", return_value=response):
            with self.assertRaisesRegex(LocalLlmError, "invalid structured JSON"):
                OllamaClient(config()).generate_json("classify", {"type": "object"})

    def test_generate_json_accepts_single_fenced_json_object(self) -> None:
        response = FakeHttpResponse(
            {"model": "fixture:4b", "message": {"content": "```json\n{\"status\":\"ok\"}\n```"}}
        )
        with patch("pastor_transcript_extractor.local_llm.urlopen", return_value=response):
            result = OllamaClient(config()).generate_json("check", {"type": "object"})

        self.assertEqual({"status": "ok"}, result.content)


if __name__ == "__main__":
    unittest.main()
