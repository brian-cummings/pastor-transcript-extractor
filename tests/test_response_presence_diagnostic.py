from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pastor_transcript_extractor import response_presence_diagnostic as diagnostic
from pastor_transcript_extractor import response_growth_binding as producer
from pastor_transcript_extractor.pastor_evidence import digest
from test_profile_section import reading


def fixture(root):
    """Tiny authored states/answers test lineage and preparation, not semantics."""
    window, _, _, checked = reading()
    groups = [(diagnostic.BACKGROUND, diagnostic.TARGETS['A1']),
              (diagnostic.ADJACENT, diagnostic.TARGETS['A2']),
              (diagnostic.TARGETS['A3'],), ()]
    tasks = []; rows = []
    def save(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return diagnostic.reference(path)
    for wid, ids in zip(diagnostic.WINDOWS, groups):
        current = replace(window, id=wid)
        tasks.append(dict(id=wid, window=asdict(current)))
        observations = []
        for oid in ids:
            item = deepcopy(checked['observations'][0]); item['id'] = oid
            observations.append(item)
        source = save(root/'sources'/wid/'result.json', dict(observations=observations))
        spec = producer.dimension_verification(current, observations)
        receipt_ref = None; findings = []
        if spec:
            response = dict(model='jev-1.13.0', complete=True,
                usage=dict(input_tokens=100, output_tokens=0),
                output={k: dict(type='noul', noul=.89) for k in spec.body['questions']})
            receipt_ref = save(root/'receipts'/f'{wid}.json', dict(request=asdict(spec),
                halt=None, response=response, response_digest=digest(response)))
            findings = producer.dimension_findings(observations, response, spec)
        old_input = dict(request=asdict(spec) if spec else None)
        old_input['fingerprint'] = digest(old_input)
        inp = save(root/'dimensions'/wid/'input.json', old_input)
        result = save(root/'dimensions'/wid/'result.json', dict(
            input_fingerprint=old_input['fingerprint'], receipt=receipt_ref, findings=findings))
        rows.append(dict(window=wid, artifacts=[source, inp, result], findings=findings))
    plan = dict(tasks=tasks); plan['input_fingerprint'] = digest(plan)
    plan_ref = save(root/'plan.json', plan)
    audit = dict(version='verifier-contract-audit-v1', windows=rows,
        cases=[dict(id=k, observation_id=v) for k, v in diagnostic.TARGETS.items()],
        historical_cli_plans=[plan_ref['path']])
    return Path(save(root/'audit.json', audit)['path'])


class PresenceDiagnosticTests(unittest.TestCase):
    def test_freeze_is_provider_free_idempotent_and_rejects_evidence_mutation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); audit = fixture(root)
            with patch.object(diagnostic.requests, 'typesafe_transport', side_effect=AssertionError('No calls')):
                prepared = diagnostic.prepare(root, audit)
                self.assertEqual(prepared, diagnostic.prepare(root, audit))
                packet = diagnostic.report(prepared['packet'])
            self.assertEqual(3, len(packet['batches']))
            self.assertEqual(5, sum(len(b['expectations']) for b in packet['batches']))
            self.assertEqual(1, len(packet['no_call_controls']))
            self.assertEqual(0, packet['provider_calls'])
            self.assertTrue(Path(prepared['review']).read_text().startswith('# Frozen'))
            self.assertEqual('PREPARED_NOT_AUTHORIZED', packet['status'])
            self.assertLessEqual(Decimal(packet['budget']['worst_case_reserved_usd']), Decimal('.50'))
            old = packet['batches'][0]['evidence'][0]['path']
            Path(old).write_text('{}')
            with self.assertRaisesRegex(ValueError, 'evidence changed'):
                diagnostic.report(prepared['packet'])

    def test_ceiling_and_five_observation_inventory_cannot_expand(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); audit = fixture(root)
            with patch.object(diagnostic.requests, 'request_reservation', return_value=Decimal('.20')):
                with self.assertRaisesRegex(ValueError, 'exceeds'):
                    diagnostic.prepare(root, audit)
            self.assertFalse((root/'evaluation').exists())
            data = json.loads(audit.read_text()); data['cases'].pop(); audit.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'inventory differs'):
                diagnostic.prepare(root, audit)

    def test_packet_edits_do_not_pass_report(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); prepared = diagnostic.prepare(root, fixture(root))
            path = Path(prepared['packet']); packet = json.loads(path.read_text())
            packet['budget']['maximum_physical_attempts'] = 4
            packet['fingerprint'] = digest({k: v for k, v in packet.items() if k != 'fingerprint'})
            path.write_text(json.dumps(packet))
            with self.assertRaisesRegex(ValueError, 'changed'):
                diagnostic.report(path)


if __name__ == '__main__':
    unittest.main()
