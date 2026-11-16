"""Set aside a frozen plan and its downstream paid outputs so a corrected implementation can be frozen anew.

Nothing is deleted: the plan, extraction and verification directories move under `superseded/<plan>/`, and their
ledger entries are renamed but still count toward the ceiling. Human labels are never moved.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any

from .common import read_json, write_json
from .ledger import PilotLedger

DOWNSTREAM = ('extract', 'verify')
LEDGER_STEPS = ('extract_pro', 'extract_flash', 'verify')
LABELLED = ('review.json', 'decisions.jsonl')


def run(pilot: Path, reason: str) -> dict[str, Any]:
    pilot = Path(pilot).resolve()
    if not reason.strip():
        raise ValueError('A reason is required')
    plan_path = pilot / 'plan.json'
    if not plan_path.exists():
        raise ValueError('No frozen plan to supersede')
    labelled = [name for name in LABELLED if (pilot / name).exists()]
    if labelled:
        raise ValueError('Review artifacts exist (' + ', '.join(labelled) + '); labels are never superseded')
    plan = read_json(plan_path)
    tag = plan['content_fingerprint'][:12]
    destination = pilot / 'superseded' / tag
    if destination.exists():
        raise ValueError(f'Already superseded: {destination}')
    destination.mkdir(parents=True)
    ledger = PilotLedger(pilot / 'ledger.json')
    moved_entries = ledger.supersede(LEDGER_STEPS, tag)
    moved = ['plan.json']
    shutil.move(str(plan_path), destination / 'plan.json')
    for name in DOWNSTREAM:
        if (pilot / name).exists():
            shutil.move(str(pilot / name), destination / name)
            moved.append(name)
    note = dict(reason=reason.strip(), superseded_at=datetime.now(timezone.utc).isoformat(), plan_fingerprint=plan['content_fingerprint'],
                implementation=plan['implementation'], moved=moved, ledger_entries=moved_entries)
    write_json(destination / 'SUPERSEDED.json', note)
    return dict(note, destination=str(destination), ledger=ledger.summary(), next='Commit the corrected implementation, then run the pilot again.')
