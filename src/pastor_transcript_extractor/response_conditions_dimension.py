"""Sample-scoped response/conditions contract over the existing section workflow."""
from dataclasses import asdict
import json
from pathlib import Path

from . import profile_section as section
from .pastor_evidence import EvidenceArtifactStore as Store, digest
from .profile_support_validation import file_hash

VERSION = 'response-conditions-dimension-v1'
SELECTION = 'response-conditions-confirmation-coordinate-hash-v1'


def select_confirmation(sermons):
    """Choose four disjoint three-block windows without inspecting any answers/text."""
    candidates = []
    development = {(v, b) for v, first, last in section.WINDOWS for b in range(first, last+1)}
    for source in sorted(sermons, key=lambda s: s['video_id']):
        vid = source['video_id']; eligible = set(source['eligible_block_ids'])
        for first in sorted(eligible):
            ids = tuple(range(first, first+3))
            if not set(ids) <= eligible or any((vid, b) in development for b in ids):
                continue
            candidates.append(dict(video_id=vid, first=first, last=first+2,
                rank=digest(dict(rule=SELECTION, video_id=vid, first=first))))
    selected = []; used = set()
    # One per recording first, then one additional hash-ranked window.
    for vid in sorted({c['video_id'] for c in candidates}) + [None]:
        for c in sorted(candidates, key=lambda c: c['rank']):
            if vid is not None and c['video_id'] != vid:
                continue
            keys = {(c['video_id'], b) for b in range(c['first'], c['last']+1)}
            if used & keys:
                continue
            selected.append(c); used.update(keys); break
    if len(selected) != 4:
        raise ValueError('Four disjoint confirmation windows unavailable')
    return selected


def freeze_confirmation(base_dir, objective, predecessor):
    """Freeze coordinates before producer revision; disclose conservative exposure."""
    inv = section.inventory(base_dir)
    chosen = select_confirmation(inv['sermons'])
    prior = json.loads(Path(predecessor).read_text())
    known = {t['id'] for t in prior['tasks']}
    for c in chosen:
        c['id'] = f"v{c['video_id']}b{c['first']}-{c['last']}"
        c['exposure'] = dict(exact_window_in_predecessor=c['id'] in known,
            recording_previously_reviewed=True, untouched=False,
            block_exposure='Not established as unseen; conservatively treated as exposed existing material.',
            independent_selection='Coordinates and eligibility only; no generated answers or source meaning used.')
    packet = dict(version=VERSION, selection_rule=SELECTION,
        objective=dict(path=str(Path(objective).resolve()), sha256=file_hash(objective)),
        predecessor=dict(path=str(Path(predecessor).resolve()), sha256=file_hash(predecessor)),
        inventory_fingerprint=inv['content_fingerprint'], confirmation=chosen,
        development=[list(w) for w in section.WINDOWS],
        sources=[{k:s[k] for k in ('video_id','source_path','source_sha256')} for s in inv['sermons']],
        producer_before_revision=file_hash(section.producer.__file__),
        meaning='Specific requested or described local responses with all attached meaning-changing restrictions, voice, adoption and polarity. No uptake or ministry-level trait.',
        representation='Set of qualified local response records; numeric pastor score is null.',
        opportunities='Each frozen window is an inspection opportunity; at most two producer-selected complete points per window. Not exhaustive response enumeration.',
        aggregation='Retain source-ordered local values, group by recording/window and disclose missingness. No occurrence rate, scalar, probability average or distance.',
        missingness='Separate no proposed response, unresolved/incorrect proposal, source failure, support withholding and not inspected. Unknown is not zero.',
        abstention='Require unchanged independent correctness and specific-presence checks at .90 plus ordinary support for readable release; complete-binding admission remains separate.',
        confirmation_policy='Freeze implementation before opening confirmation outputs; evaluate unchanged; no tuning against confirmation.',
        limits='Additional independently selected windows in already exposed recordings; not untouched material, population validation or production admission.',
        budgets=dict(provider_usd='5', maximum_batch_usd='.50', semantic_revisions=3,
            assistant_tokens=200000, maximum_helpers=2, maximum_tokens_per_helper=20000))
    packet['fingerprint'] = digest(packet)
    root = Path(base_dir)/'evaluation'/VERSION/'confirmation-freeze'/packet['fingerprint']
    Store(root).write_immutable('freeze.json', packet)
    (root/'freeze.md').write_text('# Frozen confirmation selection\n\n'+packet['limits']+'\n\n'+
        '\n'.join('- '+c['id']+' — previously exposed recording; unseen-block status unproven.' for c in chosen)+'\n')
    return dict(freeze=str(root/'freeze.json'), fingerprint=packet['fingerprint'],
        windows=[c['id'] for c in chosen], provider_calls=0)
