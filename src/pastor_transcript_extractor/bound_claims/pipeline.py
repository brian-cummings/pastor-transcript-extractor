"""One command over the paid steps B, D and E; every step keeps its own reservations, receipts and stop rules."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import extract, leaf_pass, strata, verify
from .ledger import PilotLedger
from .leaf_pass import DEFAULT_PACKS


def run(pilot: Path, approved_sha256: str, *, check_only: bool = False) -> dict[str, Any]:
    """leaf signals, strata, Pro and Flash extraction, then verification; halts at the first stop or failure."""
    pilot = Path(pilot).resolve()
    ledger = PilotLedger(pilot / 'ledger.json')
    slice_path = pilot / 'slice.json'
    done: dict[str, Any] = {}
    done['leaf'] = leaf_pass.run(slice_path, approved_sha256, ledger, check_only=check_only, letters=DEFAULT_PACKS)
    if check_only:
        return dict(status='CHECK_ONLY', steps=done, note='Later steps need the leaf table; run without --check-only.')
    done['strata'] = strata.run(slice_path, pilot / 'leaf' / 'leaf_observations.json', pilot / 'strata.json')
    for producer in ('pro', 'flash'):
        done['extract_' + producer] = result = extract.run(pilot / 'strata.json', producer, ledger)
        if result['stopped']:
            return dict(status='STOPPED', stopped_at='extract_' + producer, reason=result['stopped'], steps=done)
    done['verify'] = result = verify.run([pilot / 'extract' / p / 'extraction.json' for p in ('pro', 'flash')], ledger)
    if result['stopped']:
        return dict(status='STOPPED', stopped_at='verify', reason=result['stopped'], steps=done)
    return dict(status='COMPLETE', steps=done, ledger=ledger.summary(), next='pte analysis bound-claims review --pilot ' + str(pilot))
