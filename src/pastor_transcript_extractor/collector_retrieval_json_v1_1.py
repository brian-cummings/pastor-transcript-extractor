"""Prospective JSON-native seals; historical typed preimages remain untouched."""
from __future__ import annotations
import hashlib
import json
import math


def native(value):
    """Normalize only JSON-representable values, rejecting lossy key collisions."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if type(key) not in (str, int):
                raise ValueError('Only string/integer JSON object keys are allowed')
            name = str(key)
            if name in out:
                raise ValueError('JSON key collision')
            out[name] = native(item)
        return out
    if isinstance(value, (tuple, list)):
        return [native(v) for v in value]
    if value is None or type(value) in (str, bool, int): return value
    if type(value) is float and math.isfinite(value): return value
    raise ValueError('Non-JSON or nonfinite seal value')


def seal(value):
    body = native({k:v for k,v in value.items() if k != 'content_fingerprint'})
    # Seal exactly the JSON-native representation that consumers will reread.
    body = json.loads(json.dumps(body, ensure_ascii=False, allow_nan=False))
    digest = hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    return dict(body,content_fingerprint=digest)
