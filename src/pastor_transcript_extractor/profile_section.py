"""Bounded section adapter over shared source bindings, profile support and handoff."""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
import json
import re
from . import response_growth_binding as producer
from . import profile_analysis_support_execution as x
from . import profile_support_budget as allowance
from . import segment_cache_inventory, sermon_topics
from .pastor_evidence import SourceWindow, EvidenceArtifactStore as Store, digest
from .profile_support_validation import file_hash

VERSION = 'profile-section-v1'
WINDOWS = ((281,122,124), (3973,68,70), (3973,74,78), (3973,88,97),
           (4589,43,48), (4589,49,51))
LIMIT = ('Six selected development windows in three exposed recordings; not a representative '
    'sample, exhaustive theology, frequency estimate or independent generalization. '
    'Invitations do not establish audience uptake. Quarantined legacy leaves remain quarantined.')
UNKNOWN = ['Completeness outside the six windows and unrecovered points within them',
    'Frequency, dominance, comparative priority, causal effects and ministry-wide stability',
    'Actual listener response or saving state; a complete doctrine of perseverance or loss',
    'Admitted repentance/obedience measurements and independent holdout generalization']


def identity():
    return {m.__name__:file_hash(m.__file__) for m in (producer, producer.source_context,
        producer.contract, producer.reading_diagnostics, producer.evidence, x, x.core, x.requests,
        x.provider, x.correction, x.streaming, x.supervised, allowance)} | {__name__:file_hash(__file__)}


def inventory(base_dir):
    return segment_cache_inventory.build(base_dir, profile_id=318, video_ids=(281,3973,4589))


def windows(inv):
    sources = {s['video_id']:s for s in inv['sermons']}
    result = []
    for vid, first, last in WINDOWS:
        s = sources[vid]
        if file_hash(s['source_path']) != s['source_sha256']:
            raise ValueError('Frozen source changed')
        raw = json.loads(Path(s['source_path']).read_text())
        analysis = sermon_topics.resolve_topic_analysis_artifact(raw['classification'])
        blocks = {b['block_id']:b for b in analysis['blocks']}
        ids = list(range(first,last+1))
        if not set(ids) <= set(s['eligible_block_ids']):
            raise ValueError('Frozen window includes an ineligible block')
        selected = tuple(dict(block_id=k, target_text=sermon_topics.resolve_topic_block_context(blocks[k])['target_text'],
            **{f:blocks[k][f] for f in ('start_seconds','end_seconds','segment_indexes')}) for k in ids)
        result.append(SourceWindow(f'v{vid}b{first}-{last}',318,vid,s['source_sha256'],first,
            selected,'selected_gap_and_contrast'))
    return result


