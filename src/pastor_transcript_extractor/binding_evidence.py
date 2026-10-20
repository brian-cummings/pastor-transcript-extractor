"""Literal evidence checks shared by reviewed bindings; no semantic inference."""
import hashlib
import json


def text_digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def context_digest(texts):
    return text_digest(json.dumps(texts, sort_keys=True, ensure_ascii=False))


def validate_span(span, texts):
    field = span.get('source_field')
    if field not in ('target_text', 'leading_context', 'trailing_context'):
        raise ValueError('Unknown evidence source field')
    start, end = span.get('start'), span.get('end')
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(texts[field]):
        raise ValueError('Evidence coordinates outside the supplied source')
    if texts[field][start:end] != span.get('text'):
        raise ValueError('Authored evidence no longer matches the literal source')


def target_span(span, texts):
    validate_span(span, texts)
    if span['source_field'] != 'target_text':
        raise ValueError('A target claim or semantic link cannot be supplied by context')
