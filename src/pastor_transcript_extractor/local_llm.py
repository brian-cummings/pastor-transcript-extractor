from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pastor_transcript_extractor.config import LlmConfig


class LocalLlmError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LocalLlmResponse:
    content: dict[str, Any]
    raw_content: str
    model: str


@dataclass(frozen=True, slots=True)
class LocalLlmHealth:
    reachable: bool
    model_available: bool
    structured_output: bool
    detail: str


class LocalLlmClient(Protocol):
    model: str

    def generate_json(self, prompt: str, schema: dict[str, Any]) -> LocalLlmResponse: ...


class OllamaClient:
    def __init__(self, config: LlmConfig) -> None:
        self.config = config
        self.model = config.model
        self._model_digest: str | None = None

    def model_digest(self) -> str:
        if self._model_digest is not None:
            return self._model_digest
        request = Request(f"{self.config.base_url}/api/tags", method="GET")
        try:
            with urlopen(request, timeout=min(self.config.timeout_seconds, 5.0)) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise LocalLlmError(f"Could not resolve Ollama model digest: {error}") from error
        models = payload.get("models") if isinstance(payload, dict) else None
        if isinstance(models, list):
            for item in models:
                if not isinstance(item, dict):
                    continue
                name = item.get("model") or item.get("name")
                digest = item.get("digest")
                if name == self.model and isinstance(digest, str) and digest:
                    self._model_digest = digest
                    return digest
        raise LocalLlmError(f"Could not find digest for configured model {self.model!r}")

    def check_health(self) -> LocalLlmHealth:
        request = Request(f"{self.config.base_url}/api/tags", method="GET")
        try:
            with urlopen(request, timeout=min(self.config.timeout_seconds, 5.0)) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            return LocalLlmHealth(False, False, False, f"Ollama is unreachable: {error}")

        models = payload.get("models") if isinstance(payload, dict) else None
        available_names = {
            str(item.get("model") or item.get("name"))
            for item in models
            if isinstance(item, dict) and (item.get("model") or item.get("name"))
        } if isinstance(models, list) else set()
        if self.model not in available_names:
            return LocalLlmHealth(
                True,
                False,
                False,
                f"configured model {self.model!r} is not installed",
            )

        schema = {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["ok"]}},
            "required": ["status"],
        }
        try:
            result = self.generate_json('Return {"status":"ok"}.', schema)
        except (LocalLlmError, ValueError) as error:
            return LocalLlmHealth(True, True, False, f"structured output check failed: {error}")
        if result.content.get("status") != "ok":
            return LocalLlmHealth(True, True, False, "structured output check returned an unexpected value")
        return LocalLlmHealth(True, True, True, "ready")

    def generate_json(self, prompt: str, schema: dict[str, Any]) -> LocalLlmResponse:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": schema,
                "options": {"temperature": 0, "num_predict": 256, "num_ctx": self.config.context_size},
            }
        ).encode("utf-8")
        request = Request(
            f"{self.config.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                envelope = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise LocalLlmError(f"Ollama request failed: {error}") from error
        raw_content = envelope.get("message", {}).get("content")
        if not isinstance(raw_content, str):
            raise LocalLlmError("Ollama response did not contain message.content")
        candidate = raw_content.strip()
        if candidate.startswith("```") and candidate.endswith("```"):
            lines = candidate.splitlines()
            if len(lines) >= 3 and lines[0].strip() in {"```", "```json"}:
                candidate = "\n".join(lines[1:-1]).strip()
        try:
            content = json.loads(candidate)
        except json.JSONDecodeError as error:
            snippet = " ".join(raw_content.split())[:240]
            raise LocalLlmError(
                f"Ollama returned invalid structured JSON ({error.msg} at character {error.pos}): {snippet!r}"
            ) from error
        if not isinstance(content, dict):
            raise LocalLlmError("Ollama structured response was not an object")
        return LocalLlmResponse(content=content, raw_content=raw_content, model=str(envelope.get("model") or self.model))