def prepare(base_dir, objective, previous_allowance):
    base_dir = Path(base_dir).resolve()
    ref, auth = allowance.authorize_readiness(base_dir, objective, previous_allowance)
    inv = inventory(base_dir)
    root = x.build_paths(base_dir).evaluation / VERSION / digest(auth['objective'])
    tasks = []
    for window in windows(inv):
        spec = producer.request(window)
        reserved = 2*x.requests.request_reservation(spec)+x.requests.reservation('source_verification')
        if reserved > Decimal('.50'):
            raise ValueError('Source batch exceeds fifty cents')
        tasks.append(dict(id=window.id, window=asdict(window), request=asdict(spec),
            reserved_usd=str(reserved), maximum_paid_attempts=3))
    # Fixed upper bound for support: at most twelve local points plus one membership
    # interpretation. Each is prepared and partitioned below fifty cents after binding.
    support_reserve = Decimal('1.25')
    maximum = sum((Decimal(t['reserved_usd']) for t in tasks), support_reserve)
    if maximum > Decimal(auth['additional_usd']):
        raise ValueError('Frozen complete sequence exceeds additional allowance')
    packet = dict(version=VERSION, base_dir=str(base_dir), profile=inv['selected_profile'],
        inventory_fingerprint=inv['content_fingerprint'], source_identity=[{k:s[k] for k in
            ('video_id','title','url','source_path','source_sha256','gate')} for s in inv['sermons']],
        coverage=inv['coverage'], tasks=tasks, acceptance_authorization=ref,
        budget=dict(spend_root=auth['spend_root'], cumulative_ceiling_usd=auth['cumulative_ceiling_usd'],
            starting_conservative_usd=auth['starting_conservative_usd'], additional_usd='3',
            maximum_batch_usd='.50', maximum_sequence_reservation_usd=str(maximum),
            support_reservation_usd=str(support_reserve)),
        policy=dict(semantic_iterations=2, mechanical_corrections=1, semantic_retries=0,
            maximum_source_windows=6, automatic_expansion=False, production_admission='not_admitted'),
        limitation=LIMIT, unknowns=UNKNOWN, code_identity=identity())
    packet['input_fingerprint'] = digest(packet)
    # Keep earlier freezes intact when a focused implementation fix changes code.
    root = root/'freezes'/packet['input_fingerprint']
    Store(root).write_immutable('plan.json', packet)
    (root/'plan.md').write_text('# Bounded automatic section\n\n'+LIMIT+'\n\n'+
        json.dumps(dict(budget=packet['budget'], source_batches=[{k:t[k] for k in
            ('id','reserved_usd','maximum_paid_attempts')} for t in tasks]),indent=2)+'\n')
    return dict(plan=str(root/'plan.json'), input_fingerprint=packet['input_fingerprint'],
        budget=packet['budget'], source_batches=[t['id'] for t in tasks], paid_calls=0)


def load(path):
    path = Path(path); p = json.loads(path.read_text())
    if p['input_fingerprint'] != digest({k:v for k,v in p.items() if k!='input_fingerprint'}):
        raise ValueError('Section freeze differs')
    if p['code_identity'] != identity():
        raise ValueError('Section implementation changed after freeze')
    allowance.ceiling(p)
    inv = inventory(Path(p['base_dir']))
    if (inv['content_fingerprint'] != p['inventory_fingerprint'] or
        digest([asdict(w) for w in windows(inv)]) != digest([t['window'] for t in p['tasks']])):
        raise ValueError('Membership, inventory or complete source windows changed')
    return p, path.parent


def ledger(p, root):
    with x.supervised.cumulative_history(p, root/'ledger') as history:
        return x.supervised.BASELINE_SPEND + sum((c for _,c in history), Decimal(0))


def obtain(p, spec, transport):
    """Existing shared accounting namespace; failed/unreceipted work cannot resend."""
    target = x._store(p, spec)
    with x.supervised.cumulative_history(p, target.root) as history:
        spent = x.supervised.BASELINE_SPEND + sum((c for _,c in history),Decimal(0))
        cached = x._cached(spec,target)
        if cached is None:
            if spent+x.requests.request_reservation(spec) >= allowance.ceiling(p):
                raise ValueError('Goal allowance exhausted')
            paid = x.requests.request_provider(spec)=='DeepInfra'
            guard = (x.provider.OneRequestLedger(str(x.requests.request_reservation(spec)),spec.version)
                if paid else x.requests.BudgetLedger(max_attempts=1))
            x.requests.execute(spec,guard,target,transport)
            cached = x._cached(spec,target)
        if cached is None or cached['halt'] or cached['response'] is None:
            raise ValueError('Incomplete or unknown usage; stop without retry')
    return cached, target.root/'receipts'/f'{spec.fingerprint}.json'


