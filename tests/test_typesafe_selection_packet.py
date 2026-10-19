import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner
from pastor_transcript_extractor import typesafe_selection_packet as p
from pastor_transcript_extractor import typesafe_selection_execution as e
from pastor_transcript_extractor import typesafe_window_bridge as b
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from tests.test_typesafe_window_bridge import mapped_fixture, answers


class SelectionPacketTests(unittest.TestCase):
    def test_wire_cannot_change_model_or_leak_diagnostic_metadata(self):
        _, _, anchor, context = mapped_fixture()
        request = b.prepare_selection(context, anchor, ['G3'])
        self.assertEqual({'model', 'state', 'questions'}, set(p.wire(request)))
        with self.assertRaises(ValueError):
            p.wire(seal({**request, 'model': 'jev-latest'}))
        changed = deepcopy(request); changed['state']['extra'] = 'bad'
        with self.assertRaises(ValueError): p.wire(changed)

    def test_refinement_envelope_covers_all_page_lengths(self):
        from tests.test_minute_evidence_implementation import fixture
        _, _, _, anchor, context = fixture(['x'*1000])
        first = b.prepare_selection(context, anchor, ['G2', 'G3'])
        maximum = p.refinement_envelope(first)
        for page in first['state']['boundary_pages']:
            refined, _ = b.refine(first, answers(first, {k: page['id'] for k in first['questions']}))
            self.assertLessEqual(p.wire_bytes(p.wire(refined)), maximum)

    def test_no_execution_authority_from_fingerprint_alone(self):
        packet = seal(dict(bounds={'provider_requests_max': 30}))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'decision.json'
            e.write_once(path, dict(status='NOT_AUTHORIZED', input_fingerprint=packet['content_fingerprint'],
                scope='one_nomination_only_attempt', bounds=packet['bounds']))
            with self.assertRaisesRegex(ValueError, 'unauthorized'):
                p.require_authorization(packet, packet['content_fingerprint'], path)
            with self.assertRaisesRegex(ValueError, 'fingerprint'):
                p.require_authorization(packet, 'wrong', path)

    def test_response_model_usage_and_distribution_fail_closed(self):
        _, _, anchor, context = mapped_fixture(); request = b.prepare_selection(context, anchor, ['G3'])
        raw = dict(model=p.MODEL, usage=dict(input_tokens=20, output_tokens=5),
            answers={k: dict(type='choice', **v) for k,v in answers(request).items()})
        def check(value): return e.checked_response(dict(status=200, body_utf8=json.dumps(value)), request['questions'])
        self.assertEqual(raw, check(raw))
        for field, value in [('model', 'jev-latest'), ('usage', {'input_tokens': True, 'output_tokens': 1}),
                ('usage', {'input_tokens': p.TOKENS_PER_REQUEST+1, 'output_tokens': 1}), ('answers', {})]:
            with self.assertRaises((ValueError, KeyError)): check({**raw, field:value})
        with self.assertRaises(ValueError):
            e.checked_response(dict(status=429, body_utf8='{}'), request['questions'])

    def harness(self, tmp, transport):
        source, proof, anchor, context = mapped_fixture()
        request = b.prepare_selection(context, anchor, ['G3'])
        packet = seal(dict(requests=[dict(request=request, first_dispatch=b.dispatch_plan(request,{}), diagnostic_slots=['synthetic'])],
            endpoint='https://example.invalid', structural_deferrals=[], bounds=dict(provider_requests_max=1,
                run_seconds_max=1800, request_timeout_seconds=45, reserved_total_input_tokens=p.TOKENS_PER_REQUEST)))
        selected = dict(contexts={context['content_fingerprint']:context}, cases=[dict(context_fingerprint=context['content_fingerprint'],
            anchor=anchor, preparation_binding=dict(source_proof=proof))])
        patches = [patch.object(p,'verify',return_value=(packet,Path(tmp)/'input.json')),
            patch.object(p,'require_authorization',return_value={'content_fingerprint':'synthetic-authority'}),
            patch.object(e.review,'selected_windows',return_value=(selected,None)),
            patch.object(e,'build_paths',return_value=SimpleNamespace(evaluation=Path(tmp)))]
        for item in patches: item.start(); self.addCleanup(item.stop)
        return packet, request

    def test_one_send_retains_raw_response_and_no_measurements_then_blocks_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet, request = self.harness(tmp, None)
            response = dict(status=200,body_utf8=json.dumps(dict(model=p.MODEL, usage=dict(input_tokens=11, output_tokens=2),
                answers={k: dict(type='choice', **v) for k,v in answers(request).items()})))
            sends=[]
            def transport(*args): sends.append(args); return response
            result, path = e.execute(packet['content_fingerprint'], transport=transport)
            self.assertEqual(1,len(sends));self.assertEqual(1,result['provider_requests'])
            self.assertEqual(0,result['measurement_requests']);self.assertFalse(result['usable_evidence'])
            self.assertEqual(response, json.loads((path.parent/'01-response.json').read_text())['raw'])
            with self.assertRaises(FileExistsError): e.execute(packet['content_fingerprint'],transport=transport)
            self.assertEqual(1,len(sends))

    def test_uncertain_send_keeps_reservation_stops_and_cannot_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet, _ = self.harness(tmp,None)
            sends=[]
            def transport(*args): sends.append(args); raise TimeoutError('synthetic')
            with self.assertRaises(TimeoutError): e.execute(packet['content_fingerprint'],transport=transport)
            out=Path(tmp)/p.VERSION/packet['content_fingerprint']/'attempt-1'
            self.assertTrue((out/'01-reservation.json').exists());self.assertTrue((out/'stopped-v1.json').exists())
            with self.assertRaises(FileExistsError): e.execute(packet['content_fingerprint'],transport=transport)
            self.assertEqual(1,len(sends))

    def test_full_exact_cache_does_not_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet, request = self.harness(tmp,None)
            cache={}
            for key,answer in answers(request).items():
                leaf=b.cached_leaf(request,key,answer,{'receipt':'synthetic'});cache[leaf['leaf_key']]=leaf
            packet['requests'][0]['first_dispatch']=b.dispatch_plan(request,cache)
            packet=seal(packet)
            with patch.object(p,'verify',return_value=(packet,None)):
                result,_=e.execute(packet['content_fingerprint'],transport=lambda *args: self.fail('No needless TypeSafe call'))
            self.assertEqual(0,result['provider_requests'])

    def test_cli_preparation_does_not_execute_and_rejects_ambiguous_modes(self):
        from pastor_transcript_extractor.cli import app
        result=seal(dict(status='PREPARED_EXECUTION_UNAUTHORIZED',provider_requests=0))
        with patch.object(p,'prepare',return_value=(result,Path('/tmp/synthetic'))), patch.object(e,'execute',side_effect=AssertionError('No inference')):
            response=CliRunner().invoke(app,['analysis','structure-readiness','--typesafe-selection','--json'])
            self.assertEqual(0,response.exit_code,response.output)
        for args in (['--run-selection','--check-only'],['--approve-input','wrong']):
            response=CliRunner().invoke(app,['analysis','structure-readiness','--typesafe-selection',*args])
            self.assertEqual(2,response.exit_code)
