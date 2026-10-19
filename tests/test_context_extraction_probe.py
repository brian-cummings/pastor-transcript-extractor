from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from pastor_transcript_extractor import context_extraction_validation as v
from pastor_transcript_extractor import context_extraction_probe as p


def context(text='If you ask, come in. “Read it.”'):
    return p.seals.seal(dict(start=10,end=10+len(text),text=text,has_earlier_source=True,has_later_source=True,source_snapshot_sha256='synthetic'))

def output(c):
    s=dict(start=0,end=19,text=c['text'][:19])
    return dict(context_fingerprint=c['content_fingerprint'],nominations=[dict(capability='G3',roles=dict(left=None,right=None,utterance=s),dependency_spans=[dict(start=0,end=10,text=c['text'][:10])],provenance_hypotheses=[dict(dimension='voice',value='unknown',support=None)],context_status='uncertain')],status='proposed')


class LiteralTests(unittest.TestCase):
    def test_unicode_offsets_and_no_evidence_authority(self):
        c=context();result=v.validate_output(json.dumps(output(c),ensure_ascii=False),c,'G3')
        n=result['nominations'][0]
        self.assertEqual(10,n['roles']['utterance']['start']);self.assertFalse(n['usable_evidence']);self.assertNotIn('positive_facts',n)
        c=context('é🙂 é🙂');o=output(context());o['context_fingerprint']=c['content_fingerprint'];n=o['nominations'][0];n['roles']['utterance']=dict(start=3,end=5,text='é🙂');n['dependency_spans']=[]
        self.assertEqual(13,v.validate_output(o,c,'G3')['nominations'][0]['roles']['utterance']['start'])

    def test_corrupt_bounds_text_foreign_context_and_bool_offsets_rejected(self):
        c=context()
        for changes in (dict(start=True),dict(start=-1),dict(end=999),dict(text='paraphrase')):
            o=output(c);o['nominations'][0]['roles']['utterance'].update(changes)
            with self.assertRaises(ValueError):v.validate_output(o,c,'G3')
        o=output(c);o['context_fingerprint']='foreign'
        with self.assertRaisesRegex(ValueError,'Foreign'):v.validate_output(o,c,'G3')

    def test_missing_qualifier_declaration_outside_target_and_provenance_reject(self):
        c=context();o=output(c);o['nominations'][0]['roles']['utterance']=dict(start=12,end=19,text=c['text'][12:19])
        with self.assertRaisesRegex(ValueError,'dependency'):v.validate_output(o,c,'G3')
        o=output(c);o['nominations'][0]['provenance_hypotheses'][0]['value']='preacher'
        with self.assertRaisesRegex(ValueError,'Unsupported'):v.validate_output(o,c,'G3')

    def test_roles_family_cardinality_and_unknown_fields(self):
        c=context();o=output(c)
        with self.assertRaisesRegex(ValueError,'family'):v.validate_output(o,c,'G2')
        for field in ('pastor_credit','positive_facts','accepted_review_authority'):
            o=output(c);o['nominations'][0][field]=True
            with self.assertRaisesRegex(ValueError,'fields'):v.validate_output(o,c,'G3')
        o=output(c);o['nominations']*=5
        with self.assertRaisesRegex(ValueError,'limit'):v.validate_output(o,c,'G3')

    def test_G2_overlap_and_direction(self):
        c=context('A text. An explanation.');o=output(context());o['context_fingerprint']=c['content_fingerprint'];n=o['nominations'][0];n.update(capability='G2',dependency_spans=[],provenance_hypotheses=[])
        n['roles']=dict(left=dict(start=0,end=7,text=c['text'][:7]),right=dict(start=8,end=len(c['text']),text=c['text'][8:]),utterance=None)
        self.assertEqual(10,v.validate_output(o,c,'G2')['nominations'][0]['roles']['left']['start'])
        n['roles']['right']=n['roles']['left']
        with self.assertRaisesRegex(ValueError,'Overlapping'):v.validate_output(o,c,'G2')

    def test_no_duplicate_keys_nonfinite_or_fuzzy_quote_repair(self):
        for text in ('{"a":1,"a":2}','{"a":NaN}'):
            with self.assertRaises(ValueError):v.strict_json(text)
        c=context('same same');o=output(context());o['context_fingerprint']=c['content_fingerprint'];n=o['nominations'][0];n['roles']['utterance']=dict(start=5,end=9,text='same');n['dependency_spans']=[]
        self.assertEqual(15,v.validate_output(o,c,'G3')['nominations'][0]['roles']['utterance']['start'])
        n['roles']['utterance']['start']=4
        with self.assertRaises(ValueError):v.validate_output(o,c,'G3')


