"""Explicit goal allowance; historical packets retain their original dollar guard."""
from decimal import Decimal
import json
from pathlib import Path
from .profile_support_validation import file_hash

VERSION='profile-support-additional-allowance-v1'


def ceiling(packet):
    ref=packet.get('acceptance_authorization')
    if ref is None:return Decimal('1')
    path=Path(ref['path'])
    if file_hash(path)!=ref['sha256']:raise ValueError('Acceptance allowance changed')
    authorization=json.loads(path.read_text());start=Decimal(authorization['starting_conservative_usd']);extra=Decimal(authorization['additional_usd'])
    if (authorization['version']!=VERSION or not start.is_finite() or start<0
        or not extra.is_finite() or not 0<extra<=2
        or authorization['spend_root']!=packet['budget']['spend_root']
        or file_hash(authorization['objective']['path'])!=authorization['objective']['sha256']):raise ValueError('Invalid goal allowance authorization')
    limit=start+extra
    if Decimal(packet['budget']['cumulative_ceiling_usd'])!=limit:raise ValueError('Goal ceiling differs from authorization')
    return limit
