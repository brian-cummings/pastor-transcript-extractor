"""Three-passage connected extraction runner; no retries, collection or acceptance."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pastor_transcript_extractor import connected_proposition_binding as contract
from pastor_transcript_extractor import evidence_pipeline_trace as trace
from pastor_transcript_extractor import profile_proposition_review as reference
from pastor_transcript_extractor import profile_binding_development as review
from pastor_transcript_extractor.collector_retrieval_json_v1_1 import seal
from pastor_transcript_extractor.config import build_llm_config, build_paths
from pastor_transcript_extractor.local_llm import OllamaClient

VERSION=contract.VERSION
MAX_RESPONSE_BYTES=2_000_000


def configuration():
    config=replace(build_llm_config(),context_size=contract.CONTEXT_SIZE,timeout_seconds=contract.TIMEOUT_SECONDS,prompt_version=VERSION)
    url=urlparse(config.base_url)
    if url.scheme not in {'http','https'} or url.hostname not in {'localhost','127.0.0.1','::1'} or url.username or url.password or url.path not in {'','/'} or url.query or url.fragment:
        raise ValueError('Connected development uses the configured loopback Ollama endpoint only')
    if not config.enabled or not config.model.strip() or config.model.endswith(':cloud'):
        raise ValueError('An enabled, configured local Ollama model is required; no downloads or cloud fallback')
    return config


def directory(base_dir=None):
    path=build_paths(base_dir).evaluation/VERSION
    if path.resolve().is_relative_to(trace.ROOT):raise ValueError('Generated artifacts belong under the configured app base outside the repository')
    return path


def panel(base_dir=None):
    reviewed=reference.load(base_dir);config=configuration()
    keys=('case_id','sermon_title','video_id','block_id','source_sha256','start_seconds','end_seconds','watch_url','texts','context_diagnostics')
    sources=[{k:deepcopy(c[k]) for k in keys} for c in reviewed['cases']]
    if [(s['video_id'],s['block_id']) for s in sources]!=[(4589,47),(3973,75),(281,123)]:raise ValueError('Only the same three supplied passages may be extracted')
    spec=seal(dict(version=VERSION,sources=sources,backend=dict(base_url=config.base_url,model=config.model,context_size=config.context_size,timeout_seconds=config.timeout_seconds),max_output_tokens=contract.MAX_OUTPUT_TOKENS,max_generation_requests=3,reference_fingerprint=reviewed['content_fingerprint'],reference_visible_to_generation=False,source_inventory_fingerprint=reviewed['source_inventory_fingerprint'],membership_fingerprint=reviewed['membership_fingerprint'],schema=contract.Extraction.model_json_schema(),instructions=contract.INSTRUCTIONS,compiler_sha256=trace.digest(contract.__file__),runner_sha256=trace.digest(__file__),generic_compiler_sha256=trace.digest(contract.generic.__file__)))
    for source in sources:body(source,spec)
    return spec,reviewed


def body(source,spec):
    # This whitelist is the entire model input. No reviewed answers, counts, titles,
    # case IDs, candidate menus or historical TypeSafe judgments enter generation.
    texts={k:source['texts'][k] for k in ('target_text','leading_context','trailing_context')}
    result=dict(model=spec['backend']['model'],messages=[dict(role='system',content=spec['instructions']),dict(role='user',content=json.dumps(texts,ensure_ascii=False))],format=spec['schema'],stream=False,options=dict(temperature=0,num_predict=spec['max_output_tokens'],num_ctx=spec['backend']['context_size']))
    if len(json.dumps(result,ensure_ascii=False).encode())>64000:raise ValueError('Connected request byte ceiling exceeded; no truncation')
    return result


class Provider:
    """Same Ollama API/config as the existing client, preserving the raw envelope."""
    def __init__(self):self.config=configuration()
    def digest(self):return OllamaClient(self.config).model_digest()  # fresh tags read, never a health-test generation
    def generate(self,payload):
        request=Request(self.config.base_url+'/api/chat',data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'},method='POST')
        with urlopen(request,timeout=self.config.timeout_seconds) as response:
            raw=response.read(MAX_RESPONSE_BYTES+1)
        if len(raw)>MAX_RESPONSE_BYTES:raise ValueError('Ollama response byte ceiling exceeded')
        return raw.decode('utf-8')


def request_for(source,spec,pin):
    return seal(dict(base_url=spec['backend']['base_url'],model_digest=pin['model_digest'],body=body(source,spec)))


def compile_case(source,record,spec):
    request=record['request'];fingerprint=request['content_fingerprint']
    provenance={k:deepcopy(source[k]) for k in ('case_id','video_id','block_id','source_sha256','start_seconds','end_seconds','watch_url','context_diagnostics')}
    provenance.update(source_inventory_fingerprint=spec['source_inventory_fingerprint'],membership_fingerprint=spec['membership_fingerprint'],request_fingerprint=fingerprint,model=spec['backend']['model'],model_digest=request['model_digest'],development_only=True)
    usage=dict(input_tokens=None,output_tokens=None)
    try:
        envelope=json.loads(record['raw_envelope'])
        if not isinstance(envelope,dict):raise ValueError('Ollama envelope is not an object')
        usage={k:envelope.get(v) for k,v in (('input_tokens','prompt_eval_count'),('output_tokens','eval_count'))}
        if any(v is not None and (type(v) is not int or v<0) for v in usage.values()):raise ValueError('Invalid Ollama token receipt')
        if record['status']!='verified' or record['digest_after']!=request['model_digest']:raise ValueError('Unverified model digest after generation')
        if envelope.get('model')!=spec['backend']['model']:raise ValueError('Ollama resolved a different model tag')
        if envelope.get('done') is not True or envelope.get('done_reason')!='stop':raise ValueError('Incomplete or output-limited extraction; no partial JSON admission')
        if all(v is not None for v in usage.values()) and sum(usage.values())>spec['backend']['context_size']:raise ValueError('Reported token use exceeds context ceiling')
        content=json.loads(envelope['message']['content'])
        compiled=contract.compile_passage(content,source,provenance)
    except (ValueError,KeyError,TypeError) as error:
        compiled=dict(frames=[],generated=[],passage_unknowns=[],compile_error=str(error))
    return dict(**source,**compiled,request_fingerprint=fingerprint,usage=usage)


def pin_path(root,spec):return root/'runs'/spec['content_fingerprint']/'backend-v1.json'


def execute(base_dir=None,*,provider_factory=Provider):
    spec,reviewed=panel(base_dir);root=directory(base_dir);folder=root/'runs'/spec['content_fingerprint']
    invocation=dict(provider_requests=0,cache_hits=0,metadata_reads=0);provider=None
    with review.exclusive(root/'execution.lock'):
        ledger_path=folder/'request-ledger-v1.json'
        ledger=review.read(ledger_path) if ledger_path.exists() else dict(version=VERSION,attempts=[])
        pinfile=pin_path(root,spec)
        pin=review.read(pinfile) if pinfile.exists() else None
        def live_digest():
            nonlocal provider
            if provider is None:provider=provider_factory()
            invocation['metadata_reads']+=1
            return provider.digest()
        if pin is None:
            pin=review.save(pinfile,dict(version=VERSION,model=spec['backend']['model'],model_digest=live_digest(),panel_fingerprint=spec['content_fingerprint']))
        if not pin['model_digest'] or pin['model']!=spec['backend']['model'] or pin['panel_fingerprint']!=spec['content_fingerprint']:raise ValueError('Backend pin differs')
        cases=[];fingerprints=[]
        for source in spec['sources']:
            request=request_for(source,spec,pin);key=request['content_fingerprint'];path=root/'cache'/f'{key}.json'
            if path.exists():
                record=review.read(path)
                if record['request']!=request or record['status']!='verified':raise ValueError('Cache request/digest unverified; no automatic repeat')
                invocation['cache_hits']+=1
            else:
                if any(a['request_fingerprint']==key for a in ledger['attempts']):raise ValueError('Ambiguous prior request; no automatic retry')
                if len(ledger['attempts'])>=3:raise ValueError('Three-generation ceiling reached')
                if live_digest()!=pin['model_digest']:raise ValueError('Configured model digest changed; no silent switch')
                ledger['attempts'].append(dict(request_fingerprint=key,case_id=source['case_id'],status='started'))
                ledger=review.save(ledger_path,ledger);invocation['provider_requests']+=1
                try:
                    raw=provider.generate(request['body'])
                    # Save the raw response before parsing/validation or post-flight metadata.
                    record=review.save(path,dict(request=request,raw_envelope=raw,status='raw_saved_unverified',digest_after=None))
                    after=live_digest()
                    if after!=pin['model_digest']:raise ValueError('Model digest changed during extraction')
                    record=review.save(path,dict(request=request,raw_envelope=raw,status='verified',digest_after=after))
                    ledger['attempts'][-1]['status']='response_cached';ledger=review.save(ledger_path,ledger)
                except Exception as error:
                    ledger['attempts'][-1].update(status='failed_or_ambiguous',error_type=type(error).__name__);review.save(ledger_path,ledger)
                    raise
            fingerprints.append(key);cases.append(compile_case(source,record,spec))
        value=dict(version=VERSION,panel=spec,backend_pin=pin,cases=cases,request_fingerprints=fingerprints,unique_request_count=len(set(fingerprints)),usage={name:sum(c['usage'][name] for c in cases) if all(c['usage'][name] is not None for c in cases) else None for name in ('input_tokens','output_tokens')},accepted_observations=False,profile_projection=False,reference_visible_to_generation=False,database_writes=0,semantic_validation='Pending Codex comparison; exact source and structural checks are not semantic acceptance')
        path=folder/'generated-v1.json'
        result=review.read(path) if path.exists() else review.save(path,value)
        if result!=seal(value):raise ValueError('Immutable generated connected run differs')
        # Preserve the initial execution receipt; later resumes get separate receipts.
        initial=folder/'invocation-v1.json'
        review.save(initial if not initial.exists() else folder/'resume-invocation-v1.json',dict(version=VERSION,**invocation))
    return result,folder,reviewed


def cached(base_dir=None):
    spec,reviewed=panel(base_dir);root=directory(base_dir);folder=root/'runs'/spec['content_fingerprint']
    pin=review.read(pin_path(root,spec));result=review.read(folder/'generated-v1.json')
    if result['panel']!=spec or result['backend_pin']!=pin:raise ValueError('Current source/configuration/backend identity differs')
    if len(result['cases'])!=3:raise ValueError('Connected source coverage differs')
    fingerprints=[]
    for source,case in zip(spec['sources'],result['cases']):
        request=request_for(source,spec,pin);key=request['content_fingerprint'];record=review.read(root/'cache'/f'{key}.json')
        if record['request']!=request:raise ValueError('Raw connected request differs')
        if compile_case(source,record,spec)!=case:raise ValueError('Generated connected bindings differ from raw response')
        fingerprints.append(key)
    usage={name:sum(c['usage'][name] for c in result['cases']) if all(c['usage'][name] is not None for c in result['cases']) else None for name in ('input_tokens','output_tokens')}
    if result['request_fingerprints']!=fingerprints or result['unique_request_count']!=3 or result['usage']!=usage:raise ValueError('Connected usage/request coverage differs')
    return result,folder,reviewed


def prepare(base_dir=None):
    spec,_=panel(base_dir)
    return dict(status='SOURCE_AND_REQUEST_PREFLIGHT_PASSED',version=VERSION,backend=spec['backend'],model_digest='Pinned from installed model metadata only when Brian executes --run; not probed during preparation.',passages=3,max_generation_requests=3,max_output_tokens_per_passage=spec['max_output_tokens'],max_propositions_per_passage=contract.MAX_PROPOSITIONS,request_bytes=[len(json.dumps(body(s,spec),ensure_ascii=False).encode()) for s in spec['sources']],provider_requests=0,metadata_reads=0,writes=0,panel_fingerprint=spec['content_fingerprint'],command='pte analysis profile-connected-binding --run --json',boundaries='Same three passages only; no pulls, installs, retries, cloud/provider fallback, TypeSafe calls, new measurement, profile projection or quotation execution.')


def report(base_dir=None,*,run_model=False,provider_factory=Provider):
    result,folder,reviewed=execute(base_dir,provider_factory=provider_factory) if run_model else cached(base_dir)
    path=folder/'semantic-review-v1.json'
    comparison=review.validate_comparison(review.read(path),result,reviewed) if path.exists() else None
    output=seal(dict(version=VERSION,status='CONNECTED_RUN_COMPARED' if comparison else 'GENERATED_AWAITING_CODEX_SEMANTIC_COMPARISON',generated=result,reference=reviewed,comparison=comparison,field_outcomes={field:dict(Counter(row['fields'][field]['outcome'] for row in comparison['readings'])) for field in review.FIELDS} if comparison else {},generated_candidates=sum(len(c['generated']) for c in result['cases']),structurally_valid_candidates=sum(bool(g['binding']) for c in result['cases'] for g in c['generated']),passage_rejections=[dict(case_id=c['case_id'],error=c['compile_error']) for c in result['cases'] if c['compile_error']],invocation=review.read(folder/'invocation-v1.json'),run_directory=str(folder)))
    from pastor_transcript_extractor import connected_binding_presentation as presentation
    output=seal(dict(output,renderer_sha256=trace.digest(presentation.__file__)))
    review.save(folder/'review-v1.json',output)
    (folder/'review-v1.md').write_text(presentation.markdown(output))
    (folder/'index.html').write_text(presentation.render(output))
    return output,folder/'index.html'