class WorkflowTests(unittest.TestCase):
    def test_immutable_roundtrip_and_conflicting_writes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'receipt.json';a=p.save(path,dict(counts={2:1,10:2}));p.save(path,a)
            self.assertEqual(a,p.design.old.sealed(path))
            with self.assertRaisesRegex(ValueError,'differs'):p.save(path,dict(counts={2:9}))

    def test_authorization_precedes_credentials_and_network(self):
        with tempfile.TemporaryDirectory() as d,patch.object(p,'EXECUTION',Path(d)/'absent'),patch.object(p,'verify',return_value=(dict(content_fingerprint='held'),{})),patch.object(p,'transport',side_effect=AssertionError('No network')):
            with self.assertRaisesRegex(ValueError,'absent'):p.run(approve_input='held')

    def test_request_has_no_oracle_and_token_limit_fail_closed(self):
        c=context();r=p.request(c,'G3');state=json.loads(r['messages'][1]['content'])
        self.assertEqual({'context_fingerprint','task_family','source_context','word_offsets'},set(state))
        self.assertEqual(2048,r['max_completion_tokens']);self.assertEqual(p.MODEL,r['model']);self.assertFalse(r['store']);self.assertNotIn('tools',r)
        class TooLarge:
            def encode(self,*args,**kwargs):return list(range(16385))
        with self.assertRaisesRegex(ValueError,'reservation'):p.token_account(r,TooLarge())

    def test_cli_held_and_old_modes_delegate(self):
        from typer.testing import CliRunner
        from pastor_transcript_extractor.cli import app
        from pastor_transcript_extractor.commands.analysis import context_design
        with patch.object(context_design,'collector_retrieval_design') as old:
            result=CliRunner().invoke(app,['analysis','collector-retrieval-design','--context-extraction-proposal','--check-only'])
            self.assertEqual(0,result.exit_code,result.output);old.assert_called_once_with(True,True)
        with tempfile.TemporaryDirectory() as d,patch.object(p,'EXECUTION',Path(d)/'absent'),patch.object(p,'verify',return_value=(dict(content_fingerprint='held'),{})),patch.object(p,'transport',side_effect=AssertionError('No network')):
            result=CliRunner().invoke(app,['analysis','collector-retrieval-design','--context-extraction-probe','--run','--approve-input','held'])
            self.assertNotEqual(0,result.exit_code);self.assertIn('absent',result.output)

