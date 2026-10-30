"""Readiness review artifacts, isolated from inference and reference judgments."""
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
import json
from . import profile_support_regression as regression
from . import profile_support_readiness as readiness
from . import profile_analysis_support_execution as x
from . import profile_evidence_supply as supply
from . import segment_cache_inventory as inventory_module

VERSION='profile-support-readiness-review-v1'


def reference(path):
    path=Path(path).resolve()
    return dict(path=str(path),sha256=readiness.file_hash(path))


def diagnostic_prepare(root):
    """Two demonstrated judgment gaps; no expected decisions in model context."""
    root=Path(root);work=json.loads((root/'work-plan.json').read_text());prior=Path(work['prior_acceptance'])
    old=json.loads((prior/'plan.json').read_text());record=x.core.read_record(old['profile_input']['path']);plan=x.core.build_plan(record)
    ids={'reader-portrait-question','reader-portrait-posture'}
    plan['selection']=dict(mode='two_demonstrated_judgment_gaps',assembled_total=len(plan['items']))
    plan['items']=[i for i in plan['items'] if i['claim_id'] in ids]
    if {i['claim_id'] for i in plan['items']}!=ids:raise ValueError('Demonstrated candidate inventory changed')
    tasks=[]
    for item in plan['items']:
        spec=x.make_request(item['case'],whole_statement=True)
        tasks.append(dict(claim_id=item['claim_id'],request=asdict(spec),token_account=spec.preflight(),correction=x.correction.policy(spec,headroom=True)))
    reserve=sum((x.requests.request_reservation(x.requests.RequestSpec(**t['request']))+Decimal(t['correction']['reserved_usd']) for t in tasks),Decimal(0))
    if reserve>Decimal('.50'):raise ValueError('Diagnostic exceeds fifty-cent batch ceiling')
    auth=json.loads((root/'allowance.json').read_text())
    p=dict(version=VERSION,plan=plan,tasks=tasks,profile_input=old['profile_input'],runtime_input=old['profile_input'],
        acceptance_authorization=reference(root/'allowance.json'),module_identity=reference(__file__),
        code_identity=readiness.code_identity()|{regression.__name__:readiness.file_hash(regression.__file__)},
        budget=dict(max_usd='.50',reserved_usd=str(reserve),maximum_paid_attempts=sum(t['token_account'].get('stream_recovery',{}).get('maximum_attempts',1)+max(v['runtime_identity'].get('stream_recovery',{}).get('maximum_attempts',1) for v in t['correction']['allowed_tiers']) for t in tasks),spend_root=auth['spend_root'],cumulative_ceiling_usd=auth['cumulative_ceiling_usd']))
    p['input_fingerprint']=x.digest(p);out=root/'judgment-diagnostic'/p['input_fingerprint'];x.Store(out).write_immutable('input.json',p)
    return dict(input=str(out/'input.json'),input_fingerprint=p['input_fingerprint'],budget=p['budget'],generation_calls=0,limitation='Exposed development cases; not holdout accuracy')


def diagnostic_run(path,approve_input,*,check_only=False,progress=None):
    p=json.loads(Path(path).read_text())
    if p['module_identity']!=reference(__file__):raise ValueError('Diagnostic adapter changed after freeze')
    current=x.core.build_plan(x.core.read_record(p['profile_input']['path']));items={i['claim_id']:i for i in current['items']}
    if any(items.get(i['claim_id'])!=i for i in p['plan']['items']):raise ValueError('Diagnostic evidence changed')
    return regression.run(path,approve_input,check_only=check_only,progress=progress)


def reuse_audit(record,base_dir):
    videos=sorted(s['video_id'] for s in record['source_identity'])
    inventory=inventory_module.build(base_dir,profile_id=record['profile']['id'],video_ids=videos)
    sources={s['video_id']:json.loads(Path(s['source_path']).read_text()) for s in inventory['sermons']}
    checks=supply.inspect(inventory,sources)
    return dict(status='EXACT_REGISTERED_CONSTITUENTS_INSPECTED',checks=checks,
        exact_identities=sum(len(c['attempts']) for c in checks),compatible_answers=sum(len(c['matches']) for c in checks),
        compatible_materialized_layers=inventory['coverage'],
        bound_reuse=dict(records=len(record.get('evidence_supply',{}).get('reviewed_bound_records',[])),checks=record.get('evidence_supply',{}).get('reviewed_binding_checks',[])),
        missing_producer_contracts={
            'public-life-specificity':dict(existing='public_life_treatment measures treatment form, not qualified support of a particular public-life proposition',missing='proposition/evaluated target, voiced speaker, preacher adoption, polarity, conditions',owner='sermon_leaf_packs.PUBLIC_LIFE_TREATMENT plus theological_binding.bind upstream of profile assembly',acceptance='Report and rejection controls cannot become adopted public positions; qualification belongs to the source proposition'),
            'source-tradition-and-pastoral-tone':dict(existing='source_material measures source form; listener_directives measures specified appeals; neither alone establishes adopted interpretive authority or characteristic tone',missing='source-use/adoption relation and addressed act/recipient/circumstance, with coverage denominator',owner='sermon_leaf_packs.SOURCE_MATERIAL / LISTENER_DIRECTIVES and shared upstream bindings',acceptance='Quoted sources need not be endorsed; projected/direct address remains distinct from actual audience compliance'),
            'growth-and-repentance-qualifications':dict(existing='nine admitted salvation leaves and local reviewed bound proposals',missing='three quarantined repentance and obedience condition/consequence distinctions with attached growth qualifications across relevant contexts',owner='sermon_salvation_relationships and theological_binding.bind',acceptance='Separate source-supported condition, consequence, mistake, deliberate conduct and gradual growth; retain current quarantines until separately validated')},
        limit='No inference, cache writes, composition, migration, new measurement, or admission. Exact source/context/question/model policy only; absence is not a global arbitrary-file census.')


