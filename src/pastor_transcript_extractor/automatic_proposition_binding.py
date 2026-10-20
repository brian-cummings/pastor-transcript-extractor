"""Source-only development binding with typed selections; no reference answers.

The model interprets code-owned source candidates. Candidate coverage is explicitly
limited: it is part of the development result, not presumed by a valid record.
"""
from copy import deepcopy
import re

from pastor_transcript_extractor import theological_binding as generic
from pastor_transcript_extractor.binding_evidence import context_digest, text_digest, target_span

VERSION = 'automatic-generic-proposition-binding-dev-v1'
MODEL = 'jev-1.13.0'
# This is an abstention rule for this development run, not a measurement threshold.
MIN_PROBABILITY = .80
MAX_UNITS = 64
MAX_BINDINGS = 40
BATCH_SIZE = 2
BOUNDARY = ('Use only candidate.span for proposition content, target_text for its attribution/adoption/use. '
            'Context resolves references only, never supplies missing teaching. Quotation alone is not adoption; '
            'affirmative teaching/warrant use can support adoption without literal agreement words. '
            'Do not infer a logical opposite from rejection. Preserve internal negation in the literal proposition. '
            'Projected words are not attested listener speech. Questions do not imply uncertainty. '
            'No systematic doctrine predicate, assurance interpretation, pastor belief or quality judgment.')


def span(text, start, end):
    while start < end and text[start].isspace():start += 1
    while end > start and text[end-1].isspace():end -= 1
    return dict(source_field='target_text',start=start,end=end,text=text[start:end])


def source_units(texts):
    """Punctuation and quote units; generic clause windows for unpunctuated captions.

    No reviewed anchors, paraphrases, source-specific literals or expected labels.
    Both outer sentences and embedded quotes survive, allowing distinct speech layers.
    """
    text=texts['target_text'];units=[];seen=set()
    def add(start,end,origin):
        s=span(text,start,end)
        if not s['text'] or (s['start'],s['end']) in seen:return
        if len(s['text'].split()) < 3:return
        seen.add((s['start'],s['end']));units.append(dict(span=s,origin=origin))
    start=0
    for m in re.finditer(r'[.!?]["”]*\s+|\n+',text):
        end=m.start()+len(m.group().rstrip());add(start,end,'sentence');start=m.end()
    add(start,len(text),'sentence')
    for m in re.finditer(r'"([^"\n]+)"|“([^”\n]+)”',text):
        group=1 if m.group(1) is not None else 2
        add(m.start(group),m.end(group),'embedded_quote')
    # Long punctuation-poor units need alternatives. Generic conjunction/pronoun
    # boundaries are lexical candidates, not semantic annotations or guaranteed clauses.
    for unit in list(units):
        if len(unit['span']['text'].split()) <= 45:continue
        lo,hi=unit['span']['start'],unit['span']['end']
        cuts=[lo]+[m.start() for m in re.finditer(r'\b(?:and|but|because|if|unless|when|he|she|they|you|we|it)\b',text[lo:hi],re.I)]
        cuts=[lo]+[lo+c for c in cuts[1:] if c>0]+[hi]
        cuts=sorted(set(cuts))
        for n in range(len(cuts)-1):
            # Up to three lexical clauses keeps contrasts together without treating
            # an entire caption paragraph as one necessarily atomic proposition.
            for width in (1,2,3):
                if n+width < len(cuts):
                    left,right=cuts[n],cuts[n+width]
                    words=len(text[left:right].split())
                    if 5 <= words <= 55:add(left,right,'caption_clause_window')
    units.sort(key=lambda u:(u['span']['start'],u['span']['end']))
    if len(units)>MAX_UNITS:raise ValueError('Source-unit ceiling exceeded; no silent truncation')
    return [dict(candidate_id=f'candidate-{i+1:02d}',**u) for i,u in enumerate(units)]


def question(task,criteria):
    return dict(instructions=dict(task=task,boundary=BOUNDARY),criteria=criteria)


