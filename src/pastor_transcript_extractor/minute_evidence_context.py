"""Canonical minute-block mapping and bounded context; no semantic inference."""
from __future__ import annotations
from collections import Counter
import hashlib

from pastor_transcript_extractor.caption_normalization import normalize_caption_fragments, NORMALIZER_VERSION
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal

POLICY = dict(version='minute-centered-canonical-context-v1',padding_seconds=120,characters_max=6000)


def validate_source(source, segments):
    """Prove canonical text/unit lineage from the persisted extraction, not a search."""
    if seal(source)!=source:raise ValueError('Source seal differs')
    normalized=normalize_caption_fragments((i,s['text']) for i,s in enumerate(segments))
    if source['text']!='\n'.join(u.text for u in normalized.units):
        raise ValueError('Canonical source differs from full-stream normalization')
    if source['normalization_diagnostics']['normalizer_version']!=NORMALIZER_VERSION:
        raise ValueError('Normalization version differs')
    if len(source['units'])!=len(normalized.units):raise ValueError('Unit inventory differs')
    cursor=0
    for unit, actual in zip(source['units'], normalized.units, strict=True):
        indexes=list(actual.source_segment_indexes)
        if (unit['start']!=cursor or unit['end']!=cursor+len(actual.text) or unit['text']!=actual.text
                or unit['source_segment_indexes']!=indexes
                or unit['start_seconds']!=min(segments[i]['start_seconds'] for i in indexes)
                or unit['end_seconds']!=max(segments[i]['end_seconds'] for i in indexes)):
            raise ValueError('Canonical unit coordinate/segment lineage differs')
        cursor=unit['end']+1
    if hashlib.sha256(source['text'].encode()).hexdigest()!=source['normalized_text_sha256']:
        raise ValueError('Canonical source text hash differs')
    return seal(dict(source_fingerprint=source['content_fingerprint'],text_sha256=source['normalized_text_sha256'],
                     normalizer_version=NORMALIZER_VERSION,segments_sha256=seal(dict(segments=segments))['content_fingerprint']))


def map_anchor(source,block,retained,source_proof):
    if seal(source_proof)!=source_proof or source_proof['source_fingerprint']!=source['content_fingerprint']:
        raise ValueError('Foreign source proof')
    base=dict(source_fingerprint=source['content_fingerprint'],source_proof_fingerprint=source_proof['content_fingerprint'],
              block_id=block.block_id,start_seconds=block.start_seconds,end_seconds=block.end_seconds,
              segment_indexes=list(block.segment_indexes),retained_identity=seal(dict(indexes=sorted(retained)))['content_fingerprint'])
    def defer(reason):return seal(dict(**base,status='deferred',reason=reason,center_ranges=[],usable_evidence=False))
    if not set(block.segment_indexes)<=set(retained):return defer('partial_or_absent_retained_membership')
    units=[u for u in source['units'] if set(u['source_segment_indexes'])&set(block.segment_indexes)]
    if not units:return defer('no_canonical_unit_mapping')
    # All contributing units must be complete. Repeated text cannot be resolved
    # by choosing its first occurrence or by stripping/normalizing a mismatch.
    if Counter(i for u in units for i in u['source_segment_indexes'])!=Counter(block.segment_indexes):
        return defer('partial_or_ambiguous_unit_membership')
    if block.start_seconds!=min(u['start_seconds'] for u in units) or block.end_seconds!=max(u['end_seconds'] for u in units):
        return defer('block_timestamp_lineage_differs')
    lo,hi=units[0]['start'],units[-1]['end']
    if block.text!=source['text'][lo:hi]:return defer('block_text_not_exact_canonical_slice')
    if not source['main_span']['start']<=lo<hi<=source['main_span']['end']:
        return defer('anchor_outside_reviewed_main_source')
    return seal(dict(**base,status='mapped',reason=None,center_ranges=[dict(start=lo,end=hi,text=block.text)],
                     source_unit_ids=[u['unit_id'] for u in units],timestamp_precision='contributing_segment_bounds_not_word_timestamps',usable_evidence=False))


def plan_context(source,anchor):
    if seal(anchor)!=anchor or anchor['source_fingerprint']!=source['content_fingerprint']:raise ValueError('Foreign anchor binding')
    if anchor['status']!='mapped':return seal(dict(status='deferred',reason=anchor['reason'],anchor_fingerprint=anchor['content_fingerprint']))
    lo,hi=anchor['center_ranges'][0]['start'],anchor['center_ranges'][-1]['end']
    if hi-lo>POLICY['characters_max']:
        return seal(dict(status='deferred',reason='complete_anchor_exceeds_6000',anchor_fingerprint=anchor['content_fingerprint']))
    units=[u for u in source['units'] if u['end_seconds']>anchor['start_seconds']-120 and u['start_seconds']<anchor['end_seconds']+120]
    wl=min(lo,min(u['start'] for u in units));wr=max(hi,max(u['end'] for u in units))
    budget=6000-(hi-lo);left=min(lo-wl,budget//2);right=min(wr-hi,budget-left);left=min(lo-wl,budget-right)
    a,b=lo-left,hi+right;budget_edges=[a,b]
    # Only optional context is cut; never alter a required anchor or nomination.
    text=source['text']
    while a<lo and a>0 and not text[a-1].isspace():a+=1
    while b>hi and b<len(text) and not text[b].isspace():b-=1
    if not a<=lo<hi<=b or b-a>6000:raise ValueError('Context budget invariant failed')
    starts={u['start'] for u in source['units']};ends={u['end'] for u in source['units']}
    return seal(dict(version=POLICY['version'],status='prepared_context_only',source_fingerprint=source['content_fingerprint'],
        source_text_sha256=source['normalized_text_sha256'],anchor_fingerprint=anchor['content_fingerprint'],
        start=a,end=b,text=text[a:b],nominal_bounds=[wl,wr],pre_whitespace_budget_bounds=budget_edges,
        center_ranges=anchor['center_ranges'],budget_clipped=budget_edges!=[wl,wr],
        whitespace_edges_trimmed=[a,b]!=budget_edges,starts_inside_unit=a not in starts,ends_inside_unit=b not in ends,
        has_earlier_source=a>0,has_later_source=b<len(text),complete_context_established=False,usable_evidence=False))
