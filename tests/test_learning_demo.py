"""Synthetic model boundary fixtures; no real pastor fingerprints or warrants."""
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from pastor_transcript_extractor import learning_demo as demo
from pastor_transcript_extractor import learning_demo_contracts as c
from pastor_transcript_extractor.pastor_evidence import SourceWindow, SampleSpec, digest
from pastor_transcript_extractor.evidence_requests import ReceiptStore
from test_theological_binding import fixture


class SyntheticEncoding:
    """Fixed stub tokenizer only for transport-free orchestration fixtures."""
    def encode(self,text,**kwargs): return [0]*(len(text)//4)


def synthetic_packet():
    windows=[];requests=[];sources=[];samples=[]
    for p in range(2):
        videos=tuple(10000+p*3+i for i in range(3))
        samples.append(asdict(SampleSpec(900+p,videos,'synthetic-membership')))
        for vid in videos:
            sources.append(dict(video_id=vid))
            for slot in range(4):
                window=SourceWindow(f'synthetic-{vid}-{slot}',900+p,vid,'synthetic-source',slot,
                    (dict(block_id=slot,start_seconds=slot*60,end_seconds=(slot+1)*60,
                        segment_indexes=[slot],target_text='God creates the world. People respond with trust.'),),
                    'independent_control' if slot==3 else 'detector_selected')
                texts,mapping=window.target()
                request=c.generation_request('source_reading',dict(texts=texts,block_mapping=mapping),{'window':window.id})
                windows.append(asdict(window));requests.append(dict(case_id=window.id,request=asdict(request)))
    return dict(input_fingerprint='synthetic-only',windows=windows,samples=samples,
                source_refs=sources,source_requests=requests,measurements=[])


class FakeProvider:
    def __init__(self): self.calls=[]
    def __call__(self,request):
        self.calls.append(request)
        phase=request.phase
        if request.body['model']=='jev-1.13.0':
            output={key:dict(type='noul',noul=.95) for key in request.body['questions']}
        else:
            state=json.loads(request.body['messages'][1]['content'])
            if phase=='source_reading':
                text=state['texts']['target_text'];rows=[]
                for i,phrase in enumerate(['God creates the world.','People respond with trust.']):
                    _,row,_=fixture(text)
                    start=text.index(phrase)
                    span=dict(source_field='target_text',start=start,end=start+len(phrase),text=phrase)
                    row['binding_id']=str(i);row['proposition'].update(span=span,reading=phrase)
                    row['evidence_nodes'][0]['span']=span
                    rows.append(row)
                def quotations(value):
                    if isinstance(value,list): return [quotations(v) for v in value]
                    if not isinstance(value,dict): return value
                    return {k:quotations(v) for k,v in value.items() if not ('source_field' in value and k in ('start','end'))}
                output=dict(status='proposed',claims=quotations(rows))
            elif phase=='alignment_and_interpretation':
                assignments=[]
                for item in state['items']:
                    meaning=dict(proposition=item['binding']['proposition']['reading'],referents=[],modality='assertion',
                        quantifiers=[],conditions=[],exceptions=[],temporal_scope='unspecified',scope='local')
                    assignments.append(dict(observation_id=item['id'],meaning=meaning,
                        paths=['theology/creation'],resolved=True,evidence=[item['id']]))
                vid=state['sources'][0]['video_id']
                hypothesis=dict(id=f'hyp-{vid}',conclusion='The source connects creation and response.',
                    premise_ids=[state['items'][0]['id'],state['items'][1]['id']],inference_type='synthetic_warrant_fixture',
                    scope_video_ids=[vid],alternatives=['Statements may be adjacent only.'],counterevidence_ids=[],
                    defeaters=['No actual source link.'])
                output=dict(assignments=assignments,hypotheses=[hypothesis],relation_assessments=[])
            else:
                key=next(iter(state['entries']))
                output=dict(clauses=[dict(id='synthetic-clause',text='Synthetic supported clause.',entry_ids=[key],
                    scope_video_ids=state['entries'][key]['scope_video_ids'],role='observation')])
        return dict(model=request.body['model'],usage=dict(input_tokens=100,output_tokens=100),complete=True,output=output)


class IntegrationTests(unittest.TestCase):
    def test_full_automatic_recipe_66_attempts_and_six_omission_views(self):
        packet=synthetic_packet();provider=FakeProvider()
        with TemporaryDirectory() as directory:
            store=ReceiptStore(Path(directory))
            result=demo.execute_pipeline(packet,store,provider,encoding=SyntheticEncoding())
            self.assertEqual(len(provider.calls),66)
            self.assertEqual(result['accounting']['attempts'],66)
            self.assertLess(float(result['accounting']['reserved_usd']),.10)
            self.assertEqual(result['accounting']['local_attempts'],33)
            self.assertEqual(result['accounting']['paid_attempts'],33)
            self.assertEqual(result['accounting']['openai_calls'],0)
            self.assertEqual(result['accounting']['runtime_repairs'],0)
            self.assertEqual(result['raw_observations'][0]['field_judgments'],{})
            self.assertEqual(result['raw_observations'][0]['experimental_eligibility'],'pending_verification')
            self.assertEqual(len(result['omission_views']),6)
            self.assertEqual(len(result['fingerprints']),2)
            self.assertEqual(result['comparisons']['theology']['position_metrics']['agreement'],1)
            self.assertEqual(result['status'],'INCONCLUSIVE')
            self.assertEqual(len(result['hypotheses']['accepted']),6)
            for view in result['omission_views']:
                omitted=view['omitted_video_id']
                for fp in view['fingerprints']:
                    self.assertNotIn(omitted,fp['sample_spec']['video_ids'])
                for hypothesis in view['hypotheses']['accepted']:
                    self.assertNotIn(omitted,hypothesis['scope_video_ids'])
                for narrative in view['narratives']:
                    for clause in narrative['final']['clauses']:
                        self.assertNotIn(omitted,clause['scope_video_ids'])
            again=demo.execute_pipeline(packet,store,provider,encoding=SyntheticEncoding())
            self.assertEqual(result,again)
            self.assertEqual(len(provider.calls),66)

    def test_no_oracle_or_manual_runtime_input(self):
        packet=synthetic_packet()
        packet['oracle']='DO NOT SEND TO MODEL'
        provider=FakeProvider()
        with TemporaryDirectory() as directory:
            demo.execute_pipeline(packet,ReceiptStore(Path(directory)),provider,encoding=SyntheticEncoding())
        self.assertNotIn('DO NOT SEND TO MODEL',json.dumps([r.body for r in provider.calls]))

    def test_controls_ignore_scores_and_order(self):
        ids=[1,2,3,4,5]
        self.assertEqual(demo.independent_control(42,ids),demo.independent_control(42,ids[::-1]))

    def test_strict_schema_overflow_and_foreign_fields(self):
        with self.assertRaises(ValueError): c.validate_shape({'status':'none','claims':[],'manual_fix':True},c.READ_SCHEMA)
        with self.assertRaises(ValueError): c.validate_shape({'clauses':[{}]*13},c.NARRATIVE_SCHEMA)

    def test_verification_bias_uses_references_and_underpower_is_visible(self):
        references=[];matches=[];accepted=[]
        for i in range(10):
            references.append(dict(id=str(i),profile=1,stratum='independent_control' if i<5 else 'detector_selected',
                theological_family='qualified' if i<5 else 'simple',adjudicable=True,
                complexity_tags=['conditional_qualified'] if i<5 else []))
            matches.append(dict(reference_id=str(i),observation_id=str(i),correct=True))
            if i>=3: accepted.append(str(i))
        # Repeated readings/windows cannot enlarge correct-generation denominators.
        matches.append(dict(reference_id='0',observation_id='repeated',correct=True))
        result=demo.verification_bias(references,matches,accepted)
        tag=next(r for r in result['groups'] if r['group_type']=='complexity' and r['group']=='conditional_qualified')
        self.assertEqual(tag['correct_generated'],5)
        self.assertEqual(tag['correct_retention'],.4)
        self.assertTrue(tag['verifier_yield_fail'])
        self.assertTrue(result['gaps'][0]['selective_loss_concern'])
        self.assertIsNotNone(tag['retention_interval'])
        self.assertFalse(demo.verification_bias(references[:1],matches,[])['groups'][0]['powered'])

    def test_outcomes_and_authorization_are_distinct(self):
        self.assertEqual(demo.decide_outcome([],audit_complete=True)['status'],'INCONCLUSIVE')
        self.assertEqual(demo.decide_outcome([dict(component='extraction',passed=False,adequate_evidence=True)])['status'],'FAIL(component)')
        self.assertEqual(demo.decide_outcome([dict(component='extraction',passed=False,adequate_evidence=False)])['status'],'INCONCLUSIVE')
        required=('grounding','semantic_fidelity','discovery','verification_yield','alignment','theological_content',
              'interpretation','narrative','usefulness','sample_dependence','effort','budget','mathematics','verification_bias')
        self.assertEqual(demo.decide_outcome([dict(component=k,passed=True,adequate_evidence=True) for k in required],audit_complete=True)['status'],'PASS')
        for args in [('wrong',True,'.10',True),('exact',False,'.10',True),('exact',True,'2.00',True),('exact',True,'.10',False)]:
            with self.assertRaises(ValueError): demo.require_execution({'input_fingerprint':'exact'},*args)
        self.assertEqual(demo.require_execution({'input_fingerprint':'exact'},'exact',True,'.10',True)['max_attempts'],66)

    def test_literal_neighbor_gaps_not_skipped(self):
        from pastor_transcript_extractor.sermon_topics import resolve_topic_block_context
        from pastor_transcript_extractor.binding_evidence import text_digest,context_digest
        # Tests the actual adjacency boundary without rebuilding transcript geometry.
        analysis=dict(blocks=[dict(block_id=i,start_seconds=i,end_seconds=i+1) for i in range(5)],context_policy_version='fixture')
        case=dict(case_id='c',profile_id=1,video_id=2,source_sha256='s',anchor_block_id=2,
            target_block_ids=[2,3],excluded_immediate_neighbors=[1],stratum='independent_control',blocks=[])
        for i in [2,3]:
            block=analysis['blocks'][i];block.update(segment_indexes=[i],context_identity='fixture')
            case['blocks'].append(dict(block_id=i,start_seconds=i,end_seconds=i+1,
                target_sha256=text_digest(str(i)),context_sha256=context_digest({'target_text':str(i)})))
        with patch('pastor_transcript_extractor.sermon_topics.resolve_topic_block_context',side_effect=lambda b:{'target_text':str(b['block_id'])}):
            window=demo.source_window(case,analysis,{0,2,3,4})
            self.assertEqual([b['block_id'] for b in window.blocks],[2,3])
            bad=dict(case,target_block_ids=[0,2,3])
            with self.assertRaisesRegex(ValueError,'adjacent'): demo.source_window(bad,analysis,{0,2,3,4})

    def test_narrative_identity_aliases_are_reversible_and_preserve_literal_semantics(self):
        from copy import deepcopy
        identity='a'*64
        state=dict(entries={identity:dict(premise_ids=[identity],text=identity,
            conditions=['if trust'],voice='reported',polarity='denied',scope_video_ids=[1])})
        before=deepcopy(state)
        encoded,aliases=demo.alias_model_state(state)
        self.assertEqual(state,before)
        alias=next(iter(encoded['entries']))
        self.assertEqual(aliases[alias],identity)
        self.assertEqual(encoded['entries'][alias]['premise_ids'],[alias])
        self.assertEqual(encoded['entries'][alias]['text'],identity)
        self.assertEqual(encoded['entries'][alias]['conditions'],['if trust'])
        self.assertEqual(encoded['entries'][alias]['voice'],'reported')


class TechnicalRestartTests(unittest.TestCase):
    def test_one_failed_local_attempt_is_preserved_and_counted(self):
        with TemporaryDirectory() as directory:
            base=Path(directory);prior=dict(schema_version='synthetic-prior')
            fingerprint=digest(prior);prior['input_fingerprint']=fingerprint
            root=base/fingerprint;root.mkdir();input_path=root/'input.json'
            input_path.write_text(json.dumps(prior))
            store=ReceiptStore(root/'execution')
            store.write_immutable('attempts/local.json',dict(phase='source_reading',reserved_usd='0'))
            store.write_immutable('stopped-local.json',dict(reason="'prompt_eval_count'"))
            with patch.object(demo,'RESTART_FROM',fingerprint),patch.object(demo,'_run_directory',lambda base,key:Path(base)/key):
                lineage=demo.restart_lineage(input_path,base)
                self.assertEqual(lineage['prior_local_attempts'],1)
                self.assertIn(str(input_path.resolve()),lineage['preserved_files'])
                # The separately claimed restart marker cannot alter the frozen failure snapshot.
                store.write_immutable('restart-authorization.json',dict(restart_input_fingerprint='synthetic-new'))
                self.assertEqual(lineage,demo.restart_lineage(input_path,base))
                current=ReceiptStore(base/'new-execution')
                account=demo.cumulative_account(current,dict(restart=lineage))
                self.assertEqual(account['cumulative_attempts'],1)
                self.assertEqual(account['cumulative_paid_attempts'],0)
                self.assertEqual(account['cumulative_unknown_usage_attempts'],1)
                store.write_immutable('attempts/extra.json',dict(phase='source_reading',reserved_usd='0'))
                with self.assertRaisesRegex(ValueError,'exactly'):demo.restart_lineage(input_path,base)

    def test_exception_does_not_expand_current_run_ledger(self):
        from pastor_transcript_extractor.evidence_requests import BudgetLedger
        with self.assertRaisesRegex(ValueError,'expand'):BudgetLedger(max_attempts=67).check([],'source_reading')
        packet=dict(input_fingerprint='new',budget=dict(maximum_attempts=67,maximum_local_attempts=34))
        decision=demo.require_execution(packet,'new',True,'.10',True)
        self.assertEqual(decision['max_attempts'],67)
        self.assertEqual(decision['max_paid_attempts'],33)
        self.assertEqual(decision['max_usd'],'.10')


class HardenedContractTests(unittest.TestCase):
    def test_enums_reject_joined_choices_and_prose_limits_never_truncate(self):
        from copy import deepcopy
        row=deepcopy(FakeProvider()(c.generation_request('source_reading',
            dict(texts=dict(target_text='God creates the world. People respond with trust.')),{}))['output'])
        c.validate_shape(row,c.READ_SCHEMA)
        row['claims'][0]['voice']['kind']='preacher/quoted_or_reported/unresolved'
        with self.assertRaisesRegex(ValueError,'enum'):c.validate_shape(row,c.READ_SCHEMA)
        row['claims'][0]['voice']['kind']='preacher'
        row['claims'][0]['scope']['reading']='x'*1025
        with self.assertRaisesRegex(ValueError,'length'):c.validate_shape(row,c.READ_SCHEMA)
        self.assertEqual(len(row['claims'][0]['scope']['reading']),1025)
        self.assertEqual(c.validate_shape(dict(source_field='target_text',text='x'*3000),c.SPAN)['text'],'x'*3000)
        with self.assertRaises(ValueError):c.validate_shape(dict(source_field='target_text',text=''),c.SPAN)

    def test_wire_schema_has_no_offsets_and_enforces_existing_meanings(self):
        self.assertEqual(set(c.SPAN['properties']),{'source_field','text'})
        self.assertEqual(set(c.BINDING['properties']['adoption']['properties']['status']['enum']),
                         {'own_assertion','adopted','reported_not_adopted','rejected','undetermined'})
        self.assertEqual(c.READ_SCHEMA['properties']['claims']['maxItems'],12)
        self.assertEqual(c.BINDING['properties']['development_relations']['maxItems'],6)
        self.assertNotIn('preacher/quoted_or_reported',c.READ_PROMPT)


class ContractRoundTests(unittest.TestCase):
    def test_two_preserved_attempts_count_without_expanding_current_run(self):
        packet=synthetic_packet();packet['contract_round']=dict(prior_attempts=2,prior_local_attempts=2,
            prior_paid_attempts=0,prior_reserved_usd='0')
        provider=FakeProvider()
        with TemporaryDirectory() as directory:
            store=ReceiptStore(Path(directory))
            result=demo.execute_pipeline(packet,store,provider,encoding=SyntheticEncoding())
            self.assertEqual(len(provider.calls),66)
            self.assertEqual(result['accounting']['cumulative_attempts'],68)
            self.assertEqual(result['accounting']['cumulative_local_attempts'],35)
            self.assertEqual(result['accounting']['cumulative_paid_attempts'],33)
            self.assertEqual(result['accounting']['cumulative_unknown_usage_attempts'],2)
            self.assertTrue(all(row['producer']['literal_locator']=='unique-verbatim-unicode-v1'
                                for row in result['observations']))
            again=demo.execute_pipeline(packet,store,provider,encoding=SyntheticEncoding())
            self.assertEqual(result,again);self.assertEqual(len(provider.calls),66)

    def test_absent_literal_is_withheld_without_repair_or_verification_as_evidence(self):
        provider=FakeProvider();first=[True];verified=[]
        def send(request):
            response=provider(request)
            if request.phase=='source_reading' and first[0]:
                response['output']['claims'][0]['proposition']['span']['text']='not in synthetic source'
                first[0]=False
            if request.phase=='source_verification':verified.append(request.body['state']['items'])
            return response
        with TemporaryDirectory() as directory:
            result=demo.execute_pipeline(synthetic_packet(),ReceiptStore(Path(directory)),send,encoding=SyntheticEncoding())
            self.assertEqual(len(result['raw_observations']),47)
            self.assertEqual(len(verified[0]),1)
            self.assertEqual(result['raw_readings'][0]['output']['claims'][0]['proposition']['span']['text'],
                             'not in synthetic source')
            self.assertEqual(result['status'],'FAIL(component)')
            self.assertTrue(any(row['component']=='literal_binding' and 'absent' in row['reason']
                                for row in result['failures']))
            self.assertEqual(result['accounting']['runtime_repairs'],0)

    def test_round_cannot_follow_a_different_failed_run(self):
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'preserved incomplete'):
                demo.contract_round_lineage(Path(directory)/'other.json',Path(directory))