def run_source(path, batch, approve_input, *, check_only=False, transport=None):
    p, root = load(path)
    if approve_input != p['input_fingerprint']:
        raise ValueError('Exact frozen input approval required')
    task = next(t for t in p['tasks'] if t['id']==batch)
    for previous in p['tasks'][:p['tasks'].index(task)]:
        if not (root/'sources'/previous['id']/'result.json').exists():
            raise ValueError('Preceding source batch incomplete; no advancement after unknown usage')
    out = root/'sources'/batch
    if (out/'result.json').exists():
        return json.loads((out/'result.json').read_text())
    if check_only:
        return dict(status='CHECKED_NO_EXECUTION',batch=batch,reserved_usd=task['reserved_usd'])
    if ledger(p, root)+Decimal(task['reserved_usd']) >= allowance.ceiling(p):
        raise ValueError('Complete source batch reservation exceeds goal allowance')
    window = SourceWindow(**task['window']); spec = x.requests.RequestSpec(**task['request'])
    send = transport or x.provider.transport
    raw, receipt = obtain(p,spec,send)
    checked = producer.inspect(raw['response']['output'],window,spec,receipt)
    rounds = [dict(receipt=str(receipt),errors=checked['errors'])]
    if checked['errors']:
        corrected = x.requests.corrective_request(spec,raw['response']['output'],checked['errors'],
            producer.reading_diagnostics.CORRECTION)
        # Corrective context must fit its original frozen policy, never truncate.
        raw, receipt = obtain(p,corrected,send)
        spec = corrected
        checked = producer.inspect(raw['response']['output'],window,spec,receipt)
        rounds.append(dict(receipt=str(receipt),errors=checked['errors']))
    rows = []; verification = None
    if not checked['errors']:
        verifier = producer.verification(window,checked['observations'])
        if verifier:
            answer, vpath = obtain(p,verifier,transport or x.requests.typesafe_transport)
            verification = str(vpath)
            rows = producer.qualify(checked,answer['response'],verifier)
    result = dict(batch=batch,status='FAIL(component)' if checked['errors'] else 'COMPLETE',
        observations=rows, rounds=rounds, abstentions=checked.get('abstentions',[]),
        source_status=(checked.get('reading') or {}).get('status'), verification_receipt=verification,
        eligible=sum(r['section_eligibility']['eligible'] for r in rows),
        production_admission='not_admitted')
    Store(out).write_immutable('result.json',result)
    return result


def check_strength(claim):
    """Producer assertion-force contract, independent of model approval.

    Producers explicitly declare claim force; this is a structural gate, not an
    NLP claim detector. The unchanged historical main-question case is regression
    material with comparative_priority force and no warrant.
    """
    force = claim.get('assertion_force')
    if force not in ('local_observation','sample_membership','comparative_priority','dominance','frequency','causal'):
        raise ValueError('Explicit assertion force required')
    if force in ('comparative_priority','dominance','frequency','causal') and not claim.get('strength_warrant'):
        raise ValueError('Claim strength lacks explicit warrant')
    if re.search(r'\b(main question|dominant|predominant|most important|primarily|more often|causes)\b',claim['wording'],re.I) and not claim.get('strength_warrant'):
        raise ValueError('Comparative/causal wording requires an explicit strength warrant')


