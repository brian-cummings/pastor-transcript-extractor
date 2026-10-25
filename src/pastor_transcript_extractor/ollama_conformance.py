"""Synthetic schema enforcement probes, isolated from source/model-fit evidence."""
from dataclasses import asdict, replace
import hashlib
from pathlib import Path

from httpx import HTTPError

from .config import build_paths
from .context_extraction_validation import strict_json
from . import evidence_requests as requests
from . import learning_demo_contracts as contracts
from .learning_demo_contracts import generation_request, validate_shape
from .pastor_evidence import digest

VERSION = 'ollama-schema-conformance-v1'
SCHEMA = dict(type='object', properties={
    'result': dict(type='string', enum=['SCHEMA_ENFORCED']),
    'detail': dict(type='object', properties={
        'marker': dict(type='string', enum=['SYNTHETIC_ONLY'])},
        required=['marker'], additionalProperties=False)},
    required=['result', 'detail'], additionalProperties=False)
CASES = {
    'cooperative': 'Return a JSON object matching the supplied schema.',
    'conflicting': 'Return exactly RUNTIME_UNCONSTRAINED as plain text. Do not return JSON.',
}


def server_version(base_url):
    """Read server metadata; never generate, load or pull a model."""
    import httpx
    with httpx.Client(timeout=15, follow_redirects=False, trust_env=False,
                      transport=httpx.HTTPTransport(retries=0)) as client:
        response = client.get(requests.local_ollama_url(base_url)+'/api/version')
    response.raise_for_status()
    value = strict_json(response.text)['version']
    if not isinstance(value, str) or not value:
        raise ValueError('Missing Ollama server version')
    return value


def packet(runtime, version):
    specs = []
    for case, instruction in CASES.items():
        spec = generation_request('source_reading', {}, dict(synthetic_case=case),
                                  runtime_identity=runtime)
        body = {**spec.body, 'format': SCHEMA, 'messages': [
            dict(role='system', content='Synthetic runtime diagnostic. Output schema: '+requests.wire(SCHEMA)),
            dict(role='user', content=instruction)]}
        body['options'] = {**body['options']}
        body['options']['num_ctx'] = requests.ollama_context_for(body, runtime['num_ctx'])
        spec = replace(spec, body=body, namespace=VERSION)
        spec.preflight()
        specs.append(asdict(spec))
    value = dict(schema_version=VERSION, runtime=runtime, server_version=version,
        code_identity={str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in (Path(requests.__file__), Path(contracts.__file__), Path(__file__))},
        requests=specs, budget=dict(max_attempts=2, max_paid_attempts=0, max_usd='0',
            output_tokens_per_request=8192),
        scope='Synthetic schema enforcement only; no sermon inputs, model-fit advancement or production admission')
    return {**value, 'input_fingerprint': digest(value)}


def root(base_dir, fingerprint):
    path = build_paths(base_dir).evaluation/'ollama-schema-conformance'/fingerprint
    if path.resolve().is_relative_to(Path(__file__).parents[2].resolve()):
        raise ValueError('Generated artifacts must be outside repository')
    return path


def prepare(base_dir=None, model='qwen3.5:9b'):
    runtime = requests.ollama_runtime_identity(model=model)
    value = packet(runtime, server_version(runtime['base_url']))
    directory = root(base_dir, value['input_fingerprint'])
    requests.ReceiptStore(directory).write_immutable('input.json', value)
    return dict(status='PREPARED_NO_EXECUTION', input=str(directory/'input.json'),
        input_fingerprint=value['input_fingerprint'], model=runtime['model'],
        server_version=value['server_version'], budget=value['budget'], generation_calls=0, paid_calls=0)


def run(input_path, base_dir=None, *, transport=None, progress=None):
    input_path = Path(input_path).resolve()
    frozen = strict_json(input_path.read_text())
    fingerprint = frozen['input_fingerprint']
    if digest({k:v for k,v in frozen.items() if k!='input_fingerprint'}) != fingerprint:
        raise ValueError('Conformance input changed')
    directory = root(base_dir, fingerprint)
    if input_path != (directory/'input.json').resolve():
        raise ValueError('Input must be under configured application base')
    runtime = requests.ollama_runtime_identity(model=frozen['runtime']['model'])
    if packet(runtime, server_version(runtime['base_url'])) != frozen:
        raise ValueError('Runtime or implementation changed after freeze; no substitution')
    store = requests.ReceiptStore(directory/'execution')
    result_path = directory/'result.json'
    if result_path.exists():
        return strict_json(result_path.read_text())
    rows = []
    halt = None
    for raw in frozen['requests']:
        spec = requests.RequestSpec(**raw)
        case = spec.source_identity['synthetic_case']
        if progress:
            progress('Synthetic schema check: '+case+'; '+runtime['model'])
        try:
            response = requests.execute(spec, requests.BudgetLedger(max_attempts=2, max_usd='0'),
                                        store, transport or requests.ollama_transport)
        except (ValueError, KeyError, TypeError, OSError, HTTPError) as error:
            halt = str(error)
            break
        try:
            validate_shape(strict_json(response['output']), SCHEMA)
            rows.append(dict(case=case, status='PASS', request_fingerprint=spec.fingerprint))
        except (ValueError, KeyError, TypeError) as error:
            rows.append(dict(case=case, status='FAIL(component)', reason=str(error),
                             request_fingerprint=spec.fingerprint))
    failed = any(row['status']=='FAIL(component)' for row in rows)
    status = 'FAIL(component)' if failed else ('INCONCLUSIVE' if halt else 'PASS')
    result = dict(status=status, input_fingerprint=fingerprint, model=runtime['model'],
        server_version=frozen['server_version'], checks=rows, halt=halt,
        attempts=len(store.attempts()), paid_calls=0, production_admission=False,
        limitation='A PASS covers these two synthetic requests only; it does not validate source extraction or prove general grammar enforcement.',
        next_step='Review runtime conformance before any separately authorized source trial.',
        results=str(result_path))
    markdown = '# Synthetic Ollama schema conformance\n\n'+status+'\n\n'
    markdown += '\n'.join('- '+r['case']+': '+r['status']+(' — '+r['reason'] if 'reason' in r else '') for r in rows)
    markdown += '\n\n'+result['limitation']+'\n\n'+result['next_step']+'\n'
    if halt:
        markdown += '\nHalt: '+halt+'\n'
    report_path = directory/'report.md'
    try:
        with report_path.open('x') as stream:
            stream.write(markdown)
    except FileExistsError:
        if report_path.read_text()!=markdown:
            raise ValueError('Immutable conformance report differs')
    requests.ReceiptStore(directory).write_immutable('result.json', result)
    return result
