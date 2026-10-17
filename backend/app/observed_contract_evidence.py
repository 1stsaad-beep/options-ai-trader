"""Immutable metadata observations, separate from versioned financial events.

Receipt time is never provider effective time. This journal grants neither
entry nor settlement; old lots cannot acquire historical terms from a new read.
"""
import json
import re
from contextlib import closing
from datetime import timedelta

from .observed_paper import canonical, digest
from .observed_paper_store import LedgerConflict, ZERO
from .observed_option_replay import iso
from .option_eligibility import identity, normalize_terms, qualify
from .option_greeks import provider_greeks
from .option_metadata import TERMS_PREFIX, SNAPSHOTS
from .paper_settlement import stamp

VERSION = 'observed-contract-evidence-v1'
REPORT = 'observed-contract-report-v1'
MAX_BYTES = 64 * 1024


def _raw(value, depth=0):
    if depth > 12:
        raise ValueError('Invalid contract evidence')
    if isinstance(value, dict):
        if len(value) > 64:
            raise ValueError('Invalid contract evidence')
        for key, child in value.items():
            if (not isinstance(key, str) or len(key) > 80 or
                    re.search(r'secret|password|token|credential|authorization|api.?key', key, re.I)):
                raise ValueError('Invalid contract evidence')
            _raw(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > 64:
            raise ValueError('Invalid contract evidence')
        for child in value:
            _raw(child, depth + 1)
    elif isinstance(value, str):
        if len(value) > 1024:
            raise ValueError('Invalid contract evidence')
    elif value is not None and type(value) not in (int, float, bool):
        raise ValueError('Invalid contract evidence')


def normalize(kind, symbol, raw, captured):
    identity(symbol); stamp(captured); _raw(raw)
    if len(canonical(raw).encode()) > MAX_BYTES:
        raise ValueError('Invalid contract evidence')
    if kind == 'terms':
        return normalize_terms(raw, symbol, captured)
    if kind == 'greeks' and isinstance(raw, dict):
        # Preserve the complete member in the private original, but a quote's
        # timestamp is explicitly NOT a timestamp of its Greek calculation.
        values = provider_greeks(raw.get('greeks'), identity(symbol)[2])
        return {'values': values, 'providerTimestamp': None, 'capturedAt': captured,
                'rawHash': digest(raw), 'feed': 'opra', 'freshnessVerified': False}
    raise ValueError('Invalid contract evidence')


def demand(state):
    return ({p['contract'] for p in state['positions'].values()} |
            {c for choices in state['config']['contracts'].values() for c in choices.values()})


def _verified(db, symbol, account=None):
    head = db.one('SELECT * FROM observed_contract_heads WHERE symbol=?', (symbol,))
    sequence = 0; previous = ZERO; latest = {}
    try:
        with closing(db.stream('SELECT * FROM observed_contract_evidence WHERE symbol=? ORDER BY sequence', (symbol,))) as rows:
            for row in rows:
                sequence += 1
                p = json.loads(row['payload'])
                if (row['sequence'] != sequence or row['previous_hash'] != previous or
                        row['digest'] != digest([symbol, sequence, previous, p]) or
                        len(row['payload'].encode()) > MAX_BYTES or row['payload'] != canonical(p) or
                        set(p) != {'contract', 'symbol', 'kind', 'capturedAt', 'source', 'endpoint', 'raw', 'bindings'} or
                        p['contract'] != VERSION or p['symbol'] != symbol or p['source'] != 'alpaca' or
                        p['endpoint'] != (TERMS_PREFIX + symbol if p['kind'] == 'terms' else SNAPSHOTS) or
                        not isinstance(p['bindings'], list) or not 1 <= len(p['bindings']) <= 100):
                    raise ValueError()
                seen = set()
                for binding in p['bindings']:
                    if (not isinstance(binding, dict) or set(binding) != {'account', 'version', 'eventHash'} or
                            binding['account'] in seen or type(binding['version']) is not int or binding['version'] < 0 or
                            not isinstance(binding['eventHash'], str) or not re.fullmatch('[a-f0-9]{64}', binding['eventHash'])):
                        raise ValueError()
                    seen.add(binding['account'])
                    anchor = db.one('SELECT digest FROM observed_paper_events WHERE account_id=? AND sequence=?',
                                    (binding['account'], binding['version']))
                    if anchor is None or anchor['digest'] != binding['eventHash']:
                        raise ValueError()
                normalized = normalize(p['kind'], symbol, p['raw'], p['capturedAt'])
                if account is None or any(b['account'] == account for b in p['bindings']):
                    latest[p['kind']] = {'sequence': sequence, 'eventHash': row['digest'],
                        'capturedAt': p['capturedAt'], 'bindings': p['bindings'], 'data': normalized}
                previous = row['digest']
        if (head is None and sequence != 0 or head is not None and
                (head['sequence'] != sequence or head['event_hash'] != previous)):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise LedgerConflict('Contract evidence requires review') from None
    return sequence, previous, latest


def append(store, lease, kind, symbol, raw, captured_at, accounts):
    """Internal worker boundary; no HTTP route can inject metadata or a price."""
    normalized = normalize(kind, symbol, raw, captured_at)
    if not isinstance(accounts, list) or not 1 <= len(accounts) <= 100 or len(set(accounts)) != len(accounts):
        raise ValueError('Explicit capture accounts required')
    with store.repo.transaction() as db:
        now = store.now()
        if not store._owns(db, lease, now):
            raise LedgerConflict('Worker lease lost')
        if not timedelta(0) <= now - stamp(captured_at) <= timedelta(seconds=8):
            raise ValueError('Invalid capture time')
        bindings = []
        for account in sorted(accounts):
            head, state = store._read(db, account, full=True)
            if state['source'] != 'alpaca' or symbol not in demand(state):
                raise ValueError('Contract outside observed account demand')
            bindings.append({'account': account, 'version': head['version'], 'eventHash': head['event_hash']})
        sequence, previous, latest = _verified(db, symbol)
        prior = latest.get(kind)
        if prior and stamp(captured_at) < stamp(prior['capturedAt']):
            raise ValueError('Regressed metadata capture time')
        payload = {'contract': VERSION, 'symbol': symbol, 'kind': kind, 'capturedAt': captured_at,
                   'source': 'alpaca', 'endpoint': TERMS_PREFIX + symbol if kind == 'terms' else SNAPSHOTS,
                   'raw': raw, 'bindings': bindings}
        body = canonical(payload)
        if len(body.encode()) > MAX_BYTES:
            raise ValueError('Invalid contract evidence')
        event_hash = digest([symbol, sequence + 1, previous, payload])
        db.execute('INSERT INTO observed_contract_evidence VALUES(?,?,?,?,?)',
                   (symbol, sequence + 1, body, event_hash, previous))
        db.execute('INSERT INTO observed_contract_heads VALUES(?,?,?) ON CONFLICT(symbol) DO UPDATE SET sequence=excluded.sequence,event_hash=excluded.event_hash',
                   (symbol, sequence + 1, event_hash))
    return {'sequence': sequence + 1, 'eventHash': event_hash, 'data': normalized}


def report(store, account):
    with store.repo.transaction() as db:
        head, state = store._read(db, account, full=True)
        now = store.now(); contracts = []
        for symbol in sorted(demand(state)):
            sequence, event_hash, latest = _verified(db, symbol, account)
            # An account receives only observations explicitly bound to its
            # original ledger. Reads cannot retroactively attach another origin.
            latest = {kind: value for kind, value in latest.items()
                      if any(b['account'] == account and b['version'] <= head['version'] for b in value['bindings'])}
            terms, greeks = latest.get('terms'), latest.get('greeks')
            if any(stamp(v['capturedAt']) > now for v in latest.values()):
                raise LedgerConflict('Contract evidence requires review')
            q = qualify(symbol, greeks['data']['values'] if greeks else None, now,
                        terms=terms['data'] if terms else None,
                        lot_terms_hash='' if any(p['contract'] == symbol for p in state['positions'].values()) else None)
            contracts.append({'symbol': symbol, 'throughSequence': sequence, 'throughHash': event_hash,
                              'terms': terms, 'greeks': greeks, 'qualification': q})
        result = {'contract': REPORT, 'account': account, 'source': state['source'],
                  'version': head['version'], 'eventHash': head['event_hash'], 'asOf': iso(now),
                  'externalOrder': False, 'entryEligible': False, 'settlementEligible': False,
                  'contracts': contracts}
        return result | {'reportHash': digest(result), 'reportPayload': canonical(result)}