def assemble_record(p, results):
    """No transcript interpretation here: copy qualified upstream local statements."""
    observations = []
    for result in results:
        observations.extend(result['observations'])
    eligible = [o for o in observations if o['section_eligibility']['eligible']]
    claims = []
    for o in eligible:
        cid = 'section-'+o['id']
        claims.append(dict(id=cid,wording=o['response_growth']['reader_statement'],
            evidence_ids=[], machine_observation_ids=[o['id']], upstream_claim_ids=[],
            scope=dict(video_ids=sorted({r['video_id'] for r in o['source_refs']}),meaning='Selected complete source window only. '+LIMIT),
            assertion_force='local_observation', analytical_basis=producer.VERSION))
    facets = {f:[o['id'] for o in eligible if f in o['response_growth']['facets']] for f in producer.FACETS}
    hypotheses = []
    if all(facets[f] for f in ('personal_response','gradual_growth','reassurance','challenge')):
        premises = sorted(set(i for f in ('personal_response','gradual_growth','reassurance','challenge') for i in facets[f]))
        # Membership, not an explanatory relation or a claim about relative weight.
        conclusion = ('The selected examples include personal response, reassurance and challenge, '
            'alongside teaching about gradual growth. Their presence together supports reading '
            'the invitations with the attached growth qualifications; it does not establish '
            'their relative emphasis or a complete account of salvation.')
        h = dict(id='section-sample-connection', conclusion=conclusion,premise_ids=premises,
            inference_type='selected_example_membership',scope_video_ids=sorted({r['video_id'] for o in eligible if o['id'] in premises for r in o['source_refs']}),
            warrant='Each named facet is verified in an eligible upstream local binding. Co-presence warrants retaining them together; no causal or doctrinal reconciliation is inferred.',
            alternatives=['Selection may exaggerate how closely these themes are connected elsewhere.'],
            counterevidence_ids=[o['id'] for o in observations if o['binding']['adoption']['status'] in ('rejected','reported_not_adopted')],
            defeaters=['An erroneous upstream facet or lost qualification defeats this connection.'])
        hypotheses.append(h)
        claims.append(dict(id=h['id'],wording=h['conclusion'],evidence_ids=[],
            machine_observation_ids=premises, upstream_claim_ids=['section-'+i for i in premises],
            scope=dict(video_ids=h['scope_video_ids'],meaning=LIMIT),assertion_force='sample_membership',
            analytical_basis=h['warrant'],limits=h['defeaters'],alternative=h['alternatives']))
    for c in claims:
        check_strength(c)
    return dict(version=VERSION,profile=p['profile'],inventory_fingerprint=p['inventory_fingerprint'],
        source_identity=p['source_identity'],observations=[],machine_observations=observations,
        machine_windows={t['id']:t['window'] for t in p['tasks']},claims=claims,
        reader=dict(claims=claims,portrait=dict(entries=claims),synthesis_rule='Verified local examples and explicit selected-example membership only.'),
        coverage=p['coverage'],hypotheses=hypotheses,
        gaps=[dict(id='coverage',withheld='Complete profile characterization',cause=LIMIT,remedy='Independent holdout and broader separately authorized evidence')]+
            [dict(id='unknown-'+str(i),withheld=v,cause='Not established by selected evidence',remedy='Retain unknown') for i,v in enumerate(UNKNOWN)],
        production_admission='not_admitted')


