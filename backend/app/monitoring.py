"""Read-only readiness; observation never reconciles an account implicitly."""
import json
from datetime import datetime


def readiness(service):
    with service.repo.transaction() as db:
        db.one('SELECT 1 AS available')
        versions = [r['version'] for r in db.all('SELECT version FROM schema_migrations ORDER BY version')]
        heartbeat = db.one('SELECT * FROM runtime_health WHERE name=?', ('worker',))
        accounts = service.list_accounts_in(db)
    worker = {'present': heartbeat is not None, 'fresh': False, 'status': 'NOT_OBSERVED'}
    if heartbeat:
        try:
            age = (service.now() - datetime.fromisoformat(heartbeat['updated_at'])).total_seconds()
            payload = json.loads(heartbeat['payload'])
            worker = {'present': True, 'fresh': 0 <= age <= 120,
                      'age_seconds': age, 'status': payload['status']}
        except (ValueError, TypeError, KeyError):
            worker['status'] = 'INVALID_HEARTBEAT'
    states = [{'account_id': a['id'], 'automation_enabled': a['config']['automation_enabled'],
               **service.status(a['id'])} for a in accounts]
    opted_in = [a for a in states if a['automation_enabled']]
    return {'api_ready': True, 'database_ready': True, 'schema_versions': versions,
            'mode': 'synthetic_mock', 'live_enabled': False, 'worker': worker,
            'trading_ready': bool(opted_in) and worker['fresh'] and worker['status'] == 'OK'
            and all(a['new_entries_allowed'] for a in opted_in), 'accounts': states,
            'authorization_scope': 'single_personal_owner',
            'note': 'Readiness is not evidence of real broker connectivity or profitability'}
