"""Query public OSV advisories for exact hosted Pub lockfile versions.

Only public package names/versions are sent. No source, accounts or credentials.
Requires PyYAML 6.0.3 for the development tool, not the application runtime.
Reference: https://google.github.io/osv.dev/post-v1-querybatch/
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


def packages(lock):
    if not isinstance(lock, dict) or not isinstance(lock.get('packages'), dict):
        raise ValueError('Invalid Pub lockfile')
    hosted, skipped = [], []
    for name, row in sorted(lock['packages'].items()):
        if row.get('source') == 'sdk':
            skipped.append({'name': name, 'reason': 'Flutter SDK is not a hosted Pub package'})
        elif row.get('source') == 'hosted' and isinstance(row.get('version'), str):
            hosted.append({'name': name, 'version': row['version']})
        else:
            raise ValueError('Unsupported dependency source must be reviewed')
    if not hosted:
        raise ValueError('No hosted dependencies to audit')
    return hosted, skipped


def query(queries):
    request = Request('https://api.osv.dev/v1/querybatch',
                      data=json.dumps({'queries': queries}).encode(),
                      headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=30) as response:
        if response.geturl() != request.full_url:
            raise ValueError('Unexpected advisory service redirect')
        return json.load(response)


def audit(lock, fetch=query):
    deps, skipped = packages(lock)
    results = []
    for offset in range(0, len(deps), 100):
        batch = deps[offset:offset+100]
        queries = [{'package': {'name': p['name'], 'ecosystem': 'Pub'}, 'version': p['version']} for p in batch]
        response = fetch(queries)
        rows = response.get('results')
        if not isinstance(rows, list) or len(rows) != len(batch):
            raise ValueError('Incomplete advisory response')
        for package, row in zip(batch, rows):
            if not isinstance(row, dict) or row.get('next_page_token') or row.get('error'):
                raise ValueError('Incomplete/paginated advisory result; manual review required')
            vulnerabilities = row.get('vulns', [])
            if not isinstance(vulnerabilities, list) or any(not isinstance(v, dict) or not isinstance(v.get('id'), str) for v in vulnerabilities):
                raise ValueError('Malformed advisory records')
            results.append({**package, 'advisories': [v['id'] for v in vulnerabilities]})
    return {'status': 'findings' if any(p['advisories'] for p in results) else 'no_known_advisories',
            'checked_at': datetime.now(timezone.utc).isoformat(), 'source': 'OSV public API',
            'ecosystem': 'Pub', 'packages_checked': len(results), 'dependencies': results,
            'skipped': skipped, 'limitation': 'No coverage guarantee; Flutter SDK and native OS dependencies are outside this query'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lockfile', type=Path, default=Path('mobile/pubspec.lock'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        import yaml
        result = audit(yaml.safe_load(args.lockfile.read_text()))
        code = 1 if result['status'] == 'findings' else 0
    except Exception:
        result, code = {'status': 'not_completed', 'detail': 'Could not complete exact-version advisory query; no clean result is claimed'}, 2
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('status', 'packages_checked') if k in result}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
