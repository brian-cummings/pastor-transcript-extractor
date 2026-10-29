"""Penultimate analysis support over assembled profile claims and existing evidence.

This provider-free core never extracts propositions, repairs observations or admits
production evidence. Its document handoff preserves every unsupported statement.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import json
from . import pastor_evidence as evidence
from . import source_passages
from .binding_evidence import context_digest, validate_span, text_digest
from .sermon_topics import resolve_topic_analysis_artifact, resolve_topic_block_context

VERSION='profile-analysis-support-v1'
ANSWER_V2='profile-analysis-support-answer-v2'
LAYERS={'topic':'topic_analysis','treatment':'semantic_analysis','salvation':'salvation_relationship_analysis'}


def _unique(rows,key):
    indexed={r[key]:r for r in rows}
    if len(indexed)!=len(rows):raise ValueError('Duplicate '+key)
    return indexed


def read_record(path):
    raw=json.loads(Path(path).read_text())
    return raw.get('description',raw)


class EvidenceReader:
    """Validate materialized constituents against their exact original source once."""
    def __init__(self,record,loader=None):
        self.record=record;self.observations=_unique(record['observations'],'id')
        self.sources=_unique(record['source_identity'],'video_id');self.loaded={};self.checked={}
        self.loader=loader or (lambda path:Path(path).read_bytes())
        self.files={}

    def get(self,eid):
        if eid in self.checked:return self.checked[eid]
        o=self.observations[eid];vid=o['video_id'];source=self.sources[vid]
        if (vid not in self.record['profile']['effective_member_video_ids'] or not source.get('gate',{}).get('eligible')
            or source['source_sha256']!=o['source_sha256'] or source['source_path']!=o['source_path']):raise ValueError('Source eligibility/membership identity differs: '+eid)
        if vid not in self.loaded:
            import hashlib
            content=self.loader(o['source_path'])
            if hashlib.sha256(content).hexdigest()!=o['source_sha256']:raise ValueError('Source content changed: '+eid)
            raw=json.loads(content);topic=resolve_topic_analysis_artifact(raw['classification'])
            self.loaded[vid]=(raw,{b['block_id']:b for b in topic['blocks']})
            self.files[o['source_path']]=o['source_sha256']
        raw,blocks=self.loaded[vid];block=blocks[o['block_id']];texts=resolve_topic_block_context(block)
        if texts['target_text']!=o['full_target_text'] or any(block[k]!=o[k] for k in ('start_seconds','end_seconds','segment_indexes')):raise ValueError('Source geometry/context differs: '+eid)
        layer=raw['classification']['search'][LAYERS[o['layer']]]
        row=next(r for r in layer['blocks'] if r['block_id']==o['block_id'])
        value=row['scores' if o['layer']=='topic' else 'probabilities'][o['field']]
        version=layer.get('question_version',layer.get('question_pack_version'))
        model=row.get('resolved_model_id',layer.get('requested_model_id'))
        if (value!=o['value'] or version!=o['question_version'] or model!=o['model']
            or (o.get('question_digest') and layer.get('question_pack_digest')!=o['question_digest'])):raise ValueError('Constituent value/question/model differs: '+eid)
        if o['layer']=='salvation' and (layer['measurement_statuses'][o['field']]!='validated_for_observation_collection'
            or layer['observation_policy_version']!=o['observation_policy']):raise ValueError('Constituent remains quarantined: '+eid)
        self.checked[eid]=(o,{k:texts[k] for k in ('target_text','leading_context','trailing_context')})
        return self.checked[eid]


def _inventory(window,texts):
    fields={}
    for field,text in texts.items():
        # Reuse the source unit splitter. Context units are coordinates in their
        # named bounded field, never misrepresented as target-block timestamps.
        w=deepcopy(asdict(window));w['blocks'][0]['target_text']=text
        fields[field]=source_passages.inventory(evidence.SourceWindow(**w))['units']
    return fields


def _case(record,claim,reader,claims,points):
    available=set(claims)|{c['id'] for c in record.get('claims',[])}|set(points)
    if any(k not in available for k in claim.get('upstream_claim_ids',[])):raise ValueError('Missing upstream analytical claim')
    if claim.get('description_point_id') and claim['description_point_id'] not in points:raise ValueError('Missing linked explanatory point')
    refs=list(dict.fromkeys(claim.get('observation_input_ids',[])+claim.get('evidence_ids',[])+claim.get('counterevidence_ids',[])))
    if not refs or not claim.get('evidence_ids'):raise ValueError('Statement lacks existing analytical evidence')
    for eid in refs:reader.get(eid)
    contracts=[];rows=[];aliases={};sources={};bindings={};upstream=[]
    for i,eid in enumerate(refs):
        o,texts=reader.get(eid)
        contract={k:deepcopy(o[k]) for k in ('layer','field','meaning','question_version','model')}
        contract.update({k:deepcopy(o[k]) for k in ('question_digest','observation_policy','threshold','route_policy','route_threshold') if k in o})
        if contract not in contracts:contracts.append(contract)
        value=o['value']
        if o['layer']=='topic':value=[value['score'],value['confidence'],[value['probabilities'][str(n)] for n in range(5)]]
        rows.append([i,o['video_id'],o['block_id'],contracts.index(contract),value,o['state']]);aliases[eid]=i
    direct=list(dict.fromkeys(claim['evidence_ids']+claim.get('counterevidence_ids',[])))
    for eid in direct:
        o,texts=reader.get(eid);pid=f"v{o['video_id']}b{o['block_id']}"
        if pid not in sources:
            window=evidence.SourceWindow(pid,record['profile']['id'],o['video_id'],o['source_sha256'],o['block_id'],
                (dict(block_id=o['block_id'],target_text=texts['target_text'],start_seconds=o['start_seconds'],end_seconds=o['end_seconds'],segment_indexes=o['segment_indexes']),),'profile_analysis_support')
            sources[pid]=dict(window=json.loads(json.dumps(asdict(window))),texts=texts,fields=_inventory(window,texts),context_sha256=context_digest(texts))
        bindings[eid]=pid
    wanted=set(claim.get('reviewed_binding_ids',[]))
    for key in [claim['id']]+claim.get('upstream_claim_ids',[]):
        point=points.get(key)
        if point:
            wanted.update(point.get('reviewed_binding_ids',[]))
            upstream.append({k:deepcopy(point[k]) for k in ('point_id','kind','explanation','qualifications','frame','address_acts','status') if k in point})
    bound=[]
    for item in record.get('evidence_supply',{}).get('reviewed_bound_records',[]):
        b=item['binding']
        if b['binding_id'] not in wanted:continue
        o,texts=reader.get(item['evidence_id']);p=b['provenance']
        if (p['source_sha256']!=o['source_sha256'] or p['target_sha256']!=text_digest(texts['target_text'])
            or p['texts_sha256']!=context_digest(texts) or p['membership_fingerprint']!=record['profile']['membership_fingerprint']
            or p['source_inventory_fingerprint']!=record['inventory_fingerprint']):raise ValueError('Bound observation context/provenance differs')
        def spans(value):
            if isinstance(value,dict):
                if 'source_field' in value:validate_span(value,texts)
                for v in value.values():spans(v)
            elif isinstance(value,list):
                for v in value:spans(v)
        spans(b)
        bound.append(dict(binding=deepcopy(b),origin_status=item['status'],authority='Existing upstream proposal; not independent truth or production admission'))
    missing=wanted-{b['binding']['binding_id'] for b in bound}
    if missing:raise ValueError('Missing linked qualified bindings: '+', '.join(sorted(missing)))
    aggregates=[]
    for eid in refs:
        o,_=reader.get(eid)
        if 'measurement' in o:
            value=dict(video_id=o['video_id'],field=o['field'],measurement=deepcopy(o['measurement']))
            if value not in aggregates:aggregates.append(value)
    raw_claims={c['id']:c for c in record.get('claims',[])}
    aggregate_claims=[{k:deepcopy(raw_claims[cid][k]) for k in ('id','wording','rule','scope','support_state','uncertainty','rule_version') if k in raw_claims[cid]} for cid in claim.get('upstream_claim_ids',[]) if cid in raw_claims]
    source_state=[]
    for pid,s in sorted(sources.items()):
        source_state.append(dict(passage_id=pid,video_id=s['window']['video_id'],block_id=s['window']['anchor_block_id'],fields={k:[dict(id=u['id'],text=u['text']) for u in v] for k,v in s['fields'].items()},support_input_ids=[aliases[e] for e,p in bindings.items() if p==pid and e in claim['evidence_ids']],counter_input_ids=[aliases[e] for e,p in bindings.items() if p==pid and e in claim.get('counterevidence_ids',[])]))
    dependencies=[k for k in claim.get('upstream_claim_ids',[]) if k in claims]
    state=dict(candidate=dict(id=claim['id'],statement=claim['wording'],scope=deepcopy(claim.get('scope',{})),analytical_basis=claim.get('analytical_basis',claim.get('rule_id','existing_claim')),declared_caveats=deepcopy(claim.get('_support_caveats',{}))),
        sample=dict(profile_id=record['profile']['id'],video_ids=sorted(record['profile']['effective_member_video_ids']),coverage=deepcopy(record.get('coverage',{}))),
        measurement_ledger=dict(columns=['input_id','video_id','block_id','contract','value','state'],topic_value_columns=['score','confidence','probabilities_0_to_4'],contracts=contracts,rows=rows,meaning='Complete declared observation inputs, not semantic proof. Only linked supporting/contrary passages are reproduced below.'),
        passages=source_state,upstream_points=upstream,bound_observations=bound,stored_aggregates=aggregates,upstream_aggregate_claims=aggregate_claims,aggregation_contract=record['reader'].get('synthesis_rule','Not supplied; do not invent aggregation meanings.'))
    return dict(state=state,sources=sources,input_ids={str(v):k for k,v in aliases.items()},dependencies=dependencies,
        identity=dict(profile_id=record['profile']['id'],membership_fingerprint=record['profile']['membership_fingerprint'],inventory_fingerprint=record['inventory_fingerprint']))


def build_plan(record,*,loader=None):
    """All assembled reader claims, with explicit per-claim evidence failures."""
    reader=EvidenceReader(record,loader);claims=_unique(deepcopy(record['reader']['claims']),'id')
    portrait={p['id']:p for p in record['reader'].get('portrait',{}).get('entries',[])}
    for cid,claim in claims.items():
        claim['_support_caveats']={k:deepcopy(portrait[cid][k]) for k in ('limits','alternative') if k in portrait[cid]} if cid in portrait else {}
    points={p.get('claim_id',p['point_id']):p for p in record['reader'].get('explanatory_descriptions',{}).get('points',[])}
    items=[]
    for cid,claim in sorted(claims.items()):
        try:case=_case(record,claim,reader,claims,points);gap=None
        except (ValueError,KeyError,StopIteration,OSError,TypeError) as error:
            case=None;gap=dict(blocked_statement=claim['wording'],inspected_reuse=['Declared observation inputs','Linked source blocks/context','Linked upstream bound records'],missing_information=str(error) or type(error).__name__,responsible_producer='existing profile evidence assembly / relevant category-leaf producer',smallest_remedy='Restore compatible existing evidence or return this statement unresolved; do not reconstruct measurements here.',acceptance='Exact source, question, model, membership and context checks pass.',authorization_boundary='No new inference or upstream repair in analysis support')
        items.append(dict(claim_id=cid,statement=claim['wording'],scope=deepcopy(claim.get('scope',{})),declared_caveats=claim['_support_caveats'],case=case,gap=gap))
    return dict(version=VERSION,profile=deepcopy(record['profile']),inventory_fingerprint=record['inventory_fingerprint'],items=items,
        known_gaps=[{k:deepcopy(g[k]) for k in ('id','withheld','cause','remedy') if k in g} for g in record.get('gaps',[])],source_files=reader.files,
        policy=dict(origin='machine_generated',namespace=VERSION,production_admission='not_admitted',upstream_repairs=False))


def validate_answer(case,answer,*,maximum_citations=16):
    if not isinstance(answer,dict) or set(answer)!={'judgment','evidence','qualifications','reason'} or answer['judgment'] not in ('supported','contradicted','unresolved'):raise ValueError('Invalid analysis support answer')
    if not isinstance(answer['reason'],str) or not 0<len(answer['reason'].strip())<=800:raise ValueError('Invalid reason')
    def bind(rows):
        if not isinstance(rows,list) or len(rows)>maximum_citations:raise ValueError('Invalid citations')
        if len({evidence.digest(r) for r in rows})!=len(rows):raise ValueError('Duplicate citations')
        result=[]
        for row in rows:
            if not isinstance(row,dict) or set(row)!={'passage_id','field','start_unit','end_unit'}:raise ValueError('Invalid citation shape')
            source=case['sources'][row['passage_id']];units=source['fields'][row['field']];ids={u['id']:i for i,u in enumerate(units)}
            a,b=ids[row['start_unit']],ids[row['end_unit']]
            if a>b:raise ValueError('Reversed citation')
            text=source['texts'][row['field']];span=dict(source_field=row['field'],start=units[a]['start'],end=units[b]['end'],text=text[units[a]['start']:units[b]['end']]);validate_span(span,source['texts'])
            result.append(dict(selection=row,span=span,source_identity=dict(video_id=source['window']['video_id'],anchor_block_id=source['window']['anchor_block_id'],source_sha256=source['window']['source_sha256'],context_sha256=source['context_sha256']),coordinate_policy='Named bounded field; context is not target speech or an inferred timestamp.'))
        return result
    citations=bind(answer['evidence'])
    if answer['judgment']!='unresolved' and not citations:raise ValueError('Determinate answer requires source evidence')
    if not isinstance(answer['qualifications'],list) or len(answer['qualifications'])>8:raise ValueError('Invalid qualifications')
    qualifications=[]
    for q in answer['qualifications']:
        if not isinstance(q,dict) or set(q)!={'reading','evidence'} or not isinstance(q['reading'],str) or not 0<len(q['reading'].strip())<=300:raise ValueError('Invalid qualification')
        bound=bind(q['evidence'])
        if not bound:raise ValueError('Qualification requires evidence')
        qualifications.append(dict(reading=q['reading'],bound_evidence=bound))
    return dict(answer=deepcopy(answer),bound_evidence=citations,qualifications=qualifications,origin='machine_generated',namespace=VERSION,production_admission='not_admitted',semantic_validation='Model judgment; independent accuracy not established')


def citation_catalog(case):
    """One identifier per complete source unit; no passage/unit cross product."""
    result={}
    for pid,source in sorted(case['sources'].items()):
        for field,units in sorted(source['fields'].items()):
            for unit in units:
                result[f'c{len(result):04d}']=dict(passage_id=pid,field=field,start_unit=unit['id'],end_unit=unit['id'])
    return result


def citation_state(case):
    state=deepcopy(case['state']);catalog=citation_catalog(case)
    reverse={(v['passage_id'],v['field'],v['start_unit']):k for k,v in catalog.items()}
    for passage in state['passages']:
        for field,units in passage['fields'].items():
            for unit in units:unit['citation_id']=reverse[(passage['passage_id'],field,unit['id'])]
    return state


def validate_answer_v2(case,answer):
    """Bind model judgments and literal preservation evidence without semantic repair."""
    if not isinstance(answer,dict) or set(answer)!={'judgment','evidence','qualifications','reason'}:raise ValueError('Invalid v2 support answer')
    catalog=citation_catalog(case)
    def selections(ids):
        if not isinstance(ids,list) or len(ids)>64 or any(not isinstance(cid,str) or cid not in catalog for cid in ids):raise ValueError('Unknown source citation ID')
        if len(set(ids))!=len(ids):raise ValueError('Duplicate source citation IDs')
        return [deepcopy(catalog[cid]) for cid in ids]
    candidate=case['state']['candidate'];fields=dict(statement=candidate['statement'],scope=json.dumps(candidate.get('scope',{}),sort_keys=True,ensure_ascii=False),declared_caveats=json.dumps(candidate.get('declared_caveats',{}),sort_keys=True,ensure_ascii=False))
    qualities=answer['qualifications']
    if not isinstance(qualities,list) or len(qualities)>8:raise ValueError('Invalid qualifications')
    legacy=[];preservation=[]
    for q in qualities:
        if not isinstance(q,dict) or set(q)!={'reading','evidence','status','preservation_evidence'} or q['status'] not in ('already_preserved','missing_required','unresolved'):raise ValueError('Explicit qualification preservation status required')
        proof=q['preservation_evidence']
        if not isinstance(proof,list) or len(proof)>3:raise ValueError('Invalid preservation evidence')
        if (q['status']=='already_preserved')!=bool(proof):raise ValueError('Preserved qualification requires literal candidate evidence; other statuses require none')
        bound=[]
        for part in proof:
            if (not isinstance(part,dict) or set(part)!={'field','text'} or part['field'] not in fields
                or not isinstance(part['text'],str) or not 0<len(part['text'].strip())<=300 or part['text'] not in fields[part['field']]):raise ValueError('Preservation excerpt is not literal supplied candidate text')
            text=fields[part['field']];needle=part['text'];starts=[i for i in range(len(text)) if text.startswith(needle,i)]
            bound.append(dict(field=part['field'],text=needle,occurrences=starts))
        legacy.append(dict(reading=q['reading'],evidence=selections(q['evidence'])))
        preservation.append(dict(status=q['status'],preservation_evidence=bound))
    # The established binder continues to own literal/source checks. The v2
    # inventory permits more individual units instead of sixteen arbitrary ranges.
    old=dict(judgment=answer['judgment'],reason=answer['reason'],evidence=selections(answer['evidence']),qualifications=legacy)
    result=validate_answer(case,old,maximum_citations=64)
    for q,p in zip(result['qualifications'],preservation):q.update(p)
    result.update(answer=deepcopy(answer),contract_version=ANSWER_V2,citation_catalog_digest=evidence.digest(catalog))
    return result


def document_input(plan,results,*,production=False):
    """Final presentation consumes only supported, unchanged, dependency-safe text."""
    if production:raise ValueError('Analysis support is not production admitted')
    indexed=_unique(results,'claim_id')
    if set(indexed)!={i['claim_id'] for i in plan['items']}:raise ValueError('Incomplete support result inventory')
    states={};by_id={i['claim_id']:i for i in plan['items']}
    def state(cid,path=()):
        if cid not in indexed:return 'not_evaluated'
        if cid in states:return states[cid]
        if cid in path:return 'dependency_unresolved'
        row=indexed[cid];judgment=row.get('judgment')
        status=judgment['answer']['judgment'] if judgment else row.get('status','unresolved')
        if status=='supported' and judgment['qualifications']:
            if judgment.get('contract_version')!=ANSWER_V2:status='requires_qualification'
            elif any(q.get('status')=='missing_required' for q in judgment['qualifications']):status='requires_qualification'
            elif any(q.get('status')!='already_preserved' for q in judgment['qualifications']):status='qualification_unresolved'
        if status=='supported' and any(state(k,path+(cid,))!='supported' for k in (by_id[cid]['case'] or {}).get('dependencies',[])):status='dependency_unresolved'
        states[cid]=status;return status
    entries=[]
    for item in plan['items']:
        cid=item['claim_id'];row=indexed[cid]
        entries.append(dict(claim_id=cid,statement=item['statement'],scope=item['scope'],declared_caveats=item.get('declared_caveats',{}),support_status=state(cid),judgment=row.get('judgment'),receipt=row.get('receipt'),gap=item['gap'],failure=row.get('failure')))
    counts={s:sum(e['support_status']==s for e in entries) for s in sorted({e['support_status'] for e in entries})}
    return dict(version=VERSION,stage='analysis_support_before_final_document',profile=plan['profile'],entries=entries,
        ready_claim_ids=[e['claim_id'] for e in entries if e['support_status']=='supported'],known_gaps=plan['known_gaps'],coverage=dict(total=len(entries),assembled_total=plan.get('selection',{}).get('assembled_total',len(entries)),selection_mode=plan.get('selection',{}).get('mode','complete_profile'),by_status=counts,meaning='All assembled analytical claims; not corpus completeness or independent accuracy'),
        origin='machine_generated',namespace=VERSION,production_admission='not_admitted')


def render_handoff(document):
    lines=['# Profile analysis support','',f"Profile {document['profile']['id']} · {document['coverage']['total']} analytical statements",'',
        'Experimental model assessments. Supported statements remain scoped to the supplied sample; no production admission.','',
        '## Statements available to the final document','']
    for e in document['entries']:
        if e['support_status']=='supported':
            lines.extend([e['statement'],'','Scope: '+json.dumps(e['scope'],ensure_ascii=False),''])
            if e.get('declared_caveats'):lines.extend(['Declared limitations and alternatives: '+json.dumps(e['declared_caveats'],ensure_ascii=False),''])
            lines.extend([f"Support: {e['claim_id']} · {e['receipt']}",''])
    lines.extend(['## Unresolved, contradicted or withheld statements',''])
    for e in document['entries']:
        if e['support_status']!='supported':lines.extend([f"### {e['claim_id']} · {e['support_status']}",'',e['statement'],'',json.dumps(e.get('judgment') or e.get('gap') or e.get('failure'),ensure_ascii=False),''])
    lines.extend(['## Existing profile limitations','',json.dumps(document['known_gaps'],ensure_ascii=False,indent=2),''])
    return '\n'.join(lines)
