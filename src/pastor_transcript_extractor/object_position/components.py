"""The seven pre-registered components of the preacher's position on "the American experiment" (spec section 3a).

Frozen before any output exists. Spans are literal source phrases for the reviewer and for the located-once check; the
model never sees them. Whitespace in a span matches any run of whitespace in the transcript.
"""
from __future__ import annotations

import re

COMPONENTS = (
    dict(id=1, label='It works as an experiment in self-government; must carry component 4 as its qualification',
         spans=('is working brilliantly', 'an experiment in self-government')),
    dict(id=2, label='It was a cultural and political experiment, not a religious one',
         spans=('It was a cultural experiment, a political experiment',)),
    dict(id=3, label='Government of the people has the people doing what they want and electing who they want',
         spans=('has the people doing what they want as they want, electing who they want',)),
    dict(id=4, label='From a religious point of view it is a massive failure',
         spans=("from a religious point of view, it's a massive failure",)),
    dict(id=5, label='It is failing to live up to its original promise',
         spans=("it's failing to live up to its original promise",)),
    dict(id=6, label='The cause is the sinful human heart, not a party or a policy',
         spans=('but because of the sinful human heart',)),
    dict(id=7, label='There is a solution for that predicament (the sinful human heart)',
         spans=('a solution for that predicament',)),
)


def locate(text: str, span: str) -> list[tuple[int, int]]:
    pattern = r'\s+'.join(re.escape(word) for word in span.split())
    return [(match.start(), match.end()) for match in re.finditer(pattern, text)]


def located(text: str) -> dict[int, list[list[tuple[int, int]]]]:
    return {component['id']: [locate(text, span) for span in component['spans']] for component in COMPONENTS}
