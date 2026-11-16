"""One command over the paid steps B, D and E; every step keeps its own reservations, receipts and stop rules."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import extract, leaf_pass, strata, verify
from .common import file_sha256, read_json
from .ledger import PilotLedger
from .leaf_pass import DEFAULT_PACKS


def run(pilot: Path, approved_sha256: str, *, check_only: bool = False) -> dict[str, Any]:
    """leaf signals, strata, Pro and Flash extraction, then verification; halts at the first stop or failure."""
    pilot = Path(pilot).resolve()
    ledger = PilotLedger(pilot / 'ledger.json')
    slice_path = pilot / 'slice.json'
    done: dict[str, Any] = {}
    plan_path = pilot / 'plan.json'
    if plan_path.exists():
        # The leaf table embeds the ledger summary, so regenerating it changes strata.json, and every extraction
        # request fingerprint includes the strata hash; once frozen, upstream output is verified, never rebuilt.
        frozen = read_json(plan_path)['strata_sha256']
        if not (pilot / 'strata.json').exists() or file_sha256(pilot / 'strata.json') != frozen:
            raise ValueError('strata.json differs from the frozen plan; leaf and strata output is not regenerated once a plan is frozen')
        done['leaf'] = done['strata'] = dict(status='frozen_by_plan', strata_sha256=frozen)
    else:
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
