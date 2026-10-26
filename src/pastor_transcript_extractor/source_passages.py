"""Deterministic source units and exact contiguous passage resolution.

Units follow punctuation, newlines and block boundaries, not word-count limits.
Offsets are Unicode character offsets in SourceWindow.target(), never token offsets.
"""
import re
from .pastor_evidence import digest

VERSION='source-unit-ranges-v2'


def inventory(window):
    text,mapping=window.target();text=text['target_text'];boundaries={0,len(text)}
    boundaries.update(m.end() for m in re.finditer(r'[.!?](?=\s)|\n',text))
    # Keep block boundaries reversible, even when punctuation is absent.
    boundaries.update(m['start'] for m in mapping);boundaries.update(m['end'] for m in mapping)
    ordered=sorted(boundaries);units=[]
    for start,end in zip(ordered,ordered[1:]):
        if start==end: continue
        units.append(dict(id=f'u{len(units):04d}',start=start,end=end,text=text[start:end]))
    return dict(version=VERSION,window_id=window.id,source_sha256=window.source_sha256,
        target_digest=digest(text),units=units,coordinate_system='Unicode characters in joined declared target; end exclusive')


def resolve(window,selection):
    if not isinstance(selection,dict) or set(selection)!={'start_unit','end_unit'}: raise ValueError('A passage requires exactly start_unit and end_unit')
    packet=inventory(window);units=packet['units'];by_id={u['id']:i for i,u in enumerate(units)}
    first,last=selection['start_unit'],selection['end_unit']
    if not isinstance(first,str) or not isinstance(last,str) or first not in by_id or last not in by_id: raise ValueError('Unknown source unit ID')
    left,right=by_id[first],by_id[last]
    if left>right: raise ValueError('Reversed source range')
    text,mapping=window.target();text=text['target_text'];start,end=units[left]['start'],units[right]['end']
    quote=text[start:end]
    if not quote.strip(): raise ValueError('Whitespace-only passage')
    refs=[dict(video_id=window.video_id,source_sha256=window.source_sha256,window_id=window.id,
        stratum=window.stratum,anchor_block_id=window.anchor_block_id,**block,
        local_start=max(start,block['start'])-block['start'],local_end=min(end,block['end'])-block['start'])
        for block in mapping if start<block['end'] and end>block['start']]
    if not refs: raise ValueError('Passage lacks source blocks')
    return dict(version=VERSION,selection=dict(selection),unit_ids=[u['id'] for u in units[left:right+1]],
        span=dict(source_field='target_text',text=quote,start=start,end=end),source_refs=refs,
        target_digest=packet['target_digest'],semantic_validation='pending; unit boundaries do not establish a complete thought')


def evidence_view(source,selection):
    """Render selected text separately from immediate, unselected source context.

    Never remap old unit IDs into a new inventory version or add context to the
    selected span. Request-size checks, not truncation, bound downstream input.
    """
    if source['version']!=VERSION: raise ValueError('Source inventory version differs; do not reinterpret historical IDs')
    units=source['units'];text=''.join(u['text'] for u in units);offset=0
    for i,unit in enumerate(units):
        if unit!=dict(id=f'u{i:04d}',start=offset,end=offset+len(unit['text']),text=unit['text']):
            raise ValueError('Source inventory coordinates or identity differ')
        offset=unit['end']
    if digest(text)!=source['target_digest']: raise ValueError('Source inventory text changed')
    if not isinstance(selection,dict) or set(selection)!={'start_unit','end_unit'}: raise ValueError('Invalid source range')
    ids={u['id']:i for i,u in enumerate(units)}
    if any(not isinstance(value,str) or value not in ids for value in selection.values()): raise ValueError('Unknown source unit ID')
    first,last=ids[selection['start_unit']],ids[selection['end_unit']]
    if first>last: raise ValueError('Reversed source range')
    start,end=units[first]['start'],units[last]['end']
    if not text[start:end].strip(): raise ValueError('Whitespace-only passage')
    return dict(selected_range=dict(selection),selected_span=dict(source_field='target_text',start=start,end=end,text=text[start:end]),
        unselected_context=dict(before=dict(units[first-1]) if first else None,after=dict(units[last+1]) if last+1<len(units) else None),
        context_policy='Unselected context reveals omissions; it does not repair or enlarge the selected evidence.')
