"""Re-freeze the pilot plan at a new commit without discarding paid extraction or verification output.

`supersede` sets a plan and its paid outputs aside; `amend` is for a change that does not touch any request (here a
ceiling), so every receipt stays valid. The old plan is archived, the ledger adopts the current ceiling, and the new plan
records what it amends. Spend, entries and cached responses are untouched.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any, Callable, Mapping

from pastor_transcript_extractor import deepinfra_requests as provider

from .common import file_sha256, read_json, write_json
from .extract import freeze_plan, git_state
from .ledger import PilotLedger


def run(pilot: Path, reason: str, *, state: Callable[[], dict[str, Any]] = git_state,
        metadata: Callable[[str], Mapping[str, Any]] = provider.public_model_metadata) -> dict[str, Any]:
    pilot = Path(pilot).resolve()
    if not reason.strip():
        raise ValueError('A reason is required')
    plan_path = pilot / 'plan.json'
    if not plan_path.exists():
        raise ValueError('No frozen plan to amend')
    old = read_json(plan_path)
    current = state()
    if current['dirty']:
        raise ValueError('Uncommitted source changes: commit the implementation before amending the plan')
    if old['implementation']['src_tree'] == current['src_tree']:
        raise ValueError('The frozen plan already matches the current implementation')
    destination = pilot / 'amended' / old['content_fingerprint'][:12]
    if destination.exists():
        raise ValueError(f'Already amended: {destination}')
    ledger = PilotLedger(pilot / 'ledger.json')
    amendment = dict(reason=reason.strip(), amended_at=datetime.now(timezone.utc).isoformat(),
                     amends_plan=old['content_fingerprint'], amends_implementation=old['implementation'],
                     previous_ceiling=old['ceiling'], requests_changed=False)
    destination.mkdir(parents=True)
    shutil.move(str(plan_path), destination / 'plan.json')
    previous = ledger.adopt_ceiling()
    amendment['previous_ledger_ceiling'] = previous
    strata_path = pilot / 'strata.json'
    plan = freeze_plan(pilot, old['slice_sha256'], file_sha256(strata_path), ledger, state, metadata, amendment=amendment)
    write_json(destination / 'AMENDED.json', dict(amendment, new_plan=plan['content_fingerprint'], new_implementation=plan['implementation']))
    return dict(amendment, destination=str(destination), new_plan=plan['content_fingerprint'], new_implementation=plan['implementation'],
                ledger=ledger.summary(), next='Run the pilot again; cached extraction and leaf output are reused.')
