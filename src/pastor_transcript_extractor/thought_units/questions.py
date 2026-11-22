"""Boundary question wordings and builders. Q1 and Q2 have candidate wordings for the stage 0 probe; Q3 has one (spec section 4).

Questions quote the passages in their instructions (the TypeSafe structure-recovery cookbook's practice) and carry the existing
caption-handling instruction. Criteria describe concrete situations.
"""
from __future__ import annotations

from typing import Any

CAPTION_HANDLING = 'Ignore repeated or overlapping caption fragments and judge the meaning of the named passages.'
STATE = dict(recording=dict(note='Auto-generated sermon captions; repeated fragments and missing punctuation are caption artifacts.'))

Q1_VARIANTS = {
    'q1a': dict(statement='The second passage picks up mid-sentence from where the first passage stops.'),
    'q1b': dict(statement='The first passage ends without completing its sentence or point, and the second passage completes it.'),
    'q1c': dict(statement='The second passage begins in the middle of a sentence that started in the first passage.'),
}
Q1_CRITERIA = dict(
    true='The first passage stops in the middle of a sentence or clause and the second passage supplies the rest of it.',
    false='The first passage ends with a complete sentence and the second passage starts a new sentence.')
Q2_VARIANTS = {
    'q2a': dict(statement="The second passage begins a new point rather than continuing, illustrating or answering the first passage's point."),
    'q2b': dict(statement='The speaker moves to a different point in the second passage than the one the first passage develops.'),
    'q2c': dict(statement='The second passage starts a new subject or a new step in the argument that the first passage does not develop.'),
}
Q2_CRITERIA = dict(
    true='The second passage opens a point the first passage was not developing: a new claim, a new subject, a new illustration, or a change from explanation to appeal.',
    false='The second passage elaborates, qualifies, explains, gives an example of, or answers the point the first passage was developing.')
Q3_STATEMENT = 'The second passage resumes the point the first passage left unfinished.'
Q3_CRITERIA = dict(
    true='The first passage stops before its point is complete, the text between the passages is a brief aside or interruption, and the second passage takes the point back up.',
    false='The first passage completed or dropped its point, or the second passage starts something new.')


def pair_question(statement: str, criteria: dict[str, str], before: str, after: str, between: str = '') -> dict[str, Any]:
    instructions: dict[str, Any] = dict(statement_to_evaluate=statement, first_passage=before)
    if between:
        instructions['text_between_the_passages'] = between
    instructions.update(second_passage=after, caption_handling=CAPTION_HANDLING)
    return dict(instructions=instructions, criteria=dict(criteria))


def q1(variant: str, before: str, after: str) -> dict[str, Any]:
    return pair_question(Q1_VARIANTS[variant]['statement'], Q1_CRITERIA, before, after)


def q2(variant: str, before: str, after: str) -> dict[str, Any]:
    return pair_question(Q2_VARIANTS[variant]['statement'], Q2_CRITERIA, before, after)


def q3(before: str, between: str, after: str) -> dict[str, Any]:
    return pair_question(Q3_STATEMENT, Q3_CRITERIA, before, after, between)


# ---- Boundary-improvement probe: atomic and graded alternatives to the single Q2 (docs/THOUGHT_UNIT_EXPERIMENT.md section 14) ----

ATOMIC = {
    'b1_transition': dict(
        statement="The second passage opens with a phrase that signals a new step, topic or section, such as 'so', 'now', 'next', 'let's turn to', 'finally' or 'another thing'.",
        true='The second passage begins with such a transition, or announces a new step.',
        false="The second passage begins by continuing the first passage's sentence or point, with no signal of a new step."),
    'b2_new_element': dict(
        statement='The second passage introduces a person, place, event, Scripture passage or idea that the first passage does not mention.',
        true='The second passage brings in a new person, place, event, Scripture reference or idea.',
        false='The second passage talks only about the same people, places and ideas as the first passage.'),
    'b3_kind_of_speech': dict(
        statement='The second passage changes the kind of speech compared with the first passage, for example from explanation to a story, a prayer, an appeal, a joke or an announcement.',
        true='The kind of speech in the second passage differs from the kind in the first.',
        false='Both passages are the same kind of speech.'),
    'b4_closure': dict(
        statement='The first passage has finished making its point.',
        true='The first passage ends with its point stated and complete; nothing is left hanging.',
        false='The first passage stops while its point, list, story or argument is still being developed.'),
    'b5_development': dict(
        statement='The second passage explains, supports, qualifies, gives an example of, or answers what the first passage just said.',
        true="The second passage is developing the first passage's point.",
        false="The second passage is not developing the first passage's point."),
}
SCORE_LEVELS = (
    dict(name='Unrelated', criterion='The second passage starts a different subject or a different kind of talk.'),
    dict(name='New point', criterion='The second passage starts a new point or step, though still in the same broad subject.'),
    dict(name='Related step', criterion="The second passage moves to a related but distinct part of the first passage's point."),
    dict(name='Continuation', criterion="The second passage continues the first passage's point with more detail, an example or a consequence."),
    dict(name='Direct continuation', criterion='The second passage finishes the sentence or the exact thought the first passage was in the middle of.'))
SCORE_TASK = 'Score how the second passage relates to the first passage.'


def atomic(name: str, before: str, after: str) -> dict[str, Any]:
    item = ATOMIC[name]
    return pair_question(item['statement'], dict(true=item['true'], false=item['false']), before, after)


def graded(before: str, after: str) -> dict[str, Any]:
    instructions = dict(task=SCORE_TASK, first_passage=before, second_passage=after, caption_handling=CAPTION_HANDLING)
    return dict(kind='score', instructions=instructions, criteria=[dict(level) for level in SCORE_LEVELS])
