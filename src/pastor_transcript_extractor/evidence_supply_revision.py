"""Fixed V2 supply preparation and separately opt-in bounded execution.

Reference checks are authored before discovery. Discovery sees source coordinates
only. The original closed feasibility gates and V1 packet are never rewritten.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from pastor_transcript_extractor import evidence_supply_review as v1

ROOT = v1.ROOT
HERE = ROOT / 'docs/review-proposals/evidence-supply-readiness-v2'
RESULTS = ROOT / 'evaluation/evidence-supply-readiness-v2'
VERSION = 'evidence-supply-readiness-v2'
BUILDER = 'complete-source-neighbors-and-local-claims-v2'
MODEL = v1.MODEL
MAX_HOPS = 4
BATCH_PAIRS = 8
CONTEXT_TOKENS = 64000
PRICE = Decimal('0.042') / Decimal(1000000)
PRICE_SOURCE = 'https://docs.typesafe.ai/models'


def fp(value: Any) -> str:
    return v1.fingerprint(value)


def dump(path: Path, value: Any) -> None:
    """Atomic write; interruption cannot leave a half-written ledger/receipt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':'))+'\n')
    temporary.replace(path)


def span(text: str, start: int, end: int) -> dict[str, Any]:
    if not 0 <= start < end <= len(text):
        raise ValueError('Invalid source coordinates')
    return dict(start=start, end=end, text=text[start:end])


def sentences(source: dict[str, Any]) -> list[dict[str, Any]]:
    text = source['text']; lo = source['main_span']['start']; hi = source['main_span']['end']
    nodes = []; cursor = lo
    for match in [*re.finditer(r'[.!?]["\u201d\u2019\x27]*\s+', text[lo:hi]), None]:
        end = lo+match.start()+len(match.group().rstrip()) if match else hi
        start = cursor
        while start < end and text[start].isspace(): start += 1
        while end > start and text[end-1].isspace(): end -= 1
        if start < end:
            value=span(text,start,end)
            # Keep caption newlines as source whitespace; do not split a
            # sentence merely because a rolling-caption unit ends. Pure
            # discourse fillers remain in targets/context, not endpoint nodes.
            if not re.fullmatch(r'(?:right|okay|amen|all right|so|wow|yeah|yes|what|who|hallelujah|you know|interesting)[.!?,;\s]*',value['text'],re.I):
                nodes.append(value)
        if match: cursor = lo+match.end()
    return nodes


def _target(source, nodes, first, last):
    return span(source['text'], nodes[first]['start'], nodes[last]['end'])


def _context(source, target):
    lo, hi = source['main_span']['start'], source['main_span']['end']
    return dict(leading_context=source['text'][max(lo,target['start']-250):target['start']],
                trailing_context=source['text'][target['end']:min(hi,target['end']+250)])


