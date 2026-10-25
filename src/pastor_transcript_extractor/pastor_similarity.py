"""Explainable scoped operators, without a cross-family score or ranking."""
from dataclasses import dataclass
from .pastor_evidence import digest
from .pastor_fingerprint import project_dimension


@dataclass(frozen=True)
class ComparisonSpec:
    path: str = 'theology'
    requested_positions: tuple[str, ...] | None = None
    requested_emphasis: tuple[str, ...] | None = None
    requested_relations: tuple[str, ...] | None = None
    requested_forms: tuple[str, ...] | None = None
    version: str = 'unique-feature-unit-weight-v1'


def _ratio(n, d):
    return n/d if d else None


def _inventory(left, right, operator, requested):
    return sorted(set(requested if requested is not None else left[operator]+right[operator]))


def compare_fingerprints(left, right, comparison_spec=ComparisonSpec()):
    if left['schema_version'] != right['schema_version'] or left['dimension_policy'] != right['dimension_policy']:
        raise ValueError('Fingerprint contract/policy mismatch')
    if left['evidence_policy'] != right['evidence_policy']:
        raise ValueError('Evidence policies differ')
    spec = comparison_spec
    lview, rview = project_dimension(left, spec.path), project_dimension(right, spec.path)
    requested = _inventory(lview, rview, 'position', spec.requested_positions)
    common, exclusions, contributions = [], [], []
    for key in requested:
        a, b = left['claim_frames'].get(key), right['claim_frames'].get(key)
        reason = None
        if key not in lview['position'] or key not in rview['position']: reason = 'missing_or_outside_dimension'
        elif a['meaning'] != b['meaning']: reason = 'qualified_difference'
        elif a['state'] not in ([1,0],[0,1]) or b['state'] not in ([1,0],[0,1]): reason = 'neither_both_or_withheld'
        if reason:
            exclusions.append(dict(id=key, reason=reason, left=a, right=b)); continue
        common.append(key)
        contributions.append(dict(id=key, meaning=a['meaning'], weight=1,
            left=a['state'], right=b['state'], agrees=a['state']==b['state'],
            left_sources=a, right_sources=b))
    agreement = sum(r['agrees'] for r in contributions)
    result = dict(path=spec.path, comparison_policy=spec.version, position_metrics=dict(
        agreement=_ratio(agreement,len(common)), opposition=_ratio(len(common)-agreement,len(common)),
        coverage=_ratio(len(common),len(requested)), agreement_numerator=agreement,
        opposition_numerator=len(common)-agreement, denominator=len(common), requested_denominator=len(requested),
        requested_mask=requested, common_mask=common, exclusions=exclusions,
        feature_contributions=contributions, reason=None if common else 'insufficient_comparability'))
    for op, mask in [('emphasis',spec.requested_emphasis),('relation',spec.requested_relations),('form',spec.requested_forms)]:
        requested = _inventory(lview,rview,op,mask)
        rows, excluded = [], []
        for key in requested:
            a,b = left['features'][op].get(key),right['features'][op].get(key)
            if key not in lview[op] or key not in rview[op]: reason='unmeasured_or_outside_dimension'
            elif (a['contract'],a['estimand']) != (b['contract'],b['estimand']): reason='incompatible_measurement'
            else: reason=None
            if reason:
                excluded.append(dict(id=key,reason=reason)); continue
            rows.append(dict(id=key,weight=1,delta=abs(a['value']-b['value']),
                left=a['value'],right=b['value'],left_sources=a,right_sources=b))
        distance = _ratio(sum(r['delta'] for r in rows),len(rows))
        result[op+'_metrics'] = dict(distance=distance,resemblance=1-distance if distance is not None else None,
            difference_numerator=sum(r['delta'] for r in rows),denominator=len(rows),
            requested_denominator=len(requested), coverage=_ratio(len(rows),len(requested)),
            requested_mask=requested,common_mask=[r['id'] for r in rows],exclusions=excluded,
            feature_contributions=rows, reason=None if rows else 'insufficient_comparability')
    result['uncertainty'] = dict(left=left['uncertainty'],right=right['uncertainty'],
        interpretation='sample_scoped; unknown_is_not_opposition; no_overall_score')
    result['inventory_fingerprint'] = digest({k:v['requested_mask'] for k,v in result.items() if k.endswith('_metrics')})
    return result


def compare_panel(candidate, members, spec):
    """Pair-specific display seam; panel membership is supplied, never ranked."""
    return dict(rankable=False, mask_policy='pair_specific',
        comparisons=[compare_fingerprints(candidate, member, spec) for member in members])
