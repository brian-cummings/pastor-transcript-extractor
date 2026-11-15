"""Step H: present human-accepted V4 Pro claims for one profile, grouped by area and object.

Presentation of labeled evidence only: no aggregation beyond grouping, no
interpretation, no frequency or dominance language and no quotation beyond the
claim's own `anchor_text`. It does not run the frozen `profile_section` workflow.

Contract gap: `profile_analysis_support.document_input` consumes plan items whose
claims carry model support judgments, assertion assessments and dependency states.
Bound claims carry human accept labels instead; mapping them into that shape would
invent judgments that were never made, so this module emits its own
document-input-shaped record (`SECTION_<profile>.json`) and Markdown.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.segment_profile_view import short_title, timestamp

from . import contract
from .common import read_json, write_json
from .review import load_decisions

VERSION = 'bound-claim-section-v1'
AREA_TITLES = dict(salvation='Salvation', assurance='Assurance', other_doctrine='Other doctrine',
                   public_life='Public life', pastoral_address='Pastoral address')
SCOPE = ('Each statement is a claim extracted from one block of one sermon in this sample and accepted by a human reviewer. '
         'It does not show how common, central or representative the statement is, or what the preacher believes overall.')
EMPTY = 'No accepted claims in this sample.'


def accepted_pro_claims(pilot: Path) -> dict[int, list[dict[str, Any]]]:
    """Human-accepted V4 Pro claims, by profile."""
    strata = {b['coordinate']: b for b in read_json(pilot / 'strata.json')['blocks']}
    extraction = read_json(pilot / 'extract' / 'pro' / 'extraction.json')
    decisions = load_decisions(pilot)
    verification = {}
    path = pilot / 'verify' / 'verification.json'
    if path.exists():
        verification = {row['fingerprint']: row['answers'] for row in read_json(path)['rows'] if row['status'] == 'ok'}
    by_profile: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in extraction['rows']:
        block = strata[row['coordinate']]
        for found in row['claims']:
            if decisions.get(found['fingerprint'], {}).get('decision') != 'accept':
                continue
            claim = found['claim']
            by_profile[block['profile_id']].append(dict(
                claim_id=found['fingerprint'], coordinate=row['coordinate'], video_id=block['video_id'], title=block['title'],
                watch_url=block['watch_url'], start_seconds=block['start_seconds'], stratum=block['stratum'],
                **{key: claim[key] for key in contract.FIELDS if key != 'anchor_offsets'},
                anchor_offsets=dict(start=found['anchor']['start'], end=found['anchor']['end']),
                review_decision='accept', verification_probabilities=verification.get(found['fingerprint'])))
    return by_profile


def choose_profile(by_profile: dict[int, list[dict[str, Any]]]) -> int:
    if not by_profile:
        raise ValueError('No accepted V4 Pro claims to render; complete the review first')
    return sorted(by_profile, key=lambda profile: (-len(by_profile[profile]), profile))[0]


def build_section(pilot: Path, profile: int | None = None) -> dict[str, Any]:
    by_profile = accepted_pro_claims(pilot)
    profile = choose_profile(by_profile) if profile is None else profile
    findings = sorted(by_profile.get(profile, []), key=lambda f: (f['area'], f['object'].lower(), f['video_id'], f['start_seconds']))
    if not findings:
        raise ValueError(f'Profile {profile} has no accepted V4 Pro claims')
    slice_ = read_json(pilot / 'slice.json')
    label = next((p['display_label'] for p in slice_['profiles'] if p['profile_id'] == profile), None) or f'Profile {profile}'
    sermons = [dict(video_id=s['video_id'], title=short_title(s['title']), url=s['url']) for s in slice_['sermons'] if s['profile_id'] == profile]
    groups = []
    for area in contract.AREAS:
        in_area = [f for f in findings if f['area'] == area]
        objects: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for finding in in_area:
            objects[finding['object'].strip().lower()].append(finding)
        groups.append(dict(area=area, title=AREA_TITLES[area], accepted_claims=len(in_area), message=None if in_area else EMPTY,
                           objects=[dict(object=name, claim_ids=[f['claim_id'] for f in items]) for name, items in sorted(objects.items())]))
    return seal(dict(
        version=VERSION, stage='bound_claims_labeled_evidence', profile_id=profile, label=label, sermons=sermons,
        scope=SCOPE, production_admission='not_admitted', origin='machine_extracted_human_accepted',
        contract_gap='profile_analysis_support.document_input requires model support judgments per claim; bound claims carry human labels, so no bridge was forced.',
        groups=groups, findings=findings, ready_claim_ids=[f['claim_id'] for f in findings]))


def _clauses(finding: dict[str, Any]) -> str:
    parts = [f"{finding['polarity']}", f"voiced by {finding['voiced_by'].replace('_', ' ')}",
             f"preacher {finding['preacher_adoption'].replace('_', ' ')}", f"role: {finding['speech_role'].replace('_', ' ')}"]
    return ' · '.join(parts)


def markdown(section: dict[str, Any]) -> str:
    findings = {f['claim_id']: f for f in section['findings']}
    lines = [f"# Bound claims: {section['label']}", '', section['scope'], '', '## Sermons in this sample', '']
    lines += [f"- [{s['title']}]({s['url']})" for s in section['sermons']]
    for group in section['groups']:
        lines += ['', f"## {group['title']}", '']
        if group['message']:
            lines += [group['message']]
            continue
        for obj in group['objects']:
            lines += [f"### {obj['object']}", '']
            for claim_id in obj['claim_ids']:
                f = findings[claim_id]
                lines.append(f"- **{f['proposition']}** ({_clauses(f)})")
                if f['conditions']:
                    lines.append('  - Conditions: ' + '; '.join(f['conditions']))
                if f['qualifications']:
                    lines.append('  - Qualifications: ' + '; '.join(f['qualifications']))
                if f['reasons']:
                    lines.append('  - Stated reasons: ' + '; '.join(f['reasons']))
                lines.append(f"  - Source: “{f['anchor_text']}” — [{short_title(f['title'])}, {timestamp(f['start_seconds'])}]({f['watch_url']})")
    return '\n'.join(lines) + '\n'


def run(pilot: Path, profile: int | None = None) -> dict[str, Any]:
    section = build_section(pilot, profile)
    json_path = pilot / f"SECTION_{section['profile_id']}.json"
    md_path = pilot / f"SECTION_{section['profile_id']}.md"
    write_json(json_path, section)
    md_path.write_text(markdown(section))
    return dict(profile_id=section['profile_id'], label=section['label'], accepted_claims=len(section['findings']),
                sermons_with_findings=len({f['video_id'] for f in section['findings']}),
                areas={g['area']: g['accepted_claims'] for g in section['groups']},
                section_md=str(md_path), section_json=str(json_path),
                next='Re-run `pte analysis bound-claims report` so criterion 3 reads this section.')
