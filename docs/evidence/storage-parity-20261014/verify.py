"""Offline verification of original 6a71afff artifacts; no market/network access."""
import hashlib
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

root = Path(__file__).parent
index = json.loads((root / 'index.json').read_text())
data = (root / 'evidence.zip').read_bytes()
assert hashlib.sha256(data).hexdigest() == index['bundle_sha256']
archives = {}
with zipfile.ZipFile(io.BytesIO(data)) as bundle:
    assert bundle.testzip() is None
    for artifact in index['artifacts']:
        data = bundle.read(artifact['path'])
        assert len(data) == artifact['bytes']
        assert hashlib.sha256(data).hexdigest() == artifact['sha256']
        z = zipfile.ZipFile(io.BytesIO(data))
        assert z.testzip() is None
        archives[artifact['path'].split('-')[0]] = z

def machine(key, name):
    rows = [json.loads(line) for line in archives[key].read(name).decode().splitlines() if line.startswith('{')]
    assert rows[-1]['type'] == 'done' and rows[-1]['success'] is True
    done = [r for r in rows if r.get('type') == 'testDone' and not r.get('hidden', False)]
    assert all(r['result'] == 'success' and not r.get('skipped', False) for r in done)
    return len(done)

assert machine('direct', 'mobile/direct-flutter-tests.json') == 674
assert machine('chart', 'chart-tests.json') == 23
assert machine('chart', 'golden-tests.json') == 6
jvm = 0
for name in archives['direct'].namelist():
    if name.endswith('.xml'):
        suite = ET.fromstring(archives['direct'].read(name))
        assert all(int(suite.get(k, '0')) == 0 for k in ('errors', 'failures', 'skipped'))
        jvm += int(suite.get('tests'))
assert jvm == 41
suites = ET.fromstring(archives['backend'].read('test-results.xml')).findall('testsuite')
assert sum(int(s.get('tests')) for s in suites) == 1192
assert all(int(s.get(k, '0')) == 0 for s in suites for k in ('errors', 'failures', 'skipped'))
for name, count in [('postgres-v1-results.json', 22), ('market-data-journal-postgres.json', 6),
                    ('market-runtime-postgres.json', 8), ('paper-settlement-postgres.json', 5),
                    ('postgres-backup-restore.json', 17)]:
    r = json.loads(archives['backend'].read(name))
    assert r['checks_passed'] == count and r['checks_failed'] == 0 and r['status'] == 'passed'
compose = json.loads(archives['compose'].read('compose-smoke.json'))
assert compose['status'] == 'passed' and len(compose['checks']) == 17
security = json.loads(archives['security'].read('secret-scan.json'))
assert security['finding_count'] == 0
python = json.loads(archives['security'].read('dependency-audit.json'))['dependencies']
assert len(python) == 24 and not any(p['vulns'] for p in python)
pub = json.loads(archives['security'].read('dart-dependency-audit.json'))
assert pub['packages_checked'] == 44 and pub['status'] == 'no_known_advisories'
print(json.dumps({'status': 'verified', 'source': index['source_sha'], 'results': index['results'],
                  'visual_acceptance': False, 'independent_review': False}, indent=2))
