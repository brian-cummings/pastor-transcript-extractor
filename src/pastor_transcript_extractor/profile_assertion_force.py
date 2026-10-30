"""Opt-in assertion-force boundary for generated analytical claims.

The model identifies wording and force. Code binds literal excerpts and checks
available authority; it never weakens a claim or infers its force from keywords.
"""
VERSION='profile-assertion-force-v1'
FORCES=('local_observation','sample_membership','comparative_priority','dominance','frequency','causal')
INSTRUCTION='''
The candidate carries an assertion_contract. Independently inventory the force of
every consequential assertion in its unchanged statement, including modifiers.
Do not copy the producer's declared_force as your judgment. Return assertion_force
with complete and assertions (each a literal statement excerpt and force).
local_observation describes an individual observed relationship without comparing
or characterizing repetition. sample_membership states only that declared examples
include specified findings. comparative_priority ranks alternatives; dominance
characterizes relative emphasis; frequency characterizes counts, recurrence,
proportions or consistency over a domain; causal explains production of an outcome.
Classify the assertion actually made, even when its weaker underlying topic is
supported. Scope limits do not erase a stronger assertion inside that scope.
Only allowed_forces have supplied authority. A missing force warrant is not
repaired by finding related source language. Mark complete false when you cannot
inventory the statement; unresolved force is a valid outcome, never a retry request.
'''


def schema():
    return dict(type='object',properties=dict(complete=dict(type='boolean'),assertions=dict(type='array',minItems=1,maxItems=12,
        items=dict(type='object',properties=dict(excerpt=dict(type='string',minLength=1,maxLength=300),
            force=dict(type='string',enum=list(FORCES))),required=['excerpt','force'],additionalProperties=False))),
        required=['complete','assertions'],additionalProperties=False)


def assess(candidate,value):
    contract=candidate['assertion_contract']
    if contract['version']!=VERSION or not set(contract['allowed_forces'])<=set(FORCES):
        raise ValueError('Unknown assertion authority contract')
    if set(value)!={'complete','assertions'} or type(value['complete']) is not bool or not 1<=len(value['assertions'])<=12:
        raise ValueError('Incomplete assertion force inventory')
    for item in value['assertions']:
        if (set(item)!={'excerpt','force'} or item['force'] not in FORCES or not isinstance(item['excerpt'],str)
            or not item['excerpt'].strip() or len(item['excerpt'])>300 or item['excerpt'] not in candidate['statement']):
            raise ValueError('Assertion force excerpt must bind unchanged candidate text')
    forces=sorted({item['force'] for item in value['assertions']})
    allowed=set(contract['allowed_forces'])
    accepted=value['complete'] and set(forces)<=allowed and contract['declared_force'] in allowed
    return dict(version=VERSION,inventory=value,allowed_forces=sorted(allowed),
        declared_force=contract['declared_force'],status='within_authority' if accepted else 'unwarranted_or_unresolved')