def discover(source: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from pastor_transcript_extractor import sermon_g1_feasibility_review as g1
    nodes = sentences(source); found = []; errors = []
    seed = re.compile(r'\b(?:saved|salvation|accepted|pardoned|assurance|ramps?|retention)\b', re.I)
    circumstance = re.compile(r'\b(?:griev\w*|guilt\w*|forgiv\w*|sin\w*|sorrow\w*|afraid|troubl\w*|doubt\w*|depress\w*|busy|children|parents|father|sons?|difficult\w*|temptation|backslid\w*|distract\w*|trembling|poor|selfish\w*|pride|fear|loss|divorce|convict\w*|peace|time|inventory|not ready)\b', re.I)
    for i, node in enumerate(nodes):
        if seed.search(node['text']):
            # Preserve contiguous neighboring framing in the target whenever it
            # fits the unchanged G1 input ceilings. No character slicing/rewriting.
            prepared = None
            for radius, context_chars in [(1,250),(1,0),(0,250),(0,0)]:
                target = _target(source,nodes,max(0,i-radius),min(len(nodes)-1,i+radius))
                context = _context(source,target) if context_chars else dict(leading_context='',trailing_context='')
                case = dict(case_id='supply',target_text=target['text'],**context)
                try:
                    units, pools = g1.candidates(case)
                    # This is additional source-span retrieval vocabulary, not a
                    # changed question or a new object/relation meaning.
                    extra = []
                    for field in ('target_text','leading_context','trailing_context'):
                        for m in re.finditer(r'\bpardoned\b|\bassurance\b',case[field],re.I):
                            extra.append(dict(source_field=field,start=m.start(),end=m.end(),text=m.group()))
                    if len(pools['objects'])+len(extra)>6: continue
                    for s in extra: pools['objects'][f"objects-{len(pools['objects'])}"]=s
                    claim = dict(source_field='target_text',start=node['start']-target['start'],end=node['end']-target['start'],text=node['text'])
                    # The candidate need not equal an artificial sentence-frame
                    # fragment; it remains the exact source sentence being judged.
                    prepared = dict(capability='G1',target=target,claim=node,phrase_pools=pools,
                                    local_claim=claim,**context)
                    break
                except ValueError:
                    continue
            if prepared is None:
                errors.append(dict(capability='G1',source_span=node,reason='Cannot fit unchanged G1 source/pool limits'))
            else: found.append(prepared)
        # Complete source coverage: every directed neighbor pair within the
        # declared four-sentence horizon, no sermon-level candidate cutoff.
        for j in range(max(0,i-MAX_HOPS),min(len(nodes),i+MAX_HOPS+1)):
            if i==j: continue
            tile=(min(i,j)//8)*8
            target = _target(source,nodes,max(0,tile-1),min(len(nodes)-1,tile+8+MAX_HOPS))
            found.append(dict(capability='G2',target=target,left=node,right=nodes[j],**_context(source,target)))
        # Every lexical circumstance sentence is paired with nearby utterances.
        # Null-circumstance candidates retain generic act/control observations.
        if circumstance.search(node['text']):
            for j in range(max(0,i-MAX_HOPS),min(len(nodes),i+MAX_HOPS+1)):
                tile=(min(i,j)//8)*8
                target = _target(source,nodes,max(0,tile-1),min(len(nodes)-1,tile+8+MAX_HOPS))
                found.append(dict(capability='G3',target=target,circumstance=node,utterance=nodes[j],**_context(source,target)))
        if re.search(r'\b(?:you|we|let|pray|promise|call|help|come|should)\b',node['text'],re.I):
            tile=(i//8)*8
            target=_target(source,nodes,max(0,tile-1),min(len(nodes)-1,tile+8+MAX_HOPS))
            found.append(dict(capability='G3',target=target,circumstance=None,utterance=node,**_context(source,target)))
    for c in found:
        c['video_id']=source['video_id']; c['builder_version']=BUILDER
        identity = {k:c[k] for k in ('capability','video_id','target','claim','left','right','circumstance','utterance') if k in c}
        c['candidate_id']=f"{source['video_id']}:{c['capability']}:{fp(identity)[:16]}"
    if len({c['candidate_id'] for c in found}) != len(found): raise ValueError('Duplicate source candidates')
    return found, dict(sentence_count=len(nodes),candidate_counts=dict(Counter(c['capability'] for c in found)),
                       source_start=source['main_span']['start'],source_end=source['main_span']['end'],
                       global_truncation=0,local_neighbor_horizon=MAX_HOPS,unrepresentable=errors)


def bind_address_question(value,index):
    # Reversible source-pointer substitution only. Meanings/options/thresholds
    # stay canonical; independent questions cannot see another answer.
    if isinstance(value,str):return value.replace('candidate.',f'candidates[{index}].')
    if isinstance(value,dict):return {k:bind_address_question(v,index) for k,v in value.items()}
    if isinstance(value,list):return [bind_address_question(v,index) for v in value]
    return value


def request_inputs(candidates: list[dict[str, Any]], *, batch_pairs: int = BATCH_PAIRS) -> list[dict[str, Any]]:
    from pastor_transcript_extractor import sermon_g1_feasibility_review as g1
    from pastor_transcript_extractor import sermon_g1_feasibility_revision as g1v2
    from pastor_transcript_extractor import sermon_g2_feasibility_revision as g2v2
    from pastor_transcript_extractor import sermon_g3_feasibility_review as g3
    from pastor_transcript_extractor import sermon_g3_feasibility_revision as g3v2
    groups=defaultdict(list);requests=[]
    for c in candidates:
        if c['capability'] in {'G2','G3'}: groups[(c['capability'],c['video_id'],c['target']['start'],c['target']['end'])].append(c)
        else: groups[('single',c['candidate_id'])].append(c)
    for group in groups.values():
        for start in range(0,len(group),batch_pairs if group[0]['capability']=='G2' else min(batch_pairs,3) if group[0]['capability']=='G3' else 1):
            size=batch_pairs if group[0]['capability']=='G2' else min(batch_pairs,3) if group[0]['capability']=='G3' else 1
            batch=group[start:start+size];c=batch[0];cap=c['capability'];base=c['target']['start']
            state=dict(target_text=c['target']['text'],leading_context=c['leading_context'],trailing_context=c['trailing_context'])
            def local(s): return dict(source_field='target_text',start=s['start']-base,end=s['end']-base,text=s['text'])
            if cap=='G1':
                state.update(phrase_pools=c['phrase_pools'],candidate={'candidate_id':c['candidate_id'],'claim_span':c['local_claim']})
                questions=g1v2.questions(c['phrase_pools']);version=g1v2.VERSION
            elif cap=='G2':
                state['pairs']=[dict(pair_id=x['candidate_id'],left=local(x['left']),right=local(x['right'])) for x in batch]
                questions={k:v for i in range(len(batch)) for k,v in g2v2.questions(i).items() if k.removeprefix(f'p{i}_') in {'explains_text','adoption','boundary','left_voice','right_voice'}};version=g2v2.VERSION
            else:
                state['candidates']=[dict(circumstance=local(x['circumstance']) if x['circumstance'] else None,utterance=local(x['utterance'])) for x in batch]
                original={k:v for k,v in g3.questions().items() if k!='binding'}|g3v2.questions()
                questions={f'q{i}_{k}':bind_address_question(v,i) for i in range(len(batch)) for k,v in original.items()};version=g3v2.VERSION
            body=dict(model=MODEL,state=state,questions={k:dict(type='choice',**v) for k,v in questions.items()})
            # UTF-8 bytes is a transparent size check, not a fabricated tokenizer.
            # Conservative 60KB body also stays well below documented context
            # windows for this fixed English input; service 64k ceiling is reserved.
            if len(json.dumps(body,ensure_ascii=False).encode())>60000:
                if len(batch)>1:
                    requests.extend(request_inputs(batch,batch_pairs=max(1,len(batch)//2)))
                    continue
                raise ValueError('Single request body exceeds prepared 60KB bound')
            request=dict(capability=cap,candidate_ids=[x['candidate_id'] for x in batch],state=state,questions=questions,question_version=version)
            request['request_key']=fp(request);requests.append(request)
    return requests


def _contains(actual,wanted):
    return actual is not None and actual['start']<=wanted['start'] and actual['end']>=wanted['end']


def matching(check,candidate):
    if check['kind']=='directed_edge': return _contains(candidate.get('left'),check['left']) and _contains(candidate.get('right'),check['right'])
    if check['kind']=='proposition': return _contains(candidate.get('claim'),check['claim'])
    if not _contains(candidate.get('utterance'),check['utterance']): return False
    if check['circumstance'] is None: return candidate.get('circumstance') is None
    return _contains(candidate.get('circumstance'),check['circumstance'])


def funnel(references,candidates):
    by_route=defaultdict(list)
    for c in candidates: by_route[(c['video_id'],c['capability'])].append(c)
    rows=[]
    for r in references['rows']:
        for check in r['checks']:
            hits=[c['candidate_id'] for c in by_route[(r['video_id'],r['capability'])] if matching(check,c)]
            rows.append(dict(reference_id=r['reference_id'],check_id=check['check_id'],video_id=r['video_id'],capability=r['capability'],
                             opportunity=check['opportunity'],expected=check['expected'],matching_candidate_ids=hits,
                             discovery='supplied_exact_endpoint_spans' if hits else 'not_supplied',
                             observation=None,usable_evidence=None,measurement_error=None))
    return rows


def build_packet():
    sources=[json.loads((HERE/'sources'/f'{v}.json').read_text()) for v in v1.SOURCE_IDS]
    references=json.loads((HERE/'references-v2.json').read_text());candidates=[];diagnostics={}
    for source in sources:
        cs,ds=discover(source);candidates.extend(cs);diagnostics[str(source['video_id'])]=ds
    requests=request_inputs(candidates)
    paths=[ROOT/p for p in v1.AUTHORITY_PATHS]+[v1.PACKET_DIR/'input-v1.json',v1.PACKET_DIR/'references-v1.json',HERE/'references-v2.json',Path(__file__),*(HERE/'sources'/f'{v}.json' for v in v1.SOURCE_IDS)]
    reserve=CONTEXT_TOKENS*len(requests)
    packet=dict(version=VERSION,model=MODEL,builder=BUILDER,provider_requests=0,production_effect='none',
                source_files={str(p.relative_to(ROOT)):v1.file_hash(p) for p in paths},
                source_ids=list(v1.SOURCE_IDS),source_snapshot_paths=[str((HERE/'sources'/f'{v}.json').relative_to(ROOT)) for v in v1.SOURCE_IDS],
                reference_path=str((HERE/'references-v2.json').relative_to(ROOT)),reference_count=len(references['rows']),
                candidate_manifest=[{k:v for k,v in c.items() if k not in ('target','leading_context','trailing_context','phrase_pools','local_claim')}|{'target_start':c['target']['start'],'target_end':c['target']['end']} for c in candidates],
                request_manifest=[dict(request_key=r['request_key'],capability=r['capability'],candidate_ids=r['candidate_ids'],question_count=len(r['questions']),question_version=r['question_version'],state_fingerprint=fp(r['state']),questions_fingerprint=fp(r['questions'])) for r in requests],
                discovery_diagnostics=diagnostics,funnel=funnel(references,candidates),
                budget=dict(maximum_attempts=len(requests),maximum_input_tokens=reserve,
                            maximum_list_price_usd=str((PRICE*reserve).quantize(Decimal('0.000001'),rounding=ROUND_CEILING)),
                            input_usd_per_million='0.042',output_usd_per_million='0',automatic_retries=0,
                            price_source=PRICE_SOURCE,price_checked_on='2026-10-14',per_attempt_reservation=CONTEXT_TOKENS,
                            basis='Documented default 64k combined request context, long-context explicitly disabled; reserve full ceiling for every attempt, including failed or lost receipts.',
                            authorized_attempts=0,authorized_usd='0',actual_usage=None),
                route_scope={'G1_assurance':'prepared_natural_knowledge_of_pardon_plus_ambiguous_controls','G1_city_ramp':'blocked_no_natural_positive_no_semantic_substitution','G2':'explains_text_and_accepted_stance_boundary_voice_fields_only_other_facets_not_requested','G3':'independent_local_acts_bindings_no_recurring_posture'},
                criteria=dict(critical_integrity_maximum=0,critical_integrity_types=list(v1.INTEGRITY),
                              pass_rule='Per tested route: no integrity/definite measurement errors, all positive reference checks supplied and satisfied; at least one usable source-linked positive. Ambiguous allowed values and withholding remain explicit.',
                              partial='Known discovery misses or clear-positive conservative withholdings prevent PASS; measurement errors and critical failures remain separate.',
                              failure='Any critical integrity failure fails the tested route; no averaging with omissions.',
                              final_decision='Codex audits all outputs; Brian decides separately. No automated gate PASS.'),
                usable_item_definition='One unique source-audited G1 claim, directed G2 explanation pair, or G3 utterance/circumstance record with a supported positive fact. Report fully bound/adopted, partial and report-only records separately; deduplicate aliases. Unknown-only outputs and correct no-match controls are not usable-positive items. Local negatives have separate validation counts. Counts are not independent sermons or opportunities.',
                prepared_status='ready_for_review_paid_execution_held',paid_execution_authorized=False,
                holds=['closed_G1_G2_G3_tuning','broader_collection','production_calibration','population_recall','operational_denominators','production_economics','pastor_projection_comparison','G4_coherence','clustering','recurrence_rates','quality_scoring'])
    packet['content_fingerprint']=fp(packet)
    return packet,requests


def validate_packet(packet, *, reproduce=True):
    if packet.get('content_fingerprint')!=fp({k:v for k,v in packet.items() if k!='content_fingerprint'}):
        raise ValueError('V2 packet fingerprint mismatch')
    if packet['provider_requests']!=0 or packet['production_effect']!='none' or packet['paid_execution_authorized']:
        raise ValueError('Preparation cannot authorize provider execution or projection')
    for name,digest in packet['source_files'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or v1.file_hash(path)!=digest:
            raise ValueError('Frozen source/question code changed: '+name)
    sources={v:json.loads((HERE/'sources'/f'{v}.json').read_text()) for v in v1.SOURCE_IDS}
    refs=json.loads((HERE/'references-v2.json').read_text())
    seen=set()
    for row in refs['rows']:
        source=sources[row['video_id']];text=source['text'];lo=source['main_span']['start'];hi=source['main_span']['end']
        for check in row['checks']:
            if check['check_id'] in seen:raise ValueError('Duplicate reference check')
            seen.add(check['check_id'])
            for field in ('left','right','claim','circumstance','utterance'):
                s=check.get(field)
                if s and (not lo<=s['start']<s['end']<=hi or text[s['start']:s['end']]!=s['text']):
                    raise ValueError('Reference endpoint outside reviewed source or changed: '+check['check_id'])
    if any(d['global_truncation'] or d['unrepresentable'] for d in packet['discovery_diagnostics'].values()):
        raise ValueError('Source candidates were truncated or cannot be represented')
    if packet['budget']['maximum_attempts']!=len(packet['request_manifest']):raise ValueError('Request budget drift')
    if reproduce:
        expected,requests=build_packet()
        if expected!=packet:raise ValueError('V2 sources/candidates/questions/references/budget do not reproduce')
        return requests
    return None


def live_check(packet,base_dir):
    sources=[json.loads((ROOT/p).read_text()) for p in packet['source_snapshot_paths']]
    v1.verify_live_sources({'sources':sources},base_dir)


def _seal(value):
    return value|{'fingerprint':fp(value)}


def _verify_seal(value):
    if value.get('fingerprint')!=fp({k:v for k,v in value.items() if k!='fingerprint'}):
        raise ValueError('Corrupt receipt/ledger; no automatic replacement or provider retry')


class HTTPProvider:
    """Single-attempt official HTTP API; raw body survives parser validation."""
    def __init__(self):
        self.key=os.environ.get('TYPESAFE_API_KEY','').strip()
        if not self.key:raise ValueError('TYPESAFE_API_KEY is required for the separately approved run')

    def assess(self,request):
        import urllib.request
        import urllib.error
        payload=dict(model=MODEL,state=request['state'],questions={k:dict(type='choice',**q) for k,q in request['questions'].items()})
        wire=urllib.request.Request('https://api.typesafe.ai/v1/systemone',data=json.dumps(payload,ensure_ascii=False).encode(),
                                    headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json',
                                             'TypeSafe-Danger-Zone-Long-Context':'false'},method='POST')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        opener=urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(wire,timeout=45) as response:
                return {'status_code':response.status,'request_id':response.headers.get('x-request-id'),
                        'body':response.read().decode('utf-8')}
        except urllib.error.HTTPError as error:
            return {'status_code':error.code,'request_id':error.headers.get('x-request-id'),
                    'body':error.read().decode('utf-8',errors='replace')}

    def close(self):
        self.key=''


def validate_response(receipt,request):
    from pastor_transcript_extractor.sermon_g1_feasibility_revision import validate_answers
    if receipt['status_code']!=200:raise ValueError('Provider HTTP failure; raw receipt retained; no retry')
    raw=json.loads(receipt['body'])
    if raw.get('model')!=MODEL:raise ValueError('Resolved model drift')
    answers=raw.get('answers',{})
    validate_answers(answers,request['questions'])
    usage=raw.get('usage',{})
    for key in ('input_tokens','output_tokens'):
        value=usage.get(key)
        if not isinstance(value,int) or isinstance(value,bool) or value<0:raise ValueError('Missing/invalid usage; full reservation retained')
    if usage['input_tokens']>CONTEXT_TOKENS:raise ValueError('Documented default request context/billing bound violated; stop')
    return raw


def execute(packet,requests,*,approval_key,output_dir=RESULTS,provider_factory=HTTPProvider):
    """Called only by Brian's later exact opt-in, never by preparation/check modes."""
    if approval_key!=packet['content_fingerprint']:
        raise ValueError('Paid execution requires exact --approve-paid-packet fingerprint; current authorization is provider-free only')
    validate_packet(packet,reproduce=False)
    if [r['request_key'] for r in requests]!=[r['request_key'] for r in packet['request_manifest']]:
        raise ValueError('Request manifest mismatch before provider construction')
    # Validate identities including full states/questions, not keys copied from a
    # mutable request. An invalid preflight must never create a client or ledger.
    for request,manifest in zip(requests,packet['request_manifest']):
        if fp({k:v for k,v in request.items() if k!='request_key'})!=request['request_key'] or fp(request['state'])!=manifest['state_fingerprint'] or fp(request['questions'])!=manifest['questions_fingerprint']:
            raise ValueError('Changed request state/question identity')
    ceiling=packet['budget']['maximum_attempts']
    if ceiling!=len(requests) or packet['budget']['maximum_input_tokens']!=ceiling*CONTEXT_TOKENS:
        raise ValueError('Invalid fixed execution budget')
    maximum=PRICE*CONTEXT_TOKENS*ceiling
    if Decimal(packet['budget']['maximum_list_price_usd'])<maximum:raise ValueError('Spending ceiling cannot cover full attempt reservations')
    output_dir=Path(output_dir);ledger_path=output_dir/'request-ledger.json';receipt_dir=output_dir/'receipts'
    if ledger_path.exists():
        ledger=json.loads(ledger_path.read_text());_verify_seal(ledger)
        if ledger['input_fingerprint']!=packet['content_fingerprint'] or ledger['maximum_attempts']!=ceiling or ledger['approval_key']!=approval_key:
            raise ValueError('Ledger belongs to different packet/authorization/budget')
    else:
        ledger=dict(input_fingerprint=packet['content_fingerprint'],approval_key=approval_key,
                    authorization_scope='Exact six-source measurement run only; no collection activation or projection',maximum_attempts=ceiling,attempts=[])
    attempts=ledger['attempts'];by_key={a['request_key']:a for a in attempts}
    if len(attempts)!=len(by_key) or len(attempts)>ceiling or any(k not in {r['request_key'] for r in requests} for k in by_key):
        raise ValueError('Attempt ledger keys/count invalid')
    # Validate every existing receipt and failed attempt before creating provider.
    reused={}
    for request in requests:
        key=request['request_key'];path=receipt_dir/(key+'.json')
        if key in by_key:
            if not path.exists() or by_key[key]['status'] not in {'attempted','validated'}:
                raise ValueError('Previous failed/interrupted attempt requires separate recovery decision; no automatic replacement')
            receipt=json.loads(path.read_text());_verify_seal(receipt)
            if receipt['request_key']!=key or receipt['input_fingerprint']!=packet['content_fingerprint']:
                raise ValueError('Receipt identity mismatch')
            reused[key]=validate_response(receipt['response'],request)
            if by_key[key]['status']=='attempted':
                by_key[key].update(status='validated',usage=reused[key]['usage'],resolved_model=reused[key]['model'],
                                   recovery='validated_saved_raw_receipt_no_new_attempt')
        elif path.exists():raise ValueError('Orphan receipt without charged attempt; stop')
    if len(attempts)+len(requests)-len(reused)>ceiling:raise ValueError('Remaining budget cannot finish')
    if ledger_path.exists():
        dump(ledger_path,_seal({k:v for k,v in ledger.items() if k!='fingerprint'}))
    provider=None;rows=[]
    try:
        for request in requests:
            key=request['request_key']
            if key in reused:raw=reused[key]
            else:
                # Client construction occurs only after complete input, receipt,
                # authorization and spending checks. Reserve before network call.
                if provider is None:provider=provider_factory()
                if len(attempts)>=ceiling:raise ValueError('Attempt ceiling exhausted')
                attempt=dict(request_key=key,status='attempted',reserved_input_tokens=CONTEXT_TOKENS,
                             reserved_usd=str(PRICE*CONTEXT_TOKENS))
                attempts.append(attempt);dump(ledger_path,_seal({k:v for k,v in ledger.items() if k!='fingerprint'}))
                response=provider.assess(request)
                dump(receipt_dir/(key+'.json'),_seal(dict(input_fingerprint=packet['content_fingerprint'],request_key=key,response=response)))
                raw=validate_response(response,request)
                attempt.update(status='validated',usage=raw['usage'],resolved_model=raw['model'],request_id=response.get('request_id'))
                dump(ledger_path,_seal({k:v for k,v in ledger.items() if k!='fingerprint'}))
            rows.append(dict(request_key=key,capability=request['capability'],candidate_ids=request['candidate_ids'],raw_answers=raw['answers'],usage=raw['usage'],resolved_model=raw['model'],receipt_path=str(receipt_dir/(key+'.json'))))
    except BaseException:
        # An interruption leaves an attempted reservation, and cannot silently
        # retry a lost reply. Immutable raw receipts remain available for review.
        raise
    finally:
        if provider is not None:provider.close()
    report=interpret(packet,rows,requests=requests)
    dump(output_dir/'results-v2.json',report)
    (output_dir/'results-v2.md').write_text(render_results(report))
    return report


def interpret(packet,rows,*,requests=None):
    from pastor_transcript_extractor.sermon_g2_feasibility_review import decision
    by_candidate={};duplicate=set();observations=[]
    request_map={r['request_key']:r for r in (requests or [])}
    candidate_map={c['candidate_id']:c for c in packet['candidate_manifest']}
    for row in rows:
        for pos,cid in enumerate(row['candidate_ids']):
            if cid in by_candidate:duplicate.add(cid)
            answers=row['raw_answers']
            if row['capability'] in {'G2','G3'}:
                prefix=f'p{pos}_' if row['capability']=='G2' else f'q{pos}_'
                answers={k.removeprefix(prefix):v for k,v in answers.items() if k.startswith(prefix)}
            decisions={k:decision(v) for k,v in answers.items()}
            by_candidate[cid]=dict(decisions=decisions,request_key=row['request_key'])
            if row['request_key'] in request_map:
                state=request_map[row['request_key']]['state']; candidate=candidate_map[cid]
                if row['capability']=='G1':
                    from pastor_transcript_extractor.sermon_g1_feasibility_review import compose
                    payload=compose(state,state['candidate'],decisions)
                elif row['capability']=='G3':
                    from pastor_transcript_extractor.sermon_g3_feasibility_revision import provisional
                    payload=dict(kind='address',independent_decisions=decisions,
                                 provisional_current_listener_acts=provisional(decisions))
                else:
                    payload=dict(kind='relation',relation='explains_text',decision=decisions['explains_text'],
                                 adoption=decisions['adoption'],boundary=decisions['boundary'],
                                 left_voice=decisions['left_voice'],right_voice=decisions['right_voice'])
                observations.append(dict(candidate_id=cid,capability=row['capability'],video_id=candidate['video_id'],
                                         target_start=candidate['target_start'],target_end=candidate['target_end'],
                                         payload=payload,raw_answers=answers,request_key=row['request_key'],
                                         source_scope='supplied_passage',pastor_credit=False,
                                         population_rate=None,recurrence=None,comparison=None,quality_score=None))
    if duplicate:raise ValueError('Duplicate candidate outputs cannot be pooled')
    checks=[]
    for oracle in packet['funnel']:
        matches=[(cid,by_candidate[cid]) for cid in oracle['matching_candidate_ids'] if cid in by_candidate]
        evaluations=[]
        for cid,result in matches:
            differences=[];withheld=[];critical=[]
            for field,allowed in oracle['expected'].items():
                actual=result['decisions'].get(field)
                if actual in allowed:continue
                if actual in {'unclear','incomplete'}:withheld.append(field)
                else:
                    differences.append(dict(field=field,expected=allowed,actual=actual))
                    if (field in {'voice','left_voice','right_voice'} and actual=='preacher' and allowed==['quoted_or_reported']) or (field=='addressee' and actual=='direct_current_listener' and allowed==['God']):critical.append('wrong_source_or_speaker')
                    if field=='explains_text' and actual=='linked' and allowed==['not_linked']:critical.append('fabricated_proposition_relation_or_opposite')
            status='critical_integrity_failure' if critical else 'measurement_error' if differences else 'conservative_measurement_omission' if withheld else 'matches_frozen_fields'
            evaluations.append(dict(candidate_id=cid,status=status,decisions=result['decisions'],differences=differences,withheld_fields=withheld,critical_types=critical))
        # Any error stays visible even if another alias matches; never select a
        # convenient success and hide wrong output on a duplicate opportunity.
        status='not_supplied' if not oracle['matching_candidate_ids'] else 'not_measured' if not matches else 'critical_integrity_failure' if any(e['critical_types'] for e in evaluations) else 'measurement_error' if any(e['differences'] for e in evaluations) else 'matches_frozen_fields' if any(e['status']=='matches_frozen_fields' for e in evaluations) else 'conservative_measurement_omission'
        checks.append(dict(check_id=oracle['check_id'],reference_id=oracle['reference_id'],capability=oracle['capability'],opportunity=oracle['opportunity'],status=status,evaluations=evaluations))
    usage=dict(attempts=len(rows),input_tokens=sum(r['usage']['input_tokens'] for r in rows),output_tokens=sum(r['usage']['output_tokens'] for r in rows))
    return dict(version=VERSION,status='evaluated_pending_Codex_source_audit_and_Brian_decision',input_fingerprint=packet['content_fingerprint'],raw_rows=rows,observations=observations,reference_checks=checks,check_counts=dict(Counter(c['status'] for c in checks)),usage=usage,
                actual_list_price_usd=str(Decimal(usage['input_tokens'])*PRICE),usable_evidence_items=None,cost_per_usable_item=None,
                unreviewed_positive_outputs='All non-reference positives and candidate granularity/stance need Codex source review; matching selected fields does not certify semantic truth.',
                corpus_recall=None,pastor_projection=None,quality_score=None)


def render_results(report):
    return '\n'.join(['# Evidence supply V2 bounded results','', '**Pending Codex source audit and Brian decision; no automatic readiness PASS.**','',
                      f"Requests: {report['usage']['attempts']}; input tokens: {report['usage']['input_tokens']}; output tokens: {report['usage']['output_tokens']}; list-price cost: ${report['actual_list_price_usd']}.", '',
                      '| Reference check status | Count |','| --- | --- |',*[f'| {k} | {v} |' for k,v in report['check_counts'].items()], '',
                      'All raw answers, exact source/request provenance and every mismatch/withholding remain in results-v2.json. Usable unique local evidence and its unit cost require source audit and stay null. Collection activation, population recall/calibration, operational denominators, projection/comparison, recurrence/G4/scoring remain held.',''])


def render_review(packet):
    rows=packet['funnel'];counts=Counter(c['capability'] for c in packet['candidate_manifest']);supplied=Counter(r['capability'] for r in rows if r['matching_candidate_ids']);allrefs=Counter(r['capability'] for r in rows)
    lines=['# Evidence-supply readiness V2 prepared review','', '**Provider-free V2 prepared. Paid execution is not authorized. No readiness PASS.**','',
           f"Six unchanged recording identities; {packet['reference_count']} independent focal reference checks. V1 sources, 110 episodes, candidate prototype and accepted G1/G2/G3/consumer decisions remain unchanged. V2 retains those episode IDs, documents exact-endpoint refinements, and adds R111–R114 from restored transitions.", '',
           '## Source and reference review','',
           'Full available main-sermon text and both transcript transitions are independently reviewed. Authored boundaries are in the separate source snapshots; production extraction and speaker membership are untouched. This is complete review of the available recording text, not a claim of perfect captions, missing-audio recovery or an exhaustive universal inventory of every possible atomic edge. Boundaries and exact expectations are concrete inputs for Brian to approve with this packet. No pastor credit is given outside existing reviewed speaker spans.', '',
           '## Source-wide supply before measurement','',
           '| Route | Source-wide candidates | Exact focal checks supplied | All focal checks |','| --- | --- | --- | --- |']
    for cap in ('G1','G2','G3'):lines.append(f'| {cap} | {counts[cap]} | {supplied[cap]} | {allrefs[cap]} |')
    lines+=['', 'There is no sermon-level eight-target cutoff or silent execution truncation. The four-content-sentence neighbor horizon is explicit. Caption newlines are retained as source whitespace; pure discourse fillers remain in targets/context rather than becoming endpoints. Missed long-distance or spanning endpoints remain misses, not measured negatives. Exact source-span supply is distinct from correct semantic observation.', '',
            'G1 local sentence targets retain contiguous framing and bounded context and fit the existing eight-frame/six-phrase ceilings. Source-span retrieval additionally offers literal pardoned/assurance anchors; G1 question factories, relation meanings, thresholds and composition are unchanged. This is a collection change, not G1 V3. The city-ramp natural-positive route remains blocked; unrelated public-policy material never substitutes.', '',
            '## Fixed run proposal and spending ceiling','',
            f"Maximum {packet['budget']['maximum_attempts']:,} cumulative attempts, including failed/lost replies. G2 packs up to eight endpoint pairs per shared source tile and asks only its accepted text-explanation/stance/boundary/voice fields; G3 packs up to three candidates with reversible source-pointer binding. Canonical question meanings/options remain unchanged. Both repack to meet the body bound; G1 remains one exact claim per request. Zero automatic retries; pinned `{MODEL}`; no natural-state answer reuse from unlike pilot contexts.", '',
            f"Maximum reserved input tokens: {packet['budget']['maximum_input_tokens']:,}. Maximum public-list-price spend: **${packet['budget']['maximum_list_price_usd']}**. Reserve the documented default 64,000-token combined request limit for every attempt; output is free at the verified $0.042/M input price. Long-context is explicitly disabled. This is a conservative service-limit ceiling, not a token estimate or corpus economics study ([pricing/context](https://docs.typesafe.ai/models), [API](https://docs.typesafe.ai/api)). Actual token/cost receipts replace neither failed-attempt reservations nor the fixed ceiling.", '',
            'Preflight checks every source/code hash, candidate/request/question identity, exact references, live extraction/membership snapshot, prior receipt and cumulative budget before provider construction. Every returned raw HTTP body is saved before JSON/answer validation. A malformed, failed or interrupted attempt stops without an automatic replacement. No spending is authorized by prepare/check/preflight commands.', '',
            'The full proposal is deliberately larger than the V1 budget-truncated prototype. Request count and spending are explicit for review; Codex does not run or monitor it. Known unsupplied references mean the full reference-slate route cannot already claim complete discovery PASS, even if its supplied checks later measure well.', '',
            '## Exact commands','', 'Provider-free checks:', '', '```sh', 'pte analysis evidence-supply-review --revision v2 --check-only',
            'pte analysis evidence-supply-review --revision v2 --paid-run-preflight', '```', '',
            'Prepared paid command, **only after Brian separately approves this exact packet, scope and ceiling**:', '', '```sh',
            'pte analysis evidence-supply-review --revision v2 --execute \\',
            f"  --approve-paid-packet {packet['content_fingerprint']}", '```', '',
            'That opt-in records approval of the fixed diagnostic inputs/boundaries/expectations and cumulative budget, not production membership edits or broader collection. Results are evaluation/evidence-supply-readiness-v2/results-v2.md and results-v2.json; raw receipts and request ledger remain alongside them. Reruns require the same opt-in and reuse validated receipts; failed attempts require a separate concrete recovery decision.', '',
            '## Acceptance and continuing holds','',
            'The unit-cost denominator is frozen before execution: one unique source-audited G1 claim, directed G2 explanation pair, or G3 utterance/circumstance record with a supported positive fact. Fully bound/adopted, partial and report-only records are separate counts. A known act with withheld binding can remain a useful partial record. Duplicate aliases count once; unknown-only outputs and correct no-match controls do not inflate usable-positive counts. Local-negative checks are reported separately.', '',
            'Critical integrity failures have zero tolerance: wrong source/speaker, invented proposition/relation/opposite, context promoted to target, incompatible reuse or lost provenance. Measurement errors, conservative positive withholding, correctly withheld ambiguous cases and discovery misses stay separate. No successful alias can hide a wrong alias. All non-reference positive outputs need source audit. Field checks are prepared references, not indisputable gold; source-supported expectation disputes must be separately documented, never silently overwritten.', '',
            'After Brian runs an approved command, Codex audits every positive, mismatch, omission and withholding and recommends scoped PASS/PARTIAL/FAIL; Brian records a separate decision. Actual usable-item counts and cost per usable item are null until that source audit. No population fractions, corpus cost extrapolation, pastor rates/recurrence, comparison, clustering, G4/coherence or scoring are activated. G1/G2/G3 construct tuning and the accepted consumer remain closed.', '']
    return '\n'.join(lines)


def write_packet(packet,output_dir=HERE):
    validate_packet(packet,reproduce=False)
    output_dir=Path(output_dir);path=output_dir/'input-v2.json'
    if path.exists() and json.loads(path.read_text())!=packet:raise ValueError('Frozen V2 differs; preserve/version it rather than overwrite')
    dump(path,packet)
    (output_dir/'REVIEW.md').write_text(render_review(packet))
    dump(output_dir/'funnel-v2.json',packet['funnel'])
    sources={v:json.loads((HERE/'sources'/f'{v}.json').read_text()) for v in v1.SOURCE_IDS};refs=json.loads((HERE/'references-v2.json').read_text());byid={r['reference_id']:r for r in packet['funnel']}
    lines=['# V2 exact natural reference cases','', 'Independent source checks; no provider outputs. Original V1 episode IDs and labels remain preserved separately.','']
    for row in refs['rows']:
        lines += [f"## {row['reference_id']} — {row['video_id']} {row['capability']}",'',row['rationale'],'']
        for check in row['checks']:
            lines += ['Expected field values: `'+json.dumps(check['expected'],ensure_ascii=False)+'`.','']
            for k in ('left','right','claim','circumstance','utterance'):
                if check.get(k):lines += [f"**{k}** [{check[k]['start']},{check[k]['end']}):",'', '```text',check[k]['text'].replace('```','` ` `'),'```','']
        hits=byid[row['reference_id']]['matching_candidate_ids'];lines+=['Exact candidate aliases: '+(', '.join(hits) if hits else '**not supplied**')+'.','']
    lines+=['## Explicit V1 → V2 reference refinements','',*['- '+json.dumps(c,ensure_ascii=False) for c in refs['reference_changes']],'']
    (output_dir/'CASES.md').write_text('\n'.join(lines))