def machine_case(record, claim):
    """Shared analysis-support seam: verify saved producer receipts, never repair them."""
    check_strength(claim)
    by_id = {o['id']:o for o in record['machine_observations']}
    sources = {}; bound = []; files = {}
    for oid in claim['machine_observation_ids']:
        o = by_id[oid]
        if not o['section_eligibility']['eligible'] or o['origin']!='machine_generated' or o['production_admission']!='not_admitted':
            raise ValueError('Machine binding is not eligible experimental evidence')
        source_ids = {r['window_id'] for r in o['source_refs']}
        if len(source_ids)!=1:
            raise ValueError('Binding needs exactly one complete source window')
        wid = next(iter(source_ids)); w = SourceWindow(**record['machine_windows'][wid])
        if w.video_id not in record['profile']['effective_member_video_ids']:
            raise ValueError('Machine binding outside declared membership')
        source = next(s for s in record['source_identity'] if s['video_id']==w.video_id)
        if not source['gate']['eligible'] or w.source_sha256!=source['source_sha256'] or file_hash(source['source_path'])!=w.source_sha256:
            raise ValueError('Machine source identity changed')
        raw = json.loads(Path(source['source_path']).read_text())
        blocks = {b['block_id']:b for b in sermon_topics.resolve_topic_analysis_artifact(raw['classification'])['blocks']}
        for block in w.blocks:
            actual = blocks[block['block_id']]
            if (block['target_text']!=sermon_topics.resolve_topic_block_context(actual)['target_text'] or
                any(block[k]!=actual[k] for k in ('start_seconds','end_seconds','segment_indexes'))):
                raise ValueError('Machine window geometry changed')
        ref = Path(o['raw_response_ref']); receipt = json.loads(ref.read_text()); spec=x.requests.RequestSpec(**receipt['request'])
        if receipt['halt'] or receipt['response_digest']!=digest(receipt['response']):
            raise ValueError('Machine producer receipt changed')
        x.requests.validate_response(spec,receipt['response'])
        checked = producer.inspect(receipt['response']['output'],w,spec,ref)
        rebuilt = next(r for r in checked['observations'] if r['id']==oid)
        # Verify original Jev answers and every retained binding/extension field.
        verifier=producer.verification(w,checked['observations'])
        vref=Path(o['verification_receipt']); vr=json.loads(vref.read_text())
        if vr['request']!=asdict(verifier) or vr['halt'] or vr['response_digest']!=digest(vr['response']):
            raise ValueError('Machine verification receipt changed')
        rebuilt=next(r for r in producer.qualify(checked,vr['response'],verifier) if r['id']==oid)
        rebuilt['verification_receipt']=str(vref)
        if rebuilt!=o:
            raise ValueError('Machine binding or eligibility changed')
        texts=w.target()[0]
        sources[wid]=dict(window=json.loads(json.dumps(asdict(w))),texts=texts,
            fields=x.core._inventory(w,texts),context_sha256=x.core.context_digest(texts))
        bound.append(deepcopy(o))
        files.update({str(ref):file_hash(ref),str(vref):file_hash(vref),source['source_path']:w.source_sha256})
    passages=[dict(passage_id=k,video_id=s['window']['video_id'],fields={f:[dict(id=u['id'],text=u['text']) for u in units] for f,units in s['fields'].items()}) for k,s in sources.items()]
    hypotheses=[h for h in record.get('hypotheses',[]) if h['id']==claim['id']]
    state=dict(candidate=dict(id=claim['id'],statement=claim['wording'],scope=claim['scope'],
        declared_caveats={k:claim[k] for k in ('limits','alternative') if k in claim},analytical_basis=claim['analytical_basis']),
        sample=dict(profile_id=record['profile']['id'],video_ids=record['profile']['effective_member_video_ids'],coverage=record['coverage']),
        bound_observations=bound,passages=passages,measurement_ledger=dict(rows=[],contracts=[],meaning='Qualified machine bindings; not legacy leaf measurements'),
        upstream_points=[],stored_aggregates=[],upstream_aggregate_claims=hypotheses,
        aggregation_contract=record['reader']['synthesis_rule'])
    return dict(state=state,sources=sources,input_ids={},dependencies=claim['upstream_claim_ids'],
        identity=dict(profile_id=record['profile']['id'],membership_fingerprint=record['profile']['membership_fingerprint'],inventory_fingerprint=record['inventory_fingerprint']),source_files=files)


def prepare_support(path):
    p, root = load(path); results=[]
    for t in p['tasks']:
        result=json.loads((root/'sources'/t['id']/'result.json').read_text())
        for o in result['observations']:
            o['verification_receipt']=result['verification_receipt']
        results.append(result)
    record=assemble_record(p,results)
    Store(root).write_immutable('assembled-profile.json',record)
    plan=x.core.build_plan(record); tasks=[]
    for item in plan['items']:
        if item['case'] is None:
            continue
        spec=x.make_request(item['case'],whole_statement=True)
        tasks.append(dict(claim_id=item['claim_id'],request=asdict(spec),token_account=spec.preflight(),correction=x.correction.policy(spec,headroom=True)))
    total=sum((x.requests.request_reservation(x.requests.RequestSpec(**t['request']))+Decimal(t['correction']['reserved_usd']) for t in tasks),Decimal(0))
    if total>Decimal(p['budget']['support_reservation_usd']):
        raise ValueError('Support exceeds frozen sequence reservation; no expansion')
    batches=[]; group=[];cost=Decimal(0)
    for task in tasks:
        amount=x.requests.request_reservation(x.requests.RequestSpec(**task['request']))+Decimal(task['correction']['reserved_usd'])
        if amount>Decimal('.50'):
            raise ValueError('Single support case exceeds batch cap')
        if group and cost+amount>Decimal('.50'):
            batches.append((group,cost));group=[];cost=Decimal(0)
        group.append(task);cost+=amount
    if group or not tasks:batches.append((group,cost))
    inputs=[]
    for i,(group,cost) in enumerate(batches):
        ids={t['claim_id'] for t in group}
        selection={**plan,'items':[item for item in plan['items'] if item['claim_id'] in ids]}
        packet=dict(version=x.core.VERSION,plan=selection,tasks=group,acceptance_authorization=p['acceptance_authorization'],
            budget={**p['budget'], 'max_usd':'.50','reserved_usd':str(cost),
                'maximum_paid_attempts':sum(2*t['token_account'].get('stream_recovery',{}).get('maximum_attempts',1) for t in group)})
        packet['input_fingerprint']=digest(packet)
        dest=root/'support'/f'{i+1:02d}'/'input.json'
        Store(dest.parent).write_immutable(dest.name,packet)
        inputs.append(str(dest))
    Store(root).write_immutable('support-plan.json',dict(plan=plan,inputs=inputs,profile_sha256=file_hash(root/'assembled-profile.json')))
    return dict(inputs=inputs,claims=len(plan['items']),eligible_bindings=sum(r['eligible'] for r in results),reserved_usd=str(total))


