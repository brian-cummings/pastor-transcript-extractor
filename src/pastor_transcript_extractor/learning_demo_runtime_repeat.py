"""One source-only repeat after the demonstrated Ollama schema runtime repair."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from . import learning_demo_model_fit as fit
from . import ollama_conformance as conformance
from .evidence_requests import RequestSpec, ReceiptStore
from .pastor_evidence import EvidenceArtifactStore, digest

PRIOR = '392a9b6f0bb8ffc129a38a562fc8feb13469a80d4fc47ba1d1b85f1473ff9d78'
BEFORE = 'e79b24e5679796b7c197c4d2f012563b6d2a84b6df16ac14b97c151e85d809af'
AFTER = 'b0914cd50c1f93e469e783d48f1864fb9266d331ad03048bb0d963ad43eb0e6b'


def read_input(path, fingerprint):
    value = json.loads(path.read_text())
    if value['input_fingerprint'] != fingerprint or digest({k:v for k,v in value.items() if k!='input_fingerprint'}) != fingerprint:
        raise ValueError('Historical input identity changed')
    return value


def prepare(prior_input, base_dir=None, *, model='qwen3.5:9b', check_only=False):
    prior_input = Path(prior_input).resolve()
    if prior_input != (fit.directory(base_dir, PRIOR)/'input.json').resolve():
        raise ValueError('Runtime repeat requires the preserved six-window Qwen schema failure')
    prior = read_input(prior_input, PRIOR)
    result_path = prior_input.parent/'execution/results.json'
    result = json.loads(result_path.read_text())
    store = ReceiptStore(prior_input.parent/'execution')
    attempts = store.attempts()
    if (result['input_fingerprint'] != PRIOR or result['status'] != 'FAIL(component)'
        or result['halt'] is not None or result['diagnostics']['schema_valid_responses'] != 0
        or len(result['failures']) != 6 or any(row['component']!='reading_schema' for row in result['failures'])
        or len(attempts)!=6 or any(a['phase']!='source_reading' or a['reserved_usd']!='0' for a in attempts)):
        raise ValueError('Prior Qwen run is not the reviewed six-response schema failure')
    # Reuse the same original source recipe and all existing source/history checks.
    packet, _ = fit.prepare(prior['history']['prior_input'], base_dir, model=model, check_only=True)
    if any(packet[key] != prior[key] for key in ('windows','selection','contracts','proposal','source_refs','samples')):
        raise ValueError('Runtime repeat changed frozen source selection or contracts')
    runtime = packet['generation_runtime']
    if runtime != prior['generation_runtime']:
        raise ValueError('Runtime repeat requires unchanged Qwen model files and generation settings')
    files = [prior_input, result_path, *sorted(store.root.glob('attempts/*.json')),
             *sorted(store.root.glob('receipts/*.json')), *sorted(store.root.glob('wire-responses/*.json'))]
    current_version = conformance.server_version(runtime['base_url'])
    for fingerprint, expected_status, version in ((BEFORE,'FAIL(component)','0.31.1'),(AFTER,'PASS','0.40.11')):
        root = conformance.root(base_dir, fingerprint)
        frozen = read_input(root/'input.json', fingerprint)
        saved = json.loads((root/'result.json').read_text())
        checks = saved['checks']
        probe_store = ReceiptStore(root/'execution')
        if (frozen['server_version']!=version or saved['input_fingerprint']!=fingerprint
            or saved['status']!=expected_status or saved['server_version']!=version
            or saved['halt'] is not None or saved['paid_calls']!=0 or saved['attempts']!=2
            or len(probe_store.attempts())!=2
            or [row['case'] for row in checks]!=['cooperative','conflicting']
            or [row['status'] for row in checks]!=(['PASS','PASS'] if fingerprint==AFTER else ['PASS','FAIL(component)'])):
            raise ValueError('Required before/after runtime conformance evidence differs')
        if fingerprint==AFTER and (frozen['runtime']!=runtime or current_version!=version):
            raise ValueError('Current model/server differs from passing runtime check')
        files.extend([root/'input.json',root/'result.json',*sorted(probe_store.root.rglob('*.json'))])
    runtime = {**runtime, 'server_version': current_version}
    for row, old in zip(packet['source_requests'],prior['source_requests'],strict=True):
        request = replace(RequestSpec(**row['request']),runtime_identity=runtime)
        if row['case_id']!=old['case_id'] or request.body!=old['request']['body']:
            raise ValueError('Runtime repeat changed model, source prompt, schema or decoding')
        row.update(request=asdict(request),fingerprint=request.fingerprint,token_account=request.preflight())
    preserved = {str(path):fit.demo.file_hash(path) for path in files}
    packet.update(generation_runtime=runtime,
        runtime_repeat=dict(prior_input=str(prior_input),prior_fingerprint=PRIOR,
            before_conformance=BEFORE,after_conformance=AFTER,preserved_files=preserved,
            code_sha256=fit.demo.file_hash(Path(__file__)),
            conformance_code_sha256=fit.demo.file_hash(Path(conformance.__file__)),
            prior_diagnostics=result['diagnostics'],prior_source_attempts=21,prior_synthetic_attempts=4),
        authorization='Brian authorized one same-six-window source-only repeat after Ollama 0.40.11 conformance PASS')
    packet['history']={**packet['history'],'prior_attempts':25,'prior_local_attempts':25,
        'preserved_files':{**packet['history']['preserved_files'],**preserved}}
    packet['budget']={**packet['budget'],'prior_attempts':25,'prior_source_attempts':21,
        'prior_synthetic_attempts':4,'cumulative_maximum_attempts':31}
    packet.pop('input_fingerprint')
    packet['input_fingerprint']=digest(packet)
    out=fit.directory(base_dir,packet['input_fingerprint'])
    if not check_only:
        EvidenceArtifactStore(out).write_immutable('input.json',packet)
        command=f'pte analysis learning-demo model-fit run --base-dir {fit.build_paths(base_dir).root} --input {out / "input.json"} --experimental --approve-input {packet["input_fingerprint"]} --max-usd 0 --json'
        (out/'preparation.md').write_text('# Ollama runtime repair: bounded source-only repeat\n\n'
            'Same six windows, source messages, schemas, Qwen weights, thinking disabled and 8192 output cap. '
            'Only serving runtime and associated provenance change. Prior 21 source attempts and four synthetic '
            'conformance attempts are preserved; maximum six new local attempts, cumulative maximum 31, zero paid. '
            'No automatic retry, semantic verification, full-workflow advancement or production admission.\n\n'
            'Brian executes:\n\n```sh\n'+command+'\n```\n')
    return packet,out
