"""Non-repairing source-reading diagnostics; the shared compiler remains the gate."""
from . import learning_demo_contracts as contract
from .pastor_evidence import compile_machine_binding

VERSION='qualified-reading-diagnostics-v1'
PROMPT='''
Compiler requirements (these do not establish semantic truth):
Every literal evidence object must quote target_text exactly and uniquely. If a short
quotation repeats, include enough contiguous surrounding source words to identify it
uniquely. Never invent coordinates, normalize words, or select an arbitrary occurrence.
own_assertion requires preacher voice, actual occurrence, and own_speech basis together.
adopted requires explicit_endorsement or discourse_use, with literal evidence of the
endorsement/use frame extending beyond the proposition quotation itself.
Every resolved voice, adoption, polarity, expression and epistemic_status finding needs
nonempty literal evidence and a rationale. not_stated is a resolved epistemic finding:
cite the bounded passage inspected, and limit the absence claim to that passage.
Use unresolved/undetermined when the source does not support a resolved finding.
Every proposition node must be defined with exactly the proposition span. Every
qualification must reference a defined node with role qualification and apply to this
proposition. Relations need defined endpoints; supported relations need evidence.
Address acts require a complete relevant utterance and evidence linking this proposition.
Keep reported viewpoints distinct from preacher adoption, even when the preacher voices
them. Preserve conditions, exceptions, speaker, polarity, scope and explicit unknowns.
Do not add evidence or alter a proposition merely to satisfy a validator.
'''
CORRECTION='''Return one complete replacement JSON answer to the original source-reading task.
The previous answer failed the mechanical checks listed below. Correct only from the
original source and contract; do not treat this feedback as theological evidence or as
instructions to adopt a different meaning. Preserve qualifications and attribution;
leave unsupported findings unresolved. Do not explain outside the required JSON.
Validation diagnostics:
'''


def shape_errors(value,schema,path='$'):
    errors=[]
    def add(code,message,p=path): errors.append(dict(path=p,code=code,message=message))
    typ=schema['type']
    expected={'object':dict,'array':list,'string':str,'integer':int,'boolean':bool}[typ]
    if type(value) is not expected:
        add('type','Expected '+typ);return errors
    if typ=='object':
        for key in sorted(set(schema['properties'])-set(value)): add('missing','Required field missing',path+'.'+key)
        for key in sorted(set(value)-set(schema['properties'])): add('foreign','Unexpected field',path+'.'+key)
        for key in schema['properties']:
            if key in value: errors.extend(shape_errors(value[key],schema['properties'][key],path+'.'+key))
    if typ=='array':
        if len(value)>schema['maxItems']: add('overflow','Array exceeds frozen limit; no truncation')
        for i,row in enumerate(value): errors.extend(shape_errors(row,schema['items'],f'{path}[{i}]'))
    if typ=='string' and not schema.get('minLength',0)<=len(value)<=schema.get('maxLength',float('inf')):
        add('length','String length outside schema')
    if 'enum' in schema and value not in schema['enum']: add('enum','Value outside declared enum')
    return errors