def run_support(path, batch, approve_input, *,check_only=False,transport=None):
    p,root=load(path)
    if approve_input!=p['input_fingerprint']:raise ValueError('Exact frozen approval required')
    frozen=json.loads((root/'support-plan.json').read_text())
    record=x.core.read_record(root/'assembled-profile.json')
    if file_hash(root/'assembled-profile.json')!=frozen['profile_sha256'] or x.core.build_plan(record)!=frozen['plan']:
        raise ValueError('Assembled evidence or plan changed')
    input_path=Path(frozen['inputs'][int(batch)-1]);packet=json.loads(input_path.read_text())
    if packet['input_fingerprint']!=digest({k:v for k,v in packet.items() if k!='input_fingerprint'}):
        raise ValueError('Support packet changed')
    if check_only:return dict(status='CHECKED_NO_EXECUTION',budget=packet['budget'])
    return x.recipe(packet,input_path.parent,transport or x.provider.transport)


def render(path):
    p,root=load(path);frozen=json.loads((root/'support-plan.json').read_text());rows=[]
    for name in frozen['inputs']:
        rows.extend(json.loads((Path(name).parent/'results.json').read_text())['results'])
    document=x.core.document_input(frozen['plan'],rows)
    record=x.core.read_record(root/'assembled-profile.json')
    document['section_trace']={c['id']:dict(evidence_ids=c['machine_observation_ids'],
        premise_ids=c['upstream_claim_ids'],scope=c['scope'],assertion_force=c['assertion_force'],
        interpretation=next((h for h in record['hypotheses'] if h['id']==c['id']),None)) for c in record['claims']}
    document['unknowns']=p['unknowns']; document['limitation']=LIMIT
    Store(root).write_immutable('document-input.json',document)
    lines=['# Salvation, personal response and spiritual growth','',LIMIT,'']
    sources={t['id']:t['window'] for t in p['tasks']}
    obs={o['id']:o for o in record['machine_observations']}
    for entry in document['entries']:
        if entry['support_status']!='supported':continue
        links=[]
        for oid in document['section_trace'][entry['claim_id']]['evidence_ids']:
            window=sources[obs[oid]['source_refs'][0]['window_id']]
            source=next(s for s in p['source_identity'] if s['video_id']==window['video_id'])
            url=source['url']+('&' if '?' in source['url'] else '?')+'t='+str(int(window['blocks'][0]['start_seconds']))
            link=f"[Recording {window['video_id']}, blocks {window['blocks'][0]['block_id']}–{window['blocks'][-1]['block_id']}]({url})"
            if link not in links:links.append(link)
        lines.extend([entry['statement']+' '+'; '.join(links), '',f"Trace: `{entry['claim_id']}`",''])
    if not document['ready_claim_ids']:
        lines.extend(['No substantive paragraph passed all upstream and analysis-support gates.',''])
    lines.extend(['## Limits and unknowns','']+['- '+u for u in UNKNOWN]+['','## Withheld clauses',''])
    lines += [f"- {e['statement']} ({e['support_status']})" for e in document['entries'] if e['support_status']!='supported']
    (root/'draft-section.md').write_text('\n'.join(lines)+'\n')
    (root/'analysis-support.md').write_text(x.core.render_handoff(document))
    spent=ledger(p,root);start=Decimal(p['budget']['starting_conservative_usd'])
    report=dict(draft=str(root/'draft-section.md'),document_input=str(root/'document-input.json'),
        model_supported=len(document['ready_claim_ids']),clauses=len(document['entries']),
        eligible_upstream=sum(o['section_eligibility']['eligible'] for o in obs.values()),
        upstream_total=len(obs),starting_conservative_usd=str(start),cumulative_conservative_usd=str(spent),
        new_conservative_usd=str(spent-start),remaining_credit_usd=str(allowance.ceiling(p)-spent),
        semantic_acceptance='Pending separate source review of original outputs',production_admission='not_admitted')
    Store(root).write_immutable('delivery.json',report)
    return report


