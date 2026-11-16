"""One durable pilot ledger: ceiling, reservations and attempt counting for steps B, D and E.

A request reserves its worst case before dispatch. When provider usage is
known the reservation is replaced by known list-price usage; unresolved usage
keeps its full reservation forever. Cache hits never reach the ledger.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
from pathlib import Path
from typing import Any

from .common import read_json, write_json

VERSION = 'bound-claim-pilot-ledger-v1'
CEILING_USD = Decimal('5.00')
CEILING_ATTEMPTS = 600
STEPS = ('leaf', 'extract_pro', 'extract_flash', 'verify')
CENT = Decimal('0.000000001')


def list_price_usd(input_tokens: int, output_tokens: int, input_per_million: str, output_per_million: str) -> Decimal:
    return (Decimal(input_tokens) * Decimal(input_per_million) + Decimal(output_tokens) * Decimal(output_per_million)) / Decimal(1_000_000)


class CeilingExceeded(ValueError):
    pass


class PilotLedger:
    def __init__(self, path: Path, *, ceiling_usd: Decimal = CEILING_USD, ceiling_attempts: int = CEILING_ATTEMPTS):
        self.path = Path(path)
        self.ceiling_usd = Decimal(ceiling_usd)
        self.ceiling_attempts = ceiling_attempts

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_name(self.path.name + '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return dict(version=VERSION, ceiling_usd=str(self.ceiling_usd), ceiling_attempts=self.ceiling_attempts, entries={})
        ledger = read_json(self.path)
        if (ledger.get('version') != VERSION or Decimal(ledger['ceiling_usd']) != self.ceiling_usd
                or ledger['ceiling_attempts'] != self.ceiling_attempts):
            raise ValueError('Ledger ceiling or version differs from the frozen pilot')
        return ledger

    @staticmethod
    def _committed(ledger: dict[str, Any]) -> Decimal:
        total = Decimal(0)
        for entry in ledger['entries'].values():
            total += Decimal(entry['actual_usd'] if entry['status'] == 'resolved' else entry['reserved_usd'])
        return total

    def committed_usd(self) -> Decimal:
        return self._committed(self._read())

    def attempt_count(self) -> int:
        return len(self._read()['entries'])

    def entry_status(self, entry_id: str) -> str | None:
        entry = self._read()['entries'].get(entry_id)
        return None if entry is None else entry['status']

    def entry_count(self, prefix: str) -> int:
        return sum(key.startswith(prefix) for key in self._read()['entries'])

    def remaining(self) -> tuple[Decimal, int]:
        ledger = self._read()
        return self.ceiling_usd - self._committed(ledger), self.ceiling_attempts - len(ledger['entries'])

    def require_step(self, step: str, worst_usd: Decimal, worst_attempts: int) -> None:
        """A step refuses to start when its whole worst case cannot fit the remaining ceiling."""
        remaining_usd, remaining_attempts = self.remaining()
        if worst_usd > remaining_usd or worst_attempts > remaining_attempts:
            raise CeilingExceeded(
                f'{step} worst case ${worst_usd} / {worst_attempts} attempts exceeds remaining '
                f'${remaining_usd} / {remaining_attempts} attempts of the ${self.ceiling_usd} / {self.ceiling_attempts} pilot ceiling')

    def reserve(self, entry_id: str, step: str, reserved_usd: Decimal, **detail: Any) -> None:
        if step not in STEPS:
            raise ValueError('Unknown pilot step')
        with self._locked():
            ledger = self._read()
            if entry_id in ledger['entries']:
                raise ValueError('Attempt already reserved; a lost or repeated request is never retried: ' + entry_id)
            if (self._committed(ledger) + reserved_usd > self.ceiling_usd
                    or len(ledger['entries']) + 1 > self.ceiling_attempts):
                raise CeilingExceeded('Reservation would exceed the pilot ceiling')
            ledger['entries'][entry_id] = dict(step=step, status='reserved', reserved_usd=str(reserved_usd),
                reserved_at=datetime.now(timezone.utc).isoformat(), **detail)
            write_json(self.path, ledger)

    def resolve(self, entry_id: str, *, actual_usd: Decimal | None, input_tokens: int | None = None,
                output_tokens: int | None = None, **detail: Any) -> None:
        """Known usage replaces the reservation; unknown usage keeps it."""
        with self._locked():
            ledger = self._read()
            entry = ledger['entries'][entry_id]
            if entry['status'] != 'reserved':
                raise ValueError('Attempt already resolved')
            if actual_usd is not None and actual_usd > Decimal(entry['reserved_usd']):
                raise ValueError('Known usage exceeds its reservation; ledger kept at the reservation')
            if actual_usd is None:
                entry.update(status='usage_unknown', **detail)
            else:
                entry.update(status='resolved', actual_usd=str(actual_usd.quantize(CENT)), input_tokens=input_tokens,
                             output_tokens=output_tokens, resolved_at=datetime.now(timezone.utc).isoformat(), **detail)
            write_json(self.path, ledger)

    def supersede(self, steps: tuple[str, ...], tag: str) -> list[str]:
        """Move finished attempts of `steps` under a superseded key; their spend and attempts still count toward the ceiling."""
        with self._locked():
            ledger = self._read()
            moved = [key for key, entry in ledger['entries'].items() if entry['step'] in steps]
            for key in moved:
                entry = ledger['entries'].pop(key)
                entry.update(superseded_step=entry['step'], step='superseded_' + entry['step'])
                ledger['entries'][f'superseded/{tag}/{key}'] = entry
            write_json(self.path, ledger)
        return moved

    def summary(self) -> dict[str, Any]:
        ledger = self._read()
        steps: dict[str, dict[str, Any]] = {}
        for entry in ledger['entries'].values():
            row = steps.setdefault(entry['step'], dict(attempts=0, known_usd=Decimal(0), reserved_unresolved_usd=Decimal(0),
                                                       unresolved=0, input_tokens=0, output_tokens=0))
            row['attempts'] += 1
            if entry['status'] == 'resolved':
                row['known_usd'] += Decimal(entry['actual_usd'])
                row['input_tokens'] += entry.get('input_tokens') or 0
                row['output_tokens'] += entry.get('output_tokens') or 0
            else:
                row['unresolved'] += 1
                row['reserved_unresolved_usd'] += Decimal(entry['reserved_usd'])
        for row in steps.values():
            row['known_usd'] = str(row['known_usd'])
            row['reserved_unresolved_usd'] = str(row['reserved_unresolved_usd'])
        return dict(ceiling_usd=str(self.ceiling_usd), ceiling_attempts=self.ceiling_attempts,
                    attempts=len(ledger['entries']), committed_usd=str(self._committed(ledger)), steps=steps)