def holdout_audit(base_dir,prior):
    """Metadata and prior exposure only. Never inspect new profile prose."""
    from . import sermon_topic_profile_analysis as topics
    from .storage import Database
    paths=x.build_paths(base_dir);db=Database(paths.database,readonly=True)
    with db.connect() as c:
        runs=[dict(r) for r in c.execute('SELECT video_id, MAX(id) AS run_id FROM sermon_analysis_runs WHERE analyzer_key=? AND analyzer_version=? GROUP BY video_id ORDER BY video_id',(topics.TOPIC_SERMON_ANALYZER_KEY,topics.TOPIC_SERMON_ANALYZER_VERSION))]
    # The existing adapter deliberately caps at twelve. Never silently exclude a
    # thirteenth candidate or widen into an unbounded source inspection.
    if len(runs)>inventory_module.MAX_SOURCES:raise ValueError('Current metadata exceeds bounded holdout inventory; freeze a selection before source inspection')
    inv=inventory_module.build(base_dir)
    reviews=paths.evaluation/'sermon-topics/source-material-review-v1.json';raw=json.loads(reviews.read_text())
    exposed=set()
    def walk(v):
        if isinstance(v,dict):
            if type(v.get('video_id')) is int:exposed.add(v['video_id'])
            for value in v.values():walk(value)
        elif isinstance(v,list):
            for value in v:walk(value)
    walk(raw)
    by_profile={}
    for row in inv['candidates']:
        by_profile.setdefault(row['profile_id'],[]).append(row)
    candidates=[]
    for pid,rows in sorted(by_profile.items()):
        vids=sorted(r['video_id'] for r in rows);overlap=sorted(set(vids)&exposed)
        status='exposed_profile_support_development' if pid in (318,130) else 'exposed_category_development' if overlap else 'requires_frozen_assembly_and_exposure_proof'
        candidates.append(dict(profile_id=pid,recordings=vids,compatible_recordings=[r['video_id'] for r in rows if r['status']=='compatible'],profile_metadata={k:v for k,v in asdict(db.get_speaker_profile(pid)).items() if k!='created_at'},exposed_recordings=overlap,status=status))
    return dict(status='UNTOUCHED_HOLDOUT_NOT_ESTABLISHED',metadata_scope='All persisted current-version topic-run recording IDs; twelve existing recordings; no collection or classification',current_run_metadata=runs,candidates=candidates,prior_assembled_profile_inventory=reference(prior/'holdout-inspection-v1.json'),exposure_reference=reference(reviews),
        smallest_remedy='An accepted third profile with already compatible materialized evidence and documented non-exposure, frozen before prose inspection. Existing exposed profiles can only serve portability checks if Brian explicitly approves that weaker purpose.',
        limitation='No candidate was substituted by trimming exposed sources; no new semantic outputs inspected or tuned.')