def failure_handoff(path):
    """Close an unknown-usage stop without another provider call or evidence repair.

    This historical/report path verifies the original frozen requests and sources,
    rather than requiring the reporting implementation to equal the execution freeze.
    It cannot prepare or execute new requests.
    """
    path=Path(path);p=json.loads(path.read_text());root=path.parent
    if p['input_fingerprint']!=digest({k:v for k,v in p.items() if k!='input_fingerprint'}):
        raise ValueError('Section freeze differs')
    limit=allowance.ceiling(p)
    inv=inventory(Path(p['base_dir']))
    if inv['content_fingerprint']!=p['inventory_fingerprint'] or digest([asdict(w) for w in windows(inv)])!=digest([t['window'] for t in p['tasks']]):
        raise ValueError('Frozen membership/source identity changed')
    attempts=[]
    for task in p['tasks']:
        spec=x.requests.RequestSpec(**task['request']);spec.preflight()
        store=x._store(p,spec)
        for attempt in store.attempts():
            if attempt['request_fingerprint']!=spec.fingerprint:
                raise ValueError('Foreign source attempt')
            receipt=store.root/'receipts'/f'{spec.fingerprint}.json'
            if receipt.exists():
                x._cached(spec,store)
            account=x.supervised.check.demo.usage_account(store)
            attempts.append(dict(batch=task['id'],request_fingerprint=spec.fingerprint,
                attempt_path=str(store.root/'attempts'/f'{spec.fingerprint}.json'),
                receipt_path=str(receipt),receipt_present=receipt.exists(),accounting=account))
    uncertain=[a for a in attempts if a['accounting']['unknown_usage_attempts']]
    if not uncertain:
        raise ValueError('Failure handoff requires a demonstrated unknown-usage stop')
    if any((root/'sources'/t['id']/'result.json').exists() for t in p['tasks']):
        raise ValueError('Completed source results require ordinary assembly; do not discard evidence')
    out=root/'failure'
    record=assemble_record(p,[])
    gap=dict(id='source-transport-unknown-usage',withheld='A substantive account of salvation, requested personal response, spiritual growth and reassurance/challenge in this sample',
        cause='The frozen source request has a durable paid attempt but no complete usage-bearing receipt. All subsequent paid work is stopped.',
        inspected_reuse=['Completed evidence-reuse audit: three compatible materialized sources, nine existing salvation meanings; three quarantined meanings unchanged.',
            'Saved machine bindings retain partial/unverified authority and do not supply complete compatible response/growth evidence.',
            'Frozen source request cache: attempt present, complete receipt absent. No replacement output or manual source reading is runtime evidence.'],
        missing_information='A complete accounted response and qualified upstream observations for the frozen windows.',
        responsible_producer='Shared DeepInfra source transport/receipt boundary before response_growth_binding and Jev qualification',
        remedy='Reconcile the original request usage/termination before proposing a separately authorized frozen recovery. No retry, next window, model switch or successor experiment in this delivery.',
        acceptance='Original attempt usage reconciled; any separately authorized recovery has durable accounting and passes unchanged literal/field gates.',
        authorization_boundary='Current unknown-usage stop remains in force; no additional paid execution.')
    record['gaps'].insert(0,gap)
    plan=x.core.build_plan(record)
    document=x.core.document_input(plan,[])
    document.update(section_trace={},unknowns=p['unknowns'],limitation=LIMIT,
        delivery_status='FAILED_UPSTREAM_TRANSPORT',unresolved_section_requirements=[
            'How the selected sample presents salvation', 'What personal response is requested or described',
            'How conditions and qualifications distinguish growth from immediate perfection',
            'How supported reassurance and challenge relate within the selected sample'],
        source_execution=attempts)
    Store(out).write_immutable('assembled-profile.json',record)
    Store(out).write_immutable('document-input.json',document)
    Store(out).write_immutable('clause-trace.json',dict(clauses=[],reason='No clause is released without qualified upstream evidence and analysis support.'))
    draft=('# Salvation, personal response and spiritual growth\n\n'
        'Analysis unavailable for this bounded delivery. The first source check ended without '
        'a complete response or known usage. No substantive paragraph is released.\n\n'
        'The prepared sample comprises recordings 281, 3973 and 4589. How it presents salvation, '
        'personal response, growth and reassurance/challenge remains unresolved in this delivery. '
        'This is a collection failure, not evidence that those subjects are absent.\n')
    (out/'draft-section.md').write_text(draft)
    (out/'analysis-support.md').write_text(x.core.render_handoff(document))
    spent=ledger(p,root);start=Decimal(p['budget']['starting_conservative_usd'])
    assessment=dict(status='FAILED_BOUNDED_DELIVERY',plan=str(path),input_fingerprint=p['input_fingerprint'],
        implementation_at_freeze=p['code_identity'],report_implementation=identity(),
        draft=str(out/'draft-section.md'),document_input=str(out/'document-input.json'),clause_trace=str(out/'clause-trace.json'),
        source_execution=attempts,blocked_statement=gap,
        assessment=dict(mechanical='Live source transport failed before a complete response; prior 70 focused offline tests passed.',
            model_approval='Not obtained; no source binding, Jev judgment or Qwen support result exists.',
            claim_fidelity='Not assessable: zero generated/released substantive clauses.',
            retained_qualifications='Not assessable: no qualified observations generated.',
            omissions='The entire requested substantive section is withheld; prior full-source omission findings remain unresolved.',
            contrary_evidence='No adopted stance or refutation is inferred. Frozen contrasts were not assessed by this execution.',
            usefulness='Failure handoff and blocker are inspectable; the requested useful analysis section was not delivered.',
            coverage='One source request attempted; no completed windows. Five other frozen windows and downstream stages were not run.',
            semantic_acceptance='FAIL: substantive deliverable unavailable; no accuracy or generalization claim.'),
        costs=dict(actual_invoice_usd=None,provider_estimated_usd=None,known_usage_usd=None,
            unknown_usage_attempts=sum(a['accounting']['unknown_usage_attempts'] for a in attempts),
            starting_conservative_usd=str(start),new_conservative_usd=str(spent-start),
            cumulative_conservative_usd=str(spent),remaining_goal_credit_usd=str(limit-spent)),
        production_admission='not_admitted',next_step=gap['remedy'],paid_execution_stopped=True)
    Store(out).write_immutable('assessment.json',assessment)
    (out/'assessment.md').write_text('# Bounded section delivery failed at source transport\n\n'+
        '\n\n'.join(f'**{k.replace("_"," ")}:** {v}' for k,v in assessment['assessment'].items())+
        '\n\n## Costs\n\n'+json.dumps(assessment['costs'],indent=2)+
        '\n\nActual provider billing is unknown; the complete lost-request reservation remains charged. No retries or successor checks ran.\n\n## Smallest responsible blocker\n\n'+
        gap['cause']+' '+gap['remedy']+'\n')
    return assessment
