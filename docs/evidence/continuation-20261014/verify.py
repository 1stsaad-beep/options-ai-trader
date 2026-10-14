"""Offline evidence integrity check; no network, credentials or trading actions.

Digest/CRC checks do not authenticate the source independently or certify design,
provider entitlement, security, APK signing or completeness of V1.0.
"""
import hashlib
import io
import json
from pathlib import Path
import zipfile

root=Path(__file__).resolve().parent
index=json.loads((root/'index.json').read_text())
raw=(root/index['bundle']['file']).read_bytes()
assert hashlib.sha256(raw).hexdigest()==index['bundle']['sha256']
assert len(raw)==index['bundle']['bytes']
bundle=zipfile.ZipFile(io.BytesIO(raw));assert bundle.testzip() is None
internal=json.loads(bundle.read('verification.json'))
assert internal=={k:v for k,v in index.items() if k!='bundle'}
for artifact in index['artifacts']:
    data=bundle.read(artifact['file'])
    assert len(data)==artifact['bytes']
    assert hashlib.sha256(data).hexdigest()==artifact['sha256']
    nested=zipfile.ZipFile(io.BytesIO(data));assert nested.testzip() is None
receipts=json.loads(bundle.read('workflow-receipts.json'))
assert all(r['head_sha']==index['tested_source'] and r['status']=='completed' and
           r['conclusion'] in ('success','skipped') for r in receipts['runs'])
assert all(j['conclusion']=='success' for run in receipts['jobs'] for j in run['jobs'])
print(json.dumps({'tested_source':index['tested_source'],'original_artifacts_verified':len(index['artifacts']),
                  'bundle_sha256':index['bundle']['sha256'],'integrity':'passed',
                  'independent_review':False,'new_apk_produced':False},indent=2))
