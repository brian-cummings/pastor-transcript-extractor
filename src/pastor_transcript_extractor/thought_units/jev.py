"""Batched Jev Noul requests with an immutable answer cache and the pilot ledger. A failed call is an error, never an answer."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

from pastor_transcript_extractor.bound_claims.common import digest, read_json, write_json
from pastor_transcript_extractor.bound_claims.ledger import PilotLedger, list_price_usd

MODEL = 'jev-1.13.0'
INPUT_USD_PER_MILLION = '0.042'
REQUEST_TOKEN_LIMIT = 65536          # per-request input cap used by the pilot's reservations
BATCH_QUESTIONS = 75                 # project constant (docs set no question limit)
BATCH_TOKEN_TARGET = 40000           # stay well inside the 64k request limit
CHARACTERS_PER_TOKEN = 3.8
RESERVATION = list_price_usd(REQUEST_TOKEN_LIMIT, 0, INPUT_USD_PER_MILLION, '0')


def estimated_tokens(spec: Mapping[str, Any]) -> int:
    return int(len(str(spec)) / CHARACTERS_PER_TOKEN) + 20


def batches(questions: Mapping[str, Mapping[str, Any]]) -> list[list[str]]:
    result, current, tokens = [], [], 0
    for key, spec in questions.items():
        cost = estimated_tokens(spec)
        if current and (len(current) >= BATCH_QUESTIONS or tokens + cost > BATCH_TOKEN_TARGET):
            result.append(current)
            current, tokens = [], 0
        current.append(key)
        tokens += cost
    return result + ([current] if current else [])


def default_factory(model: str) -> tuple[Any, Callable[..., Any]]:
    import os
    if not os.environ.get('TYPESAFE_API_KEY'):
        raise RuntimeError('Set TYPESAFE_API_KEY before running a Jev step')
    try:
        from typesafe_sdk import Noul, TypeSafeClient  # type: ignore[import-not-found]
    except ImportError as error:
        raise RuntimeError("Install the optional dependency: pip install -e '.[typesafe]'") from error
    return TypeSafeClient(model=model, timeout=120.0), Noul


class Asker:
    def __init__(self, cache_path: Path, ledger: PilotLedger, state: Mapping[str, Any], *, model: str = MODEL,
                 factory: Callable[[str], tuple[Any, Callable[..., Any]]] = default_factory, label: str = 'boundary'):
        self.cache_path, self.ledger, self.state, self.model, self.factory, self.label = Path(cache_path), ledger, dict(state), model, factory, label
        self._cache = read_json(self.cache_path) if self.cache_path.exists() else {}
        self.requests = 0

    def key(self, spec: Mapping[str, Any]) -> str:
        return digest(dict(model=self.model, question=spec))

    def plan(self, questions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        pending = {k: v for k, v in questions.items() if self.key(v) not in self._cache}
        groups = batches(pending)
        tokens = sum(estimated_tokens(v) for v in pending.values()) + 100 * len(groups)
        return dict(questions=len(questions), cached=len(questions) - len(pending), requests=len(groups),
                    estimated_input_tokens=tokens,
                    estimated_usd=str(list_price_usd(tokens, 0, INPUT_USD_PER_MILLION, '0')),
                    worst_case_reserved_usd=str(RESERVATION * len(groups)))

    def ask(self, questions: Mapping[str, Mapping[str, Any]]) -> dict[str, float]:
        pending = {k: v for k, v in questions.items() if self.key(v) not in self._cache}
        groups = batches(pending)
        if groups:
            self.ledger.require_step('leaf', RESERVATION * len(groups), len(groups))
            client, noul = self.factory(self.model)
            for group in groups:
                entry = f"leaf/{self.label}/{digest([self.key(pending[k]) for k in group])[:16]}"
                self.ledger.reserve(entry, 'leaf', RESERVATION, questions=len(group), model=self.model)
                self.requests += 1
                try:
                    result = client.system_one(self.state, {k: noul(**pending[k]) for k in group}, model=self.model, timeout=120.0)
                except Exception as error:
                    self.ledger.resolve(entry, actual_usd=None, error=type(error).__name__)
                    raise
                tokens = getattr(getattr(result, 'usage', None), 'input_tokens', None)
                if type(tokens) is int and 0 <= tokens <= REQUEST_TOKEN_LIMIT:
                    self.ledger.resolve(entry, actual_usd=list_price_usd(tokens, 0, INPUT_USD_PER_MILLION, '0'), input_tokens=tokens, output_tokens=0)
                else:
                    self.ledger.resolve(entry, actual_usd=None, error='usage_missing')
                nouls = getattr(result, 'nouls', {})
                missing = [k for k in group if k not in nouls]
                if missing:
                    raise ValueError(f'Jev returned no answer for {len(missing)} of {len(group)} questions; nothing is guessed')
                for k in group:
                    self._cache[self.key(pending[k])] = float(nouls[k].noul)
                write_json(self.cache_path, self._cache)
        return {k: self._cache[self.key(v)] for k, v in questions.items()}