def discovery_questions(units):
    return {u['candidate_id']:question(
        'Does source_candidates["'+u['candidate_id']+'"] express a locally recoverable theological proposition, a reported/evaluated religious stance, or an invitation to voice theological confidence? '
        'Keep report, projected declaration and outer invitation as separate possible units. Exclude dangling clauses, bare referents, duplicate wording contained in a more complete same-layer candidate, mere fillers and unrelated illustration details. '
        'A theological assertion need not fit an assurance predicate. Use target_text to interpret but not replace the exact candidate.',
        dict(include='A distinct recoverable source proposition or theological invitation is expressed in this candidate span.',
             exclude='Not such a proposition, incomplete fragment, unrelated detail, or redundant same-layer candidate.',
             unresolved='Its proposition or boundary cannot be established locally.')) for u in units}


def evidence_pool(texts,units,unit):
    # Exact surrounding source windows are available for independent attribution,
    # adoption and relation evidence, including an endorsement in another sentence.
    text=texts['target_text'];pool={}
    spans=[unit['span']]+[u['span'] for u in units if u['origin'] in ('sentence','embedded_quote')]
    sentences=[u['span'] for u in units if u['origin']=='sentence']
    for i,s in enumerate(sentences):
        if i+1<len(sentences):spans.append(span(text,s['start'],sentences[i+1]['end']))
    spans.sort(key=lambda s: (abs((s['start']+s['end'])/2-(unit['span']['start']+unit['span']['end'])/2),s['end']-s['start']))
    spans=spans[:14]+[unit['span'],span(text,0,len(text))]
    seen=set()
    for s in spans:
        key=s['start'],s['end']
        if key not in seen:pool['e'+str(len(pool))]=s;seen.add(key)
    return pool


