"""Opt-in assertion-force boundary for generated analytical claims.

The model inventories force for the frozen candidate ID. Code checks its
available authority; it never weakens a claim or infers its force from keywords.
"""
VERSION='profile-assertion-force-v3'
FORCES=('local_observation','sample_membership','comparative_priority','dominance','frequency','causal')
INSTRUCTION='''
The candidate carries an assertion_contract. Independently inventory the force of
every consequential assertion in its unchanged statement, including modifiers.
Do not copy the producer's declared_force as your judgment. Return assertion_force
with candidate_id, complete, forces (all distinct forces present anywhere in the
whole statement), measurement_entitlement and reason. Reference the supplied
candidate ID; do not copy or shorten the statement. One stronger assertion makes
its force part of the inventory even when every other assertion is local.
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
For the entire statement also return measurement_entitlement: within_meaning,
requires_missing_distinction, or unresolved. Check the exact admitted measurement
meanings and states independently of topical source support. A measurement whose
meaning admits alternatives does not establish every alternative or which one was
observed. A category name is shorthand, not an extra observation. Do not replace
an admitted disjunction with a conjunction or select a narrower alternative unless
another supplied qualified observation already establishes that distinction.
Finding the distinction in raw source text during this support check cannot create
the missing analytical observation. Nor does co-presence alone establish a new
explanatory relationship. Mark requires_missing_distinction when the unchanged
assertion needs such additional analytical evidence. Return a brief reason naming
the supplied meaning and the entitlement or gap, without repairing the candidate.
'''


def schema(candidate):
    return dict(type='object',properties=dict(candidate_id=dict(type='string',enum=[candidate['id']]),
        complete=dict(type='boolean'),forces=dict(type='array',minItems=1,maxItems=len(FORCES),uniqueItems=True,
            items=dict(type='string',enum=list(FORCES))),
        measurement_entitlement=dict(type='string',enum=['within_meaning','requires_missing_distinction','unresolved']),
        reason=dict(type='string',minLength=1,maxLength=300)),
        required=['candidate_id','complete','forces','measurement_entitlement','reason'],additionalProperties=False)


def assess(candidate,value):
    contract=candidate['assertion_contract']
    if contract['version']!=VERSION or not set(contract['allowed_forces'])<=set(FORCES):
        raise ValueError('Unknown assertion authority contract')
    if (set(value)!={'candidate_id','complete','forces','measurement_entitlement','reason'} or type(value['complete']) is not bool
        or value['candidate_id']!=candidate['id']):
        raise ValueError('Incomplete assertion force inventory')
    if (not isinstance(value['forces'],list) or not 1<=len(value['forces'])<=len(FORCES)
        or any(f not in FORCES for f in value['forces']) or len(set(value['forces']))!=len(value['forces'])
        or value['measurement_entitlement'] not in ('within_meaning','requires_missing_distinction','unresolved')
        or not isinstance(value['reason'],str) or not 0<len(value['reason'].strip())<=300):
        raise ValueError('Invalid whole-candidate assertion inventory')
    forces=sorted(value['forces'])
    allowed=set(contract['allowed_forces'])
    accepted=(value['complete'] and set(forces)<=allowed and contract['declared_force'] in allowed
        and value['measurement_entitlement']=='within_meaning')
    return dict(version=VERSION,inventory=value,allowed_forces=sorted(allowed),
        declared_force=contract['declared_force'],status='within_authority' if accepted else 'unwarranted_or_unresolved')
