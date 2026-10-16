"""Offline-only ranking adapter. Importing this module never loads a model."""
from __future__ import annotations

from importlib.metadata import version
import hashlib
import math
import platform
from pathlib import Path

from pastor_transcript_extractor import collector_retrieval_design as design

LOCK = design.ROOT / 'docs/review-proposals/collector-retrieval-implementation-v1/artifact-lock-v1.json'


def verify_files(directory, lock):
    directory = Path(directory).resolve()
    for item in lock['files']:
        path = (directory / item['path']).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or path.stat().st_size != item['size']:
            raise ValueError('Missing/size-mismatched locked artifact: '+item['path'])
        if 'sha256' in item:
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''): digest.update(block)
            valid = digest.hexdigest() == item['sha256']
        else:
            value = path.read_bytes()
            valid = hashlib.sha1(b'blob '+str(len(value)).encode()+b'\0'+value).hexdigest() == item['git_blob_sha1']
        if not valid: raise ValueError('Locked artifact digest mismatch: '+item['path'])


def validate_tokens(ids, maximum=256):
    if len(ids)>maximum:
        return False
    if not ids: raise ValueError('Tokenizer returned an empty sequence')
    return True


def pool(hidden, mask):
    # Deliberately independent of the model loader so a synthetic test can verify
    # special/padding-mask arithmetic without executing a neural model.
    values = [row for row, bit in zip(hidden, mask) if bit]
    if not values or len(hidden)!=len(mask): raise ValueError('Invalid model token/mask dimensions')
    width = len(values[0])
    if any(len(row)!=width for row in hidden): raise ValueError('Inconsistent embedding dimension')
    mean = [math.fsum(float(row[i]) for row in values)/len(values) for i in range(width)]
    norm = math.sqrt(math.fsum(x*x for x in mean))
    if not math.isfinite(norm) or norm==0: raise ValueError('Nonfinite/zero embedding')
    return [x/norm for x in mean]


class LocalEncoder:
    """Use only after a separate source-controlled execution decision is checked."""
    def __init__(self, directory, *, execution_authorized=False):
        if execution_authorized is not True:
            raise ValueError('Model loading/execution is not authorized')
        lock = design.sealed(LOCK)
        if (platform.python_version()!=lock['runtime']['python']
                or platform.system()+'-'+platform.machine()!=lock['runtime']['platform']
                or platform.mac_ver()[0]!=lock['runtime']['macos']):
            raise ValueError('Locked runtime platform/Python differs')
        for name, expected in lock['runtime']['packages'].items():
            if version(name)!=expected: raise ValueError('Locked runtime version differs: '+name)
        verify_files(directory, lock)
        # All imports and deserialization are after authorization and byte checks.
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.np = np
        self.tokenizer = Tokenizer.from_file(str(Path(directory)/'tokenizer.json'))
        self.tokenizer.no_truncation(); self.tokenizer.no_padding()
        opts = ort.SessionOptions(); opts.intra_op_num_threads=1; opts.inter_op_num_threads=1
        opts.graph_optimization_level=ort.GraphOptimizationLevel.ORT_DISABLE_ALL
        opts.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(str(Path(directory)/'onnx/model.onnx'), sess_options=opts, providers=['CPUExecutionProvider'])
        self.tokens = 0; self.encoded = 0; self.deferred = 0

    def encode(self, text):
        value = self.tokenizer.encode(text)
        if not validate_tokens(value.ids):
            self.deferred += 1
            return None
        self.tokens += len(value.ids); self.encoded += 1
        arrays = dict(input_ids=[value.ids], attention_mask=[value.attention_mask], token_type_ids=[value.type_ids])
        feed = {item.name:self.np.asarray(arrays[item.name], dtype=self.np.int64) for item in self.session.get_inputs()}
        result = self.session.run(None, feed)[0]
        if result.ndim!=3 or result.shape[0]!=1 or result.shape[1]!=len(value.ids) or result.shape[2]!=384:
            raise ValueError('Unexpected locked model output shape')
        return pool(result[0].tolist(), value.attention_mask)