class SavedDiagnosticsTests(unittest.TestCase):
    def test_first_failed_binding_is_reported_without_provider_or_admission(self):
        from dataclasses import replace
        from copy import deepcopy
        packet=synthetic_packet();provider=FakeProvider();messages=[]
        packet['contracts']=dict(schemas=c.SCHEMAS)
        for row in packet['source_requests']:
            request=demo.RequestSpec(**row['request']);row['fingerprint']=request.fingerprint
        def send(request):
            response=provider(request)
            if request.phase=='source_reading':
                for claim in response['output']['claims']:
                    claim['proposition']['span']['text']='Absent synthetic quotation'
            return response
        # Stop after one valid receipt; diagnostics must consume only saved results.
        with TemporaryDirectory() as directory:
            store=ReceiptStore(Path(directory));request=demo.RequestSpec(**packet['source_requests'][0]['request'])
            demo.execute(request,demo.BudgetLedger(),store,send)
            before=len(provider.calls)
            report=demo.source_contract_diagnostics(packet,store)
            self.assertEqual(len(provider.calls),before)
            self.assertEqual(report['attempted_windows'],1)
            self.assertEqual(report['schema_valid_responses'],1)
            self.assertEqual(report['proposed_claims'],2)
            self.assertEqual(report['literal_bound_claims'],0)
            self.assertEqual(sum(report['first_binding_error_counts'].values()),2)
            old=deepcopy(packet);old['contracts']['schemas']={}
            self.assertEqual(demo.source_contract_diagnostics(old,store)['status'],'UNAVAILABLE')
