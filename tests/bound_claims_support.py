"""Shared fixtures for bound-claim tests: blocks, claims and a fake streaming DeepInfra transport."""
from pathlib import Path
import json
import tempfile

from pastor_transcript_extractor.evidence_requests import WireResponse
from pastor_transcript_extractor.bound_claims import extract, review, verify
from pastor_transcript_extractor.bound_claims.common import write_json
from pastor_transcript_extractor.bound_claims.ledger import PilotLedger

def METADATA(model):
    flash = 'Flash' in model
    return dict(model=model, deployment_version='v', input_cents_per_token='0.00002' if flash else '0.00013',
                output_cents_per_token='0.00006' if flash else '0.00026')


CLEAN = lambda: dict(commit='c', src_tree='t', dirty=False)
DIRTY = lambda: dict(commit='c', src_tree='t', dirty=True)


def block(index, text=None):
    text = text or f'We are saved by grace alone {index}. Vote for the levy.'
    return dict(coordinate=f'v1b{index}', stratum='salvation_strong', video_id=1, profile_id=1, block_id=index, title='T',
                start_seconds=index * 20.0, end_seconds=index * 20.0 + 19.0, watch_url='https://youtu.be/1?t=0', text=text,
                preceding_text='Earlier words.', following_text='Later words.', signals={})


def claim(anchor, **changes):
    value = dict(area='salvation', object='grace', proposition='Salvation is by grace.', polarity='affirm', voiced_by='preacher',
                 preacher_adoption='adopts', speech_role='asserted', conditions=[], qualifications=[], reasons=[],
                 anchor_text=anchor, anchor_offsets=dict(start=0, end=len(anchor)))
    value.update(changes)
    return value


def stream_transport(outputs, calls=None):
    """Mimics the real streaming transport's callbacks, journals and final record."""
    def send(spec, *, before_attempt=None, after_attempt=None, maximum_attempts=1):
        coordinate = spec.source_identity['coordinate']
        if calls is not None:
            calls.append(coordinate)
        output = outputs[coordinate]
        if isinstance(output, Exception):
            raise output
        before_attempt(1)
        usage = dict(prompt_tokens=3000, completion_tokens=1500)
        raw = dict(model=spec.body['model'], service_tier='standard', usage=usage,
                   choices=[dict(index=0, finish_reason='stop', message=dict(role='assistant', content=output, reasoning_content='', refusal=None, tool_calls=[]))])
        record = dict(cancelled=False, outcome='complete', error=None, usage=usage, usage_final=True, usage_available=True)
        wire_response = WireResponse(200, json.dumps(raw, sort_keys=True, separators=(',', ':')))
        record.update(attempt=1, connection_closed=True)
        after_attempt(1, wire_response, record)
        raw['_pte_transport'] = dict(version='deepinfra-qwen-stream-v1', attempts=[record], total_elapsed_seconds=1.0, retry_outcome='not_needed')
        return WireResponse(200, json.dumps(raw, sort_keys=True, separators=(',', ':')))
    send.supports_stream_callbacks = True
    return send


STRATA_ROWS = [dict(stratum=name, requested=n, eligible=n, selected=n, shortfall=0)
               for name, n in (('salvation_strong', 8), ('absent_control', 2))]


class PilotBuilder:
    """Mixin: builds real extraction, verification and decision artifacts with fake transports."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / 'pilot'
        self.addCleanup(self.directory.cleanup)
        self.ledger = PilotLedger(self.root / 'ledger.json')

    def build(self, pro_blocks, flash_blocks, *, public_at=0, control_claims=(), accept=None, jev_by_label=(0.97, 0.5), tokens=None):
        """Eight strong blocks (0-7) and two absent-control blocks (8, 9)."""
        blocks = [dict(block(i), stratum='salvation_strong' if i < 8 else 'absent_control', profile_id=1, video_id=1 if i < 4 else 2)
                  for i in range(10)]
        write_json(self.root / 'strata.json', dict(slice_sha256='s' * 64, seed='s' * 64, strata=STRATA_ROWS, blocks=blocks))
        write_json(self.root / 'slice.json', dict(profiles=[dict(profile_id=1, display_label='Pastor Sample')], sermons=[
            dict(profile_id=1, video_id=1, title='First Sermon, Pastor Sample', url='https://youtu.be/1'),
            dict(profile_id=1, video_id=2, title='Second Sermon, Pastor Sample', url='https://youtu.be/2')]))

        def outputs(indexes, extra=()):
            result = {f'v1b{i}': '{"claims":[]}' for i in range(10)}
            for i in set(indexes) | set(extra):
                kind = dict(area='public_life', polarity='prescribe') if i == public_at else {}
                result[f'v1b{i}'] = json.dumps(dict(claims=[claim(f'We are saved by grace alone {i}.', **kind)]))
            return result
        for producer, indexes, extra in (('pro', pro_blocks, control_claims), ('flash', flash_blocks, ())):
            extract.run(self.root / 'strata.json', producer, self.ledger, transport=stream_transport(outputs(indexes, extra)), state=CLEAN, metadata=METADATA)
        queue = review._queue(self.root) if (self.root / 'review.json').exists() else (review.write_queue(self.root), review._queue(self.root))[1]
        labels = {}
        for item in queue['items']:
            labels[item['id']] = 'accept' if (accept is None or item['coordinate'] in accept) else 'reject:proposition'
        write_json(self.root / 'labels.json', labels)
        review.replay(self.root, self.root / 'labels.json')
        high, low = jev_by_label

        def send(spec):
            probability = high if labels[spec.source_identity['fingerprint']] == 'accept' else low
            body = spec.body
            used = tokens(body) if tokens else 1000
            answers = {key: dict(type='noul', noul=probability) for key in body['questions']}
            return WireResponse(200, json.dumps(dict(model='jev-1.13.0', usage=dict(input_tokens=used, output_tokens=0), answers=answers)))
        verify.run([self.root / 'extract' / p / 'extraction.json' for p in ('pro', 'flash')], self.ledger, transport=send, state=CLEAN, metadata=METADATA)
        return labels

    def section(self, videos=(1, 2)):
        write_json(self.root / 'SECTION_1.json', dict(profile_id=1, findings=[
            dict(video_id=v, watch_url=f'https://youtu.be/x?t={v}') for v in videos]))

