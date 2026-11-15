"""Shared fixtures for bound-claim tests: blocks, claims and a fake streaming DeepInfra transport."""
import json

from pastor_transcript_extractor.evidence_requests import WireResponse

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
