"""Review the fresh-source discovery proposal; no evaluation or inference runner."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

from pastor_transcript_extractor import g3_atomic_admission as a1
from pastor_transcript_extractor import g3_atomic_admission_decision as decision
from pastor_transcript_extractor.config import build_paths

ROOT = decision.design.ROOT
HERE = ROOT / 'docs/review-proposals/fresh-discovery-readiness-v1'
PLAN = HERE / 'plan-v1.json'
MANIFEST = HERE / 'source-manifest-v1.json'


def validate(plan, manifest):
    accepted = decision.accepted_decision()
    if (accepted is None or plan['parent_acceptance_fingerprint'] != accepted['content_fingerprint']
            or plan['source_manifest_fingerprint'] != manifest['content_fingerprint']
            or plan['status'] != 'PROPOSED_NOT_EXECUTED'
            or plan['authorization'] != dict(proposal_preparation=True, evaluation_execution=False,
                provider_calls=False, automatic_attestation=False, discovery_tuning=False,
                broader_collection=False, projection_scoring=False)):
        raise ValueError('Fresh proposal authority/binding changed')
    sources = manifest['sources']
    if (len(sources) != 4 or [s['role'] for s in sources] != ['primary']*3 + ['technical_reserve_only']
            or len({s['source_id'] for s in sources}) != 4
            or len({s['youtube_video_id'] for s in sources}) != 4
            or any(s['video_id'] in manifest['development_video_ids']
                   or s['source_id'] in manifest['development_source_ids'] for s in sources)
            or any(s['prior_sermon_analysis_runs'] != 0 for s in sources)
            or any(s['existing_disposition'] != 'accepted_sermon' or s['existing_guest_flag'] is not False for s in sources)):
        raise ValueError('Sources are not distinct fresh primary/reserve sermons')
    for s in sources:
        if s['selection_sha256'] != hashlib.sha256((manifest['selection_salt'] + s['youtube_video_id']).encode()).hexdigest():
            raise ValueError('Metadata-only selection identity changed')
    if [s['selection_sha256'] for s in sources] != sorted(s['selection_sha256'] for s in sources):
        raise ValueError('Metadata selection order changed')
    b = plan['bounds']
    quotas = plan['semantic_queue']['per_source']
    if (b['primary_sermons'] != 3 or b['semantic_candidate_units_total'] != 120
            or b['semantic_requests_max'] != 240 or b['automatic_retries'] != 0
            or b['G2_G3_candidates_total'] != 20000 or b['G2_G3_candidates_per_source'] != 12000
            or sum(quotas.values()) != b['semantic_candidate_units_per_source']
            or b['primary_sermons'] * b['semantic_candidate_units_per_source'] != 120
            or plan['proposed_criteria']['unsupported_admissions_max'] != 0
            or plan['proposed_criteria']['silent_truncation_max'] != 0):
        raise ValueError('Proposed bounded evaluation criteria changed')
    if plan['freeze_order'][:2] != ['Source manifest and baseline code/policy first',
            'Natural candidate inventory, ranked provider queue and automatic envelopes sealed before references exist']:
        raise ValueError('Discovery/reference separation lost')
    if not plan['integration_gap'] or not plan['limitations']:
        raise ValueError('Readiness limitations missing')


def verify(base_dir=None):
    plan, manifest = a1.v4.sealed(PLAN), a1.v4.sealed(MANIFEST)
    validate(plan, manifest)
    for name, digest in plan['pins'].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or a1.file_hash(path) != digest:
            raise ValueError('Pinned baseline or accepted containment evidence changed')
    paths = build_paths(base_dir)
    with sqlite3.connect(paths.database.as_uri() + '?mode=ro', uri=True) as connection:
        for source in manifest['sources']:
            row = connection.execute('select source_id,youtube_video_id,title from videos where id=?',
                                     (source['video_id'],)).fetchone()
            if row != (source['source_id'], source['youtube_video_id'], source['title']):
                raise ValueError('Source metadata identity changed')
            if connection.execute('select count(*) from sermon_analysis_runs where video_id=?',
                                  (source['video_id'],)).fetchone()[0] != 0:
                raise ValueError('Fresh source now has prior semantic analysis; review exposure before evaluation')
            for key, digest in source['file_hashes'].items():
                if a1.file_hash(Path(source[key])) != digest:
                    raise ValueError('Pinned fresh transcript/extraction changed')
            extracted = json.loads(Path(source['proposed_json_path']).read_text())
            if (extracted['final_disposition']['status'] != 'accepted_sermon'
                    or extracted['guest_speaker_suspected'] is not False):
                raise ValueError('Existing source-readiness metadata changed')
    return plan, manifest
