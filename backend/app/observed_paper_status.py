"""Sanitized, read-only operational diagnostics; never readiness to trade."""
from datetime import timedelta
import json

from .observed_option_replay import iso
from .paper_settlement import stamp
from .runtime_health import heartbeat_valid

DIAGNOSTICS = frozenset({'DATA_AUTH_OR_ENTITLEMENT_DENIED', 'DATA_RATE_LIMITED',
    'INVALID_PROVIDER_RESPONSE', 'DATA_UNAVAILABLE', 'OBSERVED_DEMAND_LIMIT',
    'WORKER_LEASE_LOST', 'DATA_ROUTE_FORBIDDEN'})


def safe_diagnostic(code):
    return code if isinstance(code, str) and code in DIAGNOSTICS else 'DATA_UNAVAILABLE'


def status(store):
    now = store.now()
    with store.repo.transaction() as db:
        row = db.one("SELECT * FROM runtime_health WHERE name='observed_paper'")
        budget = db.one("SELECT payload FROM observed_paper_data_state WHERE name='budget'")
    fresh = heartbeat_valid(row, 'observed_paper', now)
    payload = json.loads(row['payload']) if fresh else {}
    state = payload.get('state', 'WORKER_UNAVAILABLE')
    diagnostic = safe_diagnostic(payload['diagnosticCode']) if fresh and payload.get('diagnosticCode') is not None else None
    access = {'status': 'NOT_OBSERVED', 'authBlocked': None, 'retryAt': None, 'chargedRequestsLastMinute': None}
    alerts = []
    if not fresh: alerts.append('WORKER_UNAVAILABLE')
    if state in ('LEDGER_BLOCKED', 'PARTIALLY_BLOCKED'): alerts.append('LEDGER_REVIEW_REQUIRED')
    if diagnostic: alerts.append(diagnostic)
    if budget:
        try:
            value = json.loads(budget['payload'])
            if (not isinstance(value, dict) or set(value) != {'calls','authBlocked','retryAt','failures'}
                    or not isinstance(value['calls'], list) or len(value['calls']) > 30
                    or type(value['authBlocked']) is not bool or type(value['failures']) is not int
                    or not 0 <= value['failures'] <= 8):
                raise ValueError()
            calls = [stamp(t) for t in value['calls']]
            retry = None if value['retryAt'] is None else stamp(value['retryAt'])
            access = {'status': 'OBSERVED', 'authBlocked': value['authBlocked'],
                'retryAt': iso(retry) if retry else None,
                'chargedRequestsLastMinute': sum(now-t < timedelta(seconds=60) for t in calls)}
            if value['authBlocked']: alerts.append('DATA_AUTH_OR_ENTITLEMENT_DENIED')
            if retry and retry > now: alerts.append('DATA_BACKOFF')
        except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
            access['status'] = 'UNVERIFIED'; alerts.append('DATA_STATE_REVIEW_REQUIRED')
    def count(key):
        value = payload.get(key, 0)
        return value if type(value) is int and 0 <= value <= 100 else 0
    return {'mode': 'observed_market_virtual', 'externalOrder': False, 'serverTime': iso(now),
        'heartbeatFresh': fresh, 'state': state, 'newMarketEntryAllowed': False,
        'entryBlockReason': 'CONTRACT_ELIGIBILITY_UNVERIFIED', 'processed': count('processed'), 'blocked': count('blocked'),
        'diagnosticCode': diagnostic, 'dataAccess': access, 'alerts': list(dict.fromkeys(alerts)),
        'alertScope': 'CURRENT_STATE_READ_ONLY_NO_PUSH_DELIVERY'}