def packet(root,base_dir):
    """Concrete retrospective human review plus demonstrated independent prerequisites."""
    root=Path(root);work=json.loads((root/'work-plan.json').read_text());prior=Path(work['prior_acceptance'])
    old=json.loads((prior/'plan.json').read_text());record=x.core.read_record(old['profile_input']['path']);plan=x.core.build_plan(record)
    reuse=reuse_audit(record,base_dir);holdout=holdout_audit(base_dir,prior)
    findings=json.loads((prior/'source-review-findings-v1.json').read_text())
    # Keep the historical interpretation apart from the blinded statement pages.
    for ref in findings['reviewed_files']:
        if ref!=reference(ref['path']):raise ValueError('Canonical review source changed')
    all_sources=[reference(p) for p in sorted((prior/'source-review-canonical').glob('*.json'))]
    historical=json.loads((prior/'whole-profile/results.json').read_text())
    rows={r['claim_id']:r for r in historical['results']}
    capacity=list((root/'capacity').glob('*/results.json'))
    if len(capacity)!=1:raise ValueError('Exactly one completed capacity check expected')
    for row in json.loads(capacity[0].read_text())['results']:rows[row['claim_id']]=row
    diagnostics=list((root/'judgment-diagnostic').glob('*/results.json'))
    if len(diagnostics)>1:raise ValueError('Multiple diagnostic variants are not permitted')
    if diagnostics:
        for row in json.loads(diagnostics[0].read_text())['results']:rows[row['claim_id']]=row
    # Re-evaluate the complete dependency graph; copying isolated document entries
    # could leave a stale withheld status after an upstream result changes.
    document=x.core.document_input(plan,[rows[i['claim_id']] for i in plan['items']])
    entries={e['claim_id']:e for e in document['entries']}
    x.Store(root).write_immutable('human-review/document-input.json',document)
    (root/'human-review/analysis-support.md').write_text(x.core.render_handoff(document))
    units=[];reviewdir=root/'human-review'
    for item in plan['items']:
        cid=item['claim_id'];case=item['case'];page=dict(claim_id=cid,candidate=dict(statement=item['statement'],scope=item['scope'],declared_caveats=item['declared_caveats']),
            runtime_evidence=x.core.citation_state(case) if case else None,gap=item['gap'],
            decisions=['Accept as supported within supplied scope','Reject: contrary evidence or unsupported assertion','Withhold: missing necessary evidence or qualification','Cannot determine from the provided source'],
            checks=['Does every assertion, including strength, priority or comparison, have a source warrant?','Are speaker, adoption, polarity and conditions retained in statement plus scope and caveats?','Does any missing restriction change the actual assertion, rather than prevent an unmade inference?','Does complete sample context contain consequential omissions or contrary evidence?'],
            reviewer_decision=None,authority='Pending independent human review; not runtime evidence')
        filename='human-review/statements/'+cid+'.json';x.Store(root).write_immutable(filename,page)
        units.append(dict(claim_id=cid,packet=reference(root/filename)))
    review=dict(version=VERSION,profile=plan['profile'],profile_input=old['profile_input'],implementation=readiness.code_identity(),
        status='RETROSPECTIVE_HUMAN_REVIEW_PREPARED_HOLDOUT_BLOCKED',independent_review_completed=False,
        document_input=reference(root/'human-review/document-input.json'),assembled_document=reference(root/'human-review/analysis-support.md'),statements=units,complete_sample_sources=all_sources,canonical_source_count=findings['canonical_units'],
        document_checks=['Check the complete assembled document for balance across the three recordings, rather than counting supported statements.','Check all canonical blocks, including four excluded from measurements, for consequential omissions and contrary evidence.','Treat missing public-life, interpretive-source, pastoral-address and repentance/growth distinctions as unknown.','Check declared denominators, sample limits, traceability and dependency withholding; no ministry-wide extrapolation.'],
        proposed_decision='Approve this concrete retrospective review packet; reserve any whole-profile accuracy claim until independent review and an uncontaminated holdout are available.',
        review_method='Review blinded statement pages and complete sample first; inspect model recommendations and earlier assistant findings only afterwards. Decisions are human authored and never request inputs.',
        holdout=holdout,runtime_references=False,production_admission='not_admitted')
    frozen=dict(review=review,reuse_audit=reuse,source_review_findings_reference=reference(prior/'source-review-findings-v1.json'),model_recommendations=[entries[i['claim_id']] for i in plan['items']])
    frozen['packet_fingerprint']=x.digest(frozen)
    x.Store(root).write_immutable('human-review/packet.json',frozen)
    lines=['# Whole-profile review readiness','', 'Retrospective human review is prepared. Whole-profile accuracy is not established. An untouched independent profile is unavailable in the inspected compatible materialized evidence.','',f"Profile {plan['profile']['id']}: {len(units)} statements, {findings['canonical_units']} canonical source blocks across three recordings.",'','## Review in this order','', '1. Review each statement page against its linked complete passages and scope. Select one of the four supplied decisions; no new profile wording or reference answers are required.','2. Read all canonical source parts for omitted dimensions and contrary evidence.','3. Assess the complete document for proportion, denominators, uncertainty and dependency handling.','4. Consult model recommendations and earlier assistant findings only after recording independent decisions.','','## Prepared statements','']
    lines += [f"- [{u['claim_id']}]({u['packet']['path']})" for u in units]
    lines += ['','## Complete canonical source text','']+[f"- [Source part]({ref['path']})" for ref in findings['reviewed_files']]
    lines += ['','## Independent holdout prerequisite','',holdout['smallest_remedy'],'','## Evidence gaps','',f"{reuse['exact_identities']} exact registered constituent identities checked; {reuse['compatible_answers']} compatible answers found. Existing reviewed bindings remain local proposals, not automatic comprehensive coverage.",'']
    for key,v in reuse['missing_producer_contracts'].items():lines += [f"- **{key}**: {v['missing']}. Producer: {v['owner']}. Existing contract: {v['existing']}."]
    lines += ['','This packet is evaluation only. It does not authorize classification, collection, admission, or another experiment.','']
    (root/'human-review/review.md').write_text('\n'.join(lines))
    x.Store(root).write_immutable('evidence-reuse-audit.json',reuse);x.Store(root).write_immutable('holdout-audit.json',holdout)
    return dict(status=review['status'],packet=str(root/'human-review/packet.json'),review=str(root/'human-review/review.md'),packet_fingerprint=frozen['packet_fingerprint'],statements=len(units),generation_calls=0)