class ExecutionTests(unittest.TestCase):
    """Synthetic transport only; these tests never contact any provider."""
    def setup_run(self,d):
        c=context();body=p.request(c,'G3')
        class Encoding:
            def encode(self,*args,**kwargs):return [0]*100
        encoding=Encoding();request=p.seals.seal(dict(case_id='synthetic',body=body,token_account=p.token_account(body,encoding)))
        packet=dict(content_fingerprint='synthetic-input',requests=[request]);panel=dict(cases=[dict(context=c,family='G3')])
        authority=dict(content_fingerprint='synthetic-authority')
        raw=dict(status_code=200,body=json.dumps(dict(model=p.MODEL,usage=dict(prompt_tokens=100,completion_tokens=100,total_tokens=200),choices=[dict(finish_reason='stop',message=dict(content=json.dumps(output(c))))])),provider_request_id='synthetic')
        return packet,panel,authority,encoding,raw

    def test_sealed_receipt_reused_without_repeat_and_no_usable_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            packet,panel,authority,encoding,raw=self.setup_run(d)
            with patch.object(p,'verify',return_value=(packet,panel)),patch.object(p,'require_execution',return_value=authority),patch.object(p,'directory',return_value=Path(d)),patch.object(p,'tokenizer',return_value=encoding),patch.dict('os.environ',{'OPENAI_API_KEY':'SYNTHETIC-NOT-A-KEY'}),patch.object(p,'transport',return_value=raw) as fake:
                result=p.run();self.assertIsNone(result['nomination_feasibility_verdict']);self.assertEqual(1,result['attempted_requests'])
                self.assertEqual(result,p.run());fake.assert_called_once()
                receipt=p.design.old.sealed(Path(d)/'synthetic-input/synthetic.receipt.json')
                self.assertFalse(receipt['usable_evidence']);self.assertFalse(receipt['validation']['usable_evidence'])

    def test_uncertain_attempt_is_never_retried(self):
        with tempfile.TemporaryDirectory() as d:
            packet,panel,authority,encoding,raw=self.setup_run(d)
            with patch.object(p,'verify',return_value=(packet,panel)),patch.object(p,'require_execution',return_value=authority),patch.object(p,'directory',return_value=Path(d)),patch.object(p,'tokenizer',return_value=encoding),patch.dict('os.environ',{'OPENAI_API_KEY':'SYNTHETIC-NOT-A-KEY'}),patch.object(p,'transport',side_effect=TimeoutError('synthetic')) as fake:
                with self.assertRaisesRegex(ValueError,'no automatic retry'):p.run()
                with self.assertRaisesRegex(ValueError,'uncertain spend'):p.run()
                fake.assert_called_once()

    def test_budget_snapshot_and_http_failures_stop(self):
        for mutate in ('model','usage','http'):
            with self.subTest(mutate=mutate),tempfile.TemporaryDirectory() as d:
                packet,panel,authority,encoding,raw=self.setup_run(d)
                parsed=json.loads(raw['body'])
                if mutate=='model':parsed['model']='wrong-snapshot'
                if mutate=='usage':parsed['usage']['prompt_tokens']=16385
                if mutate=='http':raw['status_code']=429
                raw['body']=json.dumps(parsed)
                with patch.object(p,'verify',return_value=(packet,panel)),patch.object(p,'require_execution',return_value=authority),patch.object(p,'directory',return_value=Path(d)),patch.object(p,'tokenizer',return_value=encoding),patch.dict('os.environ',{'OPENAI_API_KEY':'SYNTHETIC-NOT-A-KEY'}),patch.object(p,'transport',return_value=raw) as fake:
                    result=p.run();self.assertEqual('HOLD_TECHNICAL',result['status']);fake.assert_called_once()

    def test_literal_failure_preserves_raw_without_repair(self):
        with tempfile.TemporaryDirectory() as d:
            packet,panel,authority,encoding,raw=self.setup_run(d);parsed=json.loads(raw['body']);parsed['choices'][0]['message']['content']='{"bad":"shape"}';raw['body']=json.dumps(parsed)
            with patch.object(p,'verify',return_value=(packet,panel)),patch.object(p,'require_execution',return_value=authority),patch.object(p,'directory',return_value=Path(d)),patch.object(p,'tokenizer',return_value=encoding),patch.dict('os.environ',{'OPENAI_API_KEY':'SYNTHETIC-NOT-A-KEY'}),patch.object(p,'transport',return_value=raw):
                p.run();receipt=p.design.old.sealed(Path(d)/'synthetic-input/synthetic.receipt.json')
                self.assertEqual(raw,receipt['raw_response']);self.assertIsNone(receipt['validation']);self.assertIsNotNone(receipt['failure'])

    def test_execution_authority_requires_exact_input_scope_and_owner(self):
        with tempfile.TemporaryDirectory() as d,patch.object(p,'EXECUTION',Path(d)/'decision.json'):
            packet=dict(content_fingerprint='exact',limits={})
            authority=dict(status='AUTHORIZED',decision_owner='Brian',input_fingerprint='exact',attempts=24,model=p.MODEL,limits={},extractor_execution=True,Jev=False,measurement_admission=False,fresh_sources=False,collection_projection=False,automatic_retries=False)
            p.save(p.EXECUTION,authority);self.assertEqual('Brian',p.require_execution(packet,'exact')['decision_owner'])
            with self.assertRaisesRegex(ValueError,'fingerprint'):p.require_execution(packet,'other')
            authority['model']='other';p.save(p.EXECUTION,authority,replace=True)
            with self.assertRaisesRegex(ValueError,'scope'):p.require_execution(packet,'exact')

    def test_source_oracle_completeness_checked_without_model(self):
        spec=p.design.old.sealed(p.HERE/'source-panel-spec-v1.json')
        from pastor_transcript_extractor import collector_retrieval_workflow_v1_1 as retired
        experiment=p.design.verify()[1];sources=retired.sources(retired.verify())
        p.validate_spec(spec,experiment,sources)
        broken=deepcopy(spec);broken['cases'][0]['bounds'][0]=8700
        with self.assertRaisesRegex(ValueError,'required source'):p.validate_spec(broken,experiment,sources)
        broken=deepcopy(spec);broken['cases'][0]['route']='G3_current'
        with self.assertRaisesRegex(ValueError,'identity'):p.validate_spec(broken,experiment,sources)