def field_questions(texts,unit,pool):
    selector={key:dict(exact_span=value) for key,value in pool.items()}
    selector.update(none='No such evidence is stated/bound in the target.',unresolved='The relevant source binding is unresolved.')
    q={}
    def add(name,task,criteria):q[name]=question(task+' Judge candidate.span in state.',criteria)
    add('voice','Who voices the candidate proposition, independently from the preacher’s endorsement?',dict(preacher='The preacher’s own current words.',quoted_or_reported='Words attributed to someone else, including projected listener words.',unresolved='Voiced speaker/frame unresolved.'))
    # Speaker values are source mentions, not a theology ontology. Non-name roles
    # cover unrecorded/hypothetical speech without inventing a person identity.
    names=sorted(set(re.findall(r'\b[A-Z][a-z]{2,}\b',texts['target_text'])))
    speakers={n:'Speaker identified by literal target mention '+n for n in names}
    speakers.update(preacher='The preacher.',invited_listener='The listener invited/projected to speak.',reported_people='Unidentified people described as speaking.',unresolved='Speaker identity unresolved.')
    add('speaker','Which speaker identity/role is supported for this candidate?',speakers)
    add('occurrence','Does the discourse present these words as actually spoken/reported, or only projected/invited?',dict(actual='Preacher speech or speech reported as occurring; not independent historical verification.',projected='Words someone is invited, imagined or expected to say, without attested occurrence.',unresolved='Occurrence unresolved.'))
    add('adoption','How does the preacher use the exact proposition? Keep speaker and adoption independent; local adoption is not systematic doctrine.',dict(own_assertion='Preacher presents this declarative teaching as own current assertion.',adopted='Preacher affirmatively endorses or uses this exact proposition as teaching/warrant or offered confession; scope to that use.',reported_not_adopted='Merely reports the proposition without affirmative current adoption.',rejected='Rejects this exact proposition, not merely a different stance or its inferred opposite.',undetermined='The exact proposition’s adoption is unresolved; an owned invitation act alone need not assert a hearer’s actual status.'))
    add('basis','What source basis supports the preacher’s use of this proposition?',dict(own_speech='Own current teaching assertion.',explicit_endorsement='Explicit positive endorsement beyond quotation.',discourse_use='Affirmative teaching/warrant/application/offered-confession use evidenced by surrounding discourse.',explicit_rejection='Exact proposition is explicitly rejected.',quotation_only='Quotation/report without an independent endorsement/use frame.',unresolved='Use basis unresolved.'))
    add('polarity','What is the polarity of the exact voiced proposition as worded? Retain its internal not/but negations; distinguish the preacher’s rejection of someone’s words.',dict(affirmed='The literal proposition is voiced affirmatively, including its internal negation/contrast.',denied='The exact literal proposition is explicitly negated in the utterance frame.',unsettled='The speaker explicitly leaves the proposition unsettled.',unresolved='The expression does not assert polarity or its polarity is unresolved.'))
    add('expression','What is the candidate’s surface expression, independently of occurrence or communicative act?',dict(assertion='Declarative assertion form, including a projected declaration.',question='Question form, including a rhetorical invitation.',open_issue='Explicitly left open for consideration.',unresolved='Surface expression unresolved.'))
    add('uncertainty','Does this candidate explicitly express uncertainty about its proposition? A rhetorical invitation/question mark, analyst uncertainty or reported uncertainty is not the preacher’s own expressed uncertainty.',dict(expressed_uncertainty='The voiced speaker explicitly states uncertainty about this proposition.',not_stated='No uncertainty is stated in the local wording; not a global certainty trait.',unresolved='The source’s epistemic expression is unresolved.'))
    for name,task in dict(voice_evidence='Select exact attribution/projected-speech evidence.',adoption_evidence='Select exact evidence of preacher use/adoption/rejection; quoted words alone do not establish adoption.',scope_evidence='Select exact explicit scope/referent/time evidence bound to this proposition, without treating unqualified language as universal.',uncertainty_evidence='Select exact explicit uncertainty wording, or none if no uncertainty is stated.').items():add(name,task,selector)
    add('condition','Select a source span explicitly setting a condition/exception on this proposition. Do not attach an unrelated if, rationale or concession.',selector)
    add('condition_kind','If a condition/exception is present, which kind applies?',dict(condition='Explicit if/when/as-long-as condition attached to this proposition.',exception='Explicit unless/except qualification attached to this proposition.',none='No bound condition/exception.',unresolved='Conditional relation unresolved.'))
    add('qualification','Select an exact materially relevant nonconditional qualification, such as concessive wording, bound to this proposition. A mere reason belongs to the development link.',selector)
    add('relation','What development relation is explicitly performed between this candidate and another source-grounded statement? Select none without exact relationship evidence.',dict(reason_supports_claim='An evidenced reason/example/warrant supports this candidate claim.',addresses_alternative='This candidate responds to an evidenced alternative stance.',grounds_response='This candidate response is grounded in an evidenced reason/claim.',none='No such development relation bound here.',unresolved='Relation unresolved.'))
    add('relation_endpoint','Select the exact other semantic endpoint for a development relation with this candidate. Co-occurrence alone is not a relation.',selector)
    add('relation_evidence','Select exact source evidence of the development link, not just an isolated endpoint.',selector)
    add('address','What address act does this candidate express, if any? Do not turn a reported/projected act into current listener address.',{**{key:key.replace('_',' ')+' actually expressed in this candidate.' for key in ('acknowledgment','perspective_taking','reassurance','challenge','warning','invitation','care_offer')},'none':'No address act established.','unresolved':'Act unresolved.'})
    add('addressee','If an address act is present, who is its addressee? A projected listener’s prayer is distinct from the preacher inviting that prayer.',dict(God_in_prayer='God addressed in prayer.',no_address='No addressee.',direct_current_listener='The preacher’s current hearer.',applied_we='Present hearers through explicitly applied inclusive we.',general_hypothetical='Hypothetical/general person.',reported_person='Historical/reported addressee.',unresolved='Addressee unresolved.'))
    add('address_voice','For a source-supported act linked to this candidate, whose utterance performs the act? The outer preacher invitation may frame an embedded projected declaration.',dict(preacher='Preacher performs current address.',quoted_or_reported='Address attributed to another speaker.',unresolved='Act voice unresolved.'))
    add('address_adoption','For an address act linked to this candidate, what is the preacher’s stance toward that act? Judge independently of proposition adoption; a preacher can own an invitation without declaring a hearer’s saving status.',dict(own_or_adopted='Own present or affirmatively adopted address act.',not_adopted_report='Reported act without current adoption.',explicitly_rejected='Exact address act rejected.',unresolved='Act adoption unresolved.'))
    add('address_evidence','Select exact evidence linking this candidate’s act to that addressee. The surrounding invitation may frame a projected declaration; do not attest a listener response.',selector)
    return q