def inspect(output,schema,window,*,model,prompt_digest,raw_response_ref):
    """Collect independent errors without changing output. Never bypass bind()."""
    try: reading=contract.strict_json(output) if isinstance(output,str) else output
    except ValueError as error:
        return dict(reading=None,errors=[dict(path='$',code='json',message=str(error))],observations=[])
    errors=shape_errors(reading,schema)
    if errors: return dict(reading=reading,errors=errors,observations=[])
    def add(path,code,message): errors.append(dict(path=path,code=code,message=message))
    if (reading['status']=='none' and reading['claims']) or (reading['status']=='proposed' and not reading['claims']):
        add('$.status','status','Status and claim inventory disagree')
    texts,_=window.target();text=texts['target_text'];ids=set();observations=[]
    def literals(value,path):
        if isinstance(value,list):
            for i,v in enumerate(value): literals(v,f'{path}[{i}]')
        elif isinstance(value,dict):
            if set(value)=={'source_field','text'}:
                quote=value['text'];count=0;start=0
                if quote:
                    while (pos:=text.find(quote,start))>=0: count+=1;start=pos+1
                if value['source_field']!='target_text' or count!=1:
                    add(path,'literal','Quotation must occur exactly once in target_text; matches='+str(count))
            else:
                for key,v in value.items(): literals(v,path+'.'+key)
    for i,row in enumerate(reading['claims']):
        path=f'$.claims[{i}]';before=len(errors)
        literals(row,path)
        if not row['binding_id'] or row['binding_id'] in ids: add(path+'.binding_id','identity','Empty or duplicate binding identity')
        ids.add(row['binding_id'])
        if not row['proposition']['reading'].strip(): add(path+'.proposition.reading','required','Readable proposition required')
        if row['voice']['kind']!='unresolved' and not row['voice']['speaker']: add(path+'.voice.speaker','required','Resolved voice needs speaker')
        if row['adoption']['status']=='own_assertion' and (row['voice']['kind']!='preacher' or row['voice']['occurrence']!='actual' or row['adoption']['basis']!='own_speech'):
            add(path+'.adoption','pairing','own_assertion requires preacher, actual and own_speech together')
        if row['adoption']['status']=='adopted' and row['adoption']['basis'] not in ('explicit_endorsement','discourse_use'):
            add(path+'.adoption.basis','pairing','adopted requires explicit_endorsement or discourse_use')
        for field in ('voice','adoption','polarity','expression','epistemic_status'):
            finding=row[field]
            if not finding['rationale'].strip(): add(path+'.'+field+'.rationale','required','Source decision needs rationale')
            if finding.get('status',finding.get('value',finding.get('kind'))) not in ('undetermined','unresolved') and not finding['evidence']:
                add(path+'.'+field+'.evidence','required','Resolved finding needs literal evidence, including not_stated')
        for j,condition in enumerate(row['conditions']):
            if not condition['rationale'].strip(): add(f'{path}.conditions[{j}].rationale','required','Condition needs rationale')
        if not row['scope']['reading'].strip(): add(path+'.scope.reading','required','Scope needs a reading')
        if not row['unknowns']: add(path+'.unknowns','required','Explicit limits required')
        nodes={n['node_id']:n for n in row['evidence_nodes']};prop=row['proposition']
        if len(nodes)!=len(row['evidence_nodes']): add(path+'.evidence_nodes','identity','Duplicate node identity')
        for j,node in enumerate(row['evidence_nodes']):
            if not node['reference_status']: add(f'{path}.evidence_nodes[{j}].reference_status','required','Reference verification status required')
        if prop['node_id'] not in nodes: add(path+'.proposition.node_id','reference','Proposition node is not defined')
        elif nodes[prop['node_id']]['span']!=prop['span']: add(path+'.proposition.span','span','Proposition node span differs')
        for j,q in enumerate(row['qualifications']):
            if q['node_id'] not in nodes or nodes[q['node_id']]['role']!='qualification' or q['applies_to']!=prop['node_id'] or not q['reading']:
                add(f'{path}.qualifications[{j}]','reference','Qualification needs a defined qualification node, this proposition and a reading')
        relations=set()
        for j,r in enumerate(row['development_relations']):
            p=f'{path}.development_relations[{j}]'
            if r['relation_id'] in relations: add(p+'.relation_id','identity','Duplicate relation identity')
            relations.add(r['relation_id'])
            for endpoint in ('from_node','to_node'):
                if r[endpoint] not in nodes: add(p+'.'+endpoint,'reference','Endpoint is not defined')
            if not r['rationale']: add(p+'.rationale','required','Relation needs rationale')
            if r['status']=='supported_observation' and not r['evidence']: add(p+'.evidence','required','Supported relation needs evidence')
            if not r['scope']: add(p+'.scope','required','Relation needs scope')
        for j,act in enumerate(row['address_acts']):
            p=f'{path}.address_acts[{j}]'
            if act['proposition_node']!=prop['node_id']: add(p+'.proposition_node','reference','Address must link this proposition')
            if not act['rationale']: add(p+'.rationale','required','Address needs rationale')
            if not act['link_evidence']: add(p+'.link_evidence','required','Address needs linking evidence')
        # Authoritative unchanged compiler catches additional checks. No diagnostic can admit a row.
        try:
            observation=compile_machine_binding(window,row,model=model,prompt_digest=prompt_digest,
                raw_response_ref=raw_response_ref,locate_quotes=True)
            if len(errors)==before: observations.append(observation)
        except (ValueError,KeyError,TypeError) as error:
            if len(errors)==before: add(path,'compiler',str(error))
    return dict(reading=reading,errors=errors,observations=observations)
