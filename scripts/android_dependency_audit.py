"""Audit resolved Android runtime Maven packages against OSV; no application credentials."""
import json
from pathlib import Path
import re
import sys
import urllib.request

text = Path(sys.argv[1]).read_text()
packages = set()
for line in text.splitlines():
    if '---' not in line:
        continue
    match = re.search(r'([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+):([A-Za-z0-9_.+\-]+)(?: -> ([A-Za-z0-9_.+\-]+))?', line)
    if match:
        group, artifact, version, resolved = match.groups()
        packages.add((f'{group}:{artifact}', resolved or version))
if not packages or not any(p[0] == 'com.squareup.okhttp3:okhttp' for p in packages):
    raise SystemExit('Missing resolved native dependencies; refusing empty audit')
ordered = sorted(packages)
queries = [{'package': {'ecosystem': 'Maven', 'name': name}, 'version': version} for name, version in ordered]
request = urllib.request.Request('https://api.osv.dev/v1/querybatch', data=json.dumps({'queries': queries}).encode(), headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(request, timeout=60) as response:
    data = json.load(response)
if len(data.get('results', [])) != len(ordered):
    raise SystemExit('Incomplete OSV response')
findings = [{'package': name, 'version': version, 'vulns': result.get('vulns', [])} for (name, version), result in zip(ordered, data['results'])]
print(json.dumps({'source': 'OSV Maven querybatch', 'packages': findings, 'limitations': 'Known advisories at query time only; not a security certification'}, indent=2))
if any(item['vulns'] for item in findings):
    raise SystemExit('Known Android runtime advisory found; review before delivery')
