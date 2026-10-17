"""Fixed read-only HTTPS probe for an explicitly configured health exporter."""
from datetime import datetime, timedelta, timezone
import http.client
import json
import re
import uuid
from urllib.parse import urlsplit

from .alert_webhook import strict_json
from .health_exporter import PATH, VERSION, COMPONENTS, validate_token
from .observed_option_replay import iso
from .observed_paper_alerts import CODES
from .observed_paper_status import DIAGNOSTICS
from .paper_settlement import stamp
from .provider_https import Resolver, pinned_connection
from .runtime_health import heartbeat_valid

DEADLINE_SECONDS = 5
MAX_BYTES = 8192


def validate_response(value, nonce, started, ended, status):
    if (not isinstance(value, dict) or set(value) != {'contract','nonce','serverTime',
            'externalOrder','executionAllowed','newEntryAllowed','databaseReadable','components',
            'workerDiagnostic','workerAlerts','dataAccess'}
            or value['contract'] != VERSION or value['nonce'] != nonce
            or any(value[k] is not False for k in ('externalOrder','executionAllowed','newEntryAllowed'))
            or type(value['databaseReadable']) is not bool or status != (200 if value['databaseReadable'] else 503)
            or not started <= ended or not started - timedelta(seconds=5) <= stamp(value['serverTime']) <= ended + timedelta(seconds=5)
            or not isinstance(value['components'], dict) or set(value['components']) != set(COMPONENTS)):
        raise ValueError('Invalid probe response')
    for key, name in COMPONENTS.items():
        component = value['components'][key]
        if not isinstance(component, dict) or set(component) != {'fresh','state'} or type(component['fresh']) is not bool:
            raise ValueError('Invalid component state')
        if component['fresh']:
            if not value['databaseReadable'] or not heartbeat_valid(
                    {'updated_at': iso(ended), 'payload': json.dumps({'state':component['state']})}, name, ended):
                raise ValueError('Invalid fresh component')
        elif component['state'] != ('UNAVAILABLE' if value['databaseReadable'] else 'UNKNOWN'):
            raise ValueError('Invalid unavailable component')
    diagnostic, alerts, access = value['workerDiagnostic'], value['workerAlerts'], value['dataAccess']
    if (diagnostic is not None and (not isinstance(diagnostic,str) or diagnostic not in DIAGNOSTICS
                                  or not value['components']['worker']['fresh'])
            or not isinstance(alerts, list) or any(not isinstance(v,str) or v not in CODES for v in alerts)
            or len(alerts) != len(set(alerts))
            or not isinstance(access, dict) or set(access) != {'verified','authBlocked','backoff'}
            or type(access['verified']) is not bool):
        raise ValueError('Invalid operational diagnostic')
    if access['verified']:
        if any(type(access[k]) is not bool for k in ('authBlocked','backoff')):
            raise ValueError('Invalid provider state')
        # A fresh worker diagnostic can retain the last auth failure briefly
        # after an explicit provider-latch reset; it is not the current latch.
        if (access['authBlocked'] and 'DATA_AUTH_OR_ENTITLEMENT_DENIED' not in alerts
                or access['backoff'] != ('DATA_BACKOFF' in alerts)):
            raise ValueError('Inconsistent provider state')
    elif access['authBlocked'] is not None or access['backoff'] is not None:
        raise ValueError('Unverified provider state')
    if not value['databaseReadable'] and (diagnostic is not None or alerts or access['verified']):
        raise ValueError('Unobserved database state')
    if value['databaseReadable'] and (not value['components']['worker']['fresh']) != ('WORKER_UNAVAILABLE' in alerts):
        raise ValueError('Inconsistent worker health')
    return value


class HealthProbe:
    def __init__(self, endpoint, token, *, now=None):
        try:
            url = urlsplit(endpoint)
            if (url.scheme != 'https' or not url.hostname or url.port not in (None,443)
                    or url.username is not None or url.password is not None or url.path != PATH
                    or url.query or url.fragment
                    or not re.fullmatch(r'[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?', url.hostname)
                    or url.hostname.endswith(('alpaca.markets','interactivebrokers.com','ibkr.com'))):
                raise ValueError()
            self._host = url.hostname
            self._token = validate_token(token)
        except (ValueError,TypeError,AttributeError):
            raise ValueError('Invalid health probe configuration') from None
        self._resolver = Resolver()
        self.now = now or (lambda: datetime.now(timezone.utc))

    def read(self):
        started = self.now(); nonce = uuid.uuid4().hex
        outcome = 'PROBE_UNAVAILABLE'; remote = None
        try:
            with pinned_connection(self._host, self._resolver, timeout=DEADLINE_SECONDS) as (connection, remaining):
                connection.request('GET', PATH, headers={'Authorization': 'Bearer ' + self._token,
                    'Accept': 'application/json', 'X-OAT-Probe': nonce, 'Cache-Control': 'no-cache'})
                remaining()
                response = connection.getresponse(); remaining()
                if response.status in (401,403):
                    outcome = 'PROBE_AUTH_DENIED'
                elif response.status == 429:
                    outcome = 'PROBE_RATE_LIMITED'
                elif response.status not in (200,503):
                    outcome = 'PROBE_INVALID_RESPONSE'
                else:
                    raw = response.read(MAX_BYTES + 1); remaining()
                    if len(raw) > MAX_BYTES:
                        raise ValueError()
                    value = strict_json(raw.decode('utf-8'))
                    remote = validate_response(value, nonce, started, self.now(), response.status)
                    outcome = 'OBSERVED'
        except (OSError, http.client.HTTPException):
            outcome = 'PROBE_UNAVAILABLE'; remote = None
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError, AttributeError):
            outcome = 'PROBE_INVALID_RESPONSE'; remote = None
        return {'contract': 'external-health-observation-v1', 'observedAt': iso(self.now()),
                'state': outcome, 'remote': remote, 'externalOrder': False}