def choices(raw,inventory):
    if set(raw['answers'])!=set(inventory):raise ValueError('Provider question inventory differs')
    result={};unresolved=[]
    for key,q in inventory.items():
        answer=raw['answers'][key];selected=answer['choice'];probs=answer['probabilities']
        if set(probs)!=set(q['criteria']) or selected not in probs:raise ValueError('Provider answer vocabulary differs')
        if any(type(v) not in (int,float) or not 0<=v<=1 for v in probs.values()):raise ValueError('Invalid provider probabilities')
        if abs(sum(probs.values())-1)>.025:raise ValueError('Provider probabilities do not sum to one')
        if probs[selected]<MIN_PROBABILITY:
            selected='undetermined' if key=='adoption' else 'unresolved';unresolved.append(key)
        result[key]=selected
    return result,unresolved


def compose(texts,unit,pool,decisions,provenance):
    """Compile typed generated choices, never repairing meaning to match a reference."""
    d=decisions;claim=deepcopy(unit['span']);key=provenance['case_id']+'-auto-'+unit['candidate_id'];node_id=key+':claim';diagnostics=[]
    def selected(name):
        val=d[name]
        return deepcopy(pool[val]) if val in pool else None
    def finding(value,evidence,rationale,**extra):
        return dict(value=value,evidence=evidence,rationale=rationale,**extra)
    voice_e=selected('voice_evidence');adopt_e=selected('adoption_evidence');scope_e=selected('scope_evidence');uncertain_e=selected('uncertainty_evidence')
    voice=d['voice'];occurrence=d['occurrence'];adoption=d['adoption'];basis=d['basis']
    # Independent incompatible answers are withheld, never silently made consistent.
    if not voice_e:voice='unresolved';diagnostics.append('attribution_evidence_missing')
    if adoption=='own_assertion' and (voice!='preacher' or occurrence!='actual' or basis!='own_speech'):
        adoption='undetermined';basis='unresolved';diagnostics.append('incompatible_own_assertion_frame')
    if adoption=='adopted' and (basis not in {'explicit_endorsement','discourse_use'} or not adopt_e or claim['start']<=adopt_e['start']<adopt_e['end']<=claim['end']):
        adoption='undetermined';basis='unresolved';diagnostics.append('adoption_frame_insufficient')
    if adoption!='undetermined' and not adopt_e:
        adoption='undetermined';basis='unresolved';diagnostics.append('adoption_evidence_missing')
    unknowns=['Automatic development candidate; no accepted observation, pastor-wide position, verified hearer status or external quotation accuracy.']
    unknowns += [name.replace('_',' ')+': unresolved by generated choices.' for name in ('voice','speaker','occurrence','adoption','polarity','expression','uncertainty') if d[name] in {'unresolved','undetermined'}]
    uncertainty=d['uncertainty']
    if uncertainty=='expressed_uncertainty' and not uncertain_e:
        uncertainty='unresolved';diagnostics.append('uncertainty_evidence_missing')
    row=dict(binding_id=key,title=claim['text'][:95],proposition=dict(node_id=node_id,span=claim,reading=claim['text']),
        voice=dict(kind=voice,speaker=None if d['speaker']=='unresolved' else d['speaker'].replace('_',' '),occurrence=occurrence,evidence=[voice_e] if voice_e else [],rationale='Automatic source-voice/occurrence selection; speaker identity remains distinct from preacher endorsement.'),
        adoption=dict(status=adoption,basis=basis,evidence=[adopt_e] if adopt_e else [],rationale='Automatic independent preacher-use selection. Discourse use requires the selected target frame; it is not inferred merely from quotation.'),
        polarity=finding(d['polarity'],[claim],'Polarity of the literal voiced proposition, with internal negation retained; no logical opposite synthesized.'),
        expression=finding(d['expression'],[claim],'Automatic surface-form selection, independent of utterance occurrence/address act.'),
        epistemic_status=finding(uncertainty,[uncertain_e] if uncertain_e else [claim] if uncertainty=='not_stated' else [],'Local expressed uncertainty only; analyst withholding and question form are distinct.'),
        scope=dict(reading=scope_e['text'] if scope_e else 'No explicit scope bound; local candidate only. Identity, application and universal scope remain unestablished.',evidence=[scope_e] if scope_e else []),
        conditions=[],qualifications=[],development_relations=[],address_acts=[],evidence_nodes=[],unknowns=unknowns)
    def node(name,s,role,v=voice,a=adoption):
        nid=key+':'+name;row['evidence_nodes'].append(dict(node_id=nid,span=s,role=role,voice=v,adoption=a,reference_status='Exact source; no independent external verification'));return nid
    node('claim',claim,'listener_response' if occurrence=='projected' else 'guidance' if d['expression']=='question' else 'teaching_statement')
    condition=selected('condition')
    if condition and d['condition_kind'] in {'condition','exception'}:
        row['conditions'].append(dict(kind=d['condition_kind'],span=condition,rationale='Automatically selected as explicitly attached to this proposition; not a necessity/sufficiency inference.'))
    elif condition or d['condition_kind'] not in {'none','unresolved'}:diagnostics.append('condition_binding_incomplete')
    qualification=selected('qualification')
    if qualification:
        nid=node('qualification',qualification,'qualification')
        row['qualifications'].append(dict(node_id=nid,applies_to=node_id,reading='Source-selected nonconditional qualification: '+qualification['text']))
    endpoint=selected('relation_endpoint');rel_e=selected('relation_evidence')
    if d['relation'] in {'reason_supports_claim','addresses_alternative','grounds_response'}:
        if endpoint and rel_e and endpoint!=claim:
            other=node('endpoint',endpoint,'alternative' if d['relation']=='addresses_alternative' else 'reason',v='unresolved',a='undetermined')
            row['development_relations'].append(dict(relation_id=key+':development',episode_id=provenance['case_id'],kind=d['relation'],from_node=node_id if d['relation']=='addresses_alternative' else other,to_node=other if d['relation']=='addresses_alternative' else node_id,evidence=[rel_e],voice=voice,adoption=adoption,scope='Local automatically proposed link; no demonstrated depth/quality claim.',stated_qualifications=[],status='supported_observation',unresolved_reason=None,rationale='Automatically selected semantic link between literal endpoints; requires development review.'))
        else:diagnostics.append('development_link_incomplete')
    address_e=selected('address_evidence')
    if d['address'] not in {'none','unresolved'}:
        if address_e and d['addressee']!='unresolved':
            row['address_acts'].append(dict(act_id=key+':address',type=d['address'],utterance_span=address_e,voice=d['address_voice'],adoption=d['address_adoption'],addressee=dict(kind=d['addressee'],evidence=[address_e]),proposition_node=node_id,link_evidence=[address_e],rationale='Automatic address/addressee binding. An invitation does not attest listener response; no circumstance admission.',circumstance_binding='Not evaluated.'))
        else:diagnostics.append('address_link_incomplete')
    # A source-resolved role may still be unidentified; do not invent a speaker.
    if row['voice']['kind']!='unresolved' and not row['voice']['speaker']:
        row['voice']['kind']='unresolved';diagnostics.append('speaker_identity_unresolved')
    row['unknowns']+=diagnostics
    binding=generic.bind(texts,row,provenance)
    binding.update(authorship='TypeSafe-generated development candidate; not source-reviewed or accepted',automatic_binding=True,accepted_observation=False,diagnostics=diagnostics,semantic_validation='Literal/structural checks only; generated meaning awaits development comparison')
    return binding
