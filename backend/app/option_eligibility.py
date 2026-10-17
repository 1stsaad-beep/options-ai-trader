"""Versioned, read-only qualification of actual provider contract observations.

A receipt time is not a provider effective time. In particular Alpaca snapshot
Greeks have no independent timestamp: even valid standard terms cannot unlock
entry. Nothing in this module changes legacy lots or authorizes settlement.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from uuid import UUID

from .option_greeks import provider_greeks, FIELDS
from .paper_settlement import stamp

VERSION = 'option-eligibility-v1'
TERMS_VERSION = 'alpaca-contract-terms-v1'
PATTERN = re.compile(r'([A-Z][A-Z0-9.]{0,9})(\d{2})(\d{2})(\d{2})([CP])(\d{8})')
MAX_TERMS_AGE = timedelta(hours=24)


class QualificationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _require(ok, code):
    if not ok:
        raise QualificationError(code)


def _decimal(value):
    # Provider decimal strings are bounded BEFORE conversion; no exponents,
    # booleans, NaN, float approximation or silent cent rounding.
    _require(isinstance(value, str) and re.fullmatch(r'[0-9]{1,12}(?:\.[0-9]{1,8})?', value),
             'INVALID_CONTRACT_NUMBER')
    try:
        return Decimal(value)
    except InvalidOperation:
        raise QualificationError('INVALID_CONTRACT_NUMBER') from None


def _uuid(value):
    try:
        _require(isinstance(value, str) and len(value) == 36 and str(UUID(value)) == value.lower(),
                 'INVALID_CONTRACT_IDENTITY')
        return value.lower()
    except (ValueError, TypeError, AttributeError):
        raise QualificationError('INVALID_CONTRACT_IDENTITY') from None


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def identity(symbol):
    match = PATTERN.fullmatch(symbol) if isinstance(symbol, str) else None
    _require(match is not None, 'INVALID_CONTRACT_IDENTITY')
    try:
        expiry = date(2000 + int(match[2]), int(match[3]), int(match[4]))
    except ValueError:
        raise QualificationError('INVALID_CONTRACT_IDENTITY') from None
    strike = int(match[6])
    _require(strike > 0, 'INVALID_CONTRACT_IDENTITY')
    return match[1], expiry.isoformat(), match[5], strike


def _time(value):
    try:
        return stamp(value)
    except (ValueError, TypeError, OverflowError):
        raise QualificationError('INVALID_CONTRACT_TIME') from None


def normalize_terms(raw, symbol, captured_at):
    """Decode an actual GET contract response, keeping exact deliverable facts.

    This function is intentionally not an API for user supplied entry evidence.
    The immutable raw hash is audit linkage, not cryptographic provider proof.
    """
    root, expiry, right, strike = identity(symbol)
    _time(captured_at)
    _require(isinstance(raw, dict), 'INVALID_CONTRACT_TERMS')
    _require(raw.get('symbol') == symbol and raw.get('root_symbol') == root
             and raw.get('expiration_date') == expiry
             and raw.get('type') == ('call' if right == 'C' else 'put'), 'CONTRACT_IDENTITY_MISMATCH')
    underlying = raw.get('underlying_symbol')
    _require(isinstance(underlying, str) and re.fullmatch(r'[A-Z][A-Z0-9.]{0,9}', underlying),
             'INVALID_CONTRACT_IDENTITY')
    _require(_decimal(raw.get('strike_price')) * 1000 == strike, 'CONTRACT_STRIKE_MISMATCH')
    _require(raw.get('status') in ('active', 'inactive') and type(raw.get('tradable')) is bool
             and raw.get('style') in ('american', 'european'), 'INVALID_CONTRACT_TERMS')
    multiplier, size = _decimal(raw.get('multiplier')), _decimal(raw.get('size'))
    _require(multiplier > 0 and size > 0, 'INVALID_CONTRACT_NUMBER')
    asset = _uuid(raw.get('underlying_asset_id'))
    values = raw.get('deliverables')
    _require(isinstance(values, list) and 1 <= len(values) <= 16, 'CONTRACT_DELIVERABLES_UNAVAILABLE')
    deliverables = []
    for value in values:
        _require(isinstance(value, dict), 'INVALID_CONTRACT_DELIVERABLE')
        _require(value.get('type') in ('cash', 'equity') and type(value.get('delayed_settlement')) is bool
                 and value.get('settlement_type') in tuple('T+' + str(n) for n in range(6))
                 and value.get('settlement_method') in ('BTOB', 'CADF', 'CAFX', 'CCC'), 'INVALID_CONTRACT_DELIVERABLE')
        ticker = value.get('symbol')
        _require(isinstance(ticker, str) and re.fullmatch(r'[A-Z][A-Z0-9.]{0,9}', ticker),
                 'INVALID_CONTRACT_DELIVERABLE')
        # Older responses used null for delayed unknown amounts; newer ones use
        # "0". Neither is treated as a known zero settlement or standard terms.
        amount = value.get('amount')
        _require(amount is not None or value['delayed_settlement'], 'INVALID_CONTRACT_DELIVERABLE')
        if amount is not None:
            _decimal(amount)
        allocation = _decimal(value.get('allocation_percentage'))
        _require(allocation <= 100, 'INVALID_CONTRACT_DELIVERABLE')
        deliverables.append({'type': value['type'], 'symbol': ticker, 'amount': amount,
            'allocationPercentage': value['allocation_percentage'],
            'settlementType': value['settlement_type'], 'settlementMethod': value['settlement_method'],
            'delayedSettlement': value['delayed_settlement'],
            'assetId': _uuid(value.get('asset_id')) if value['type'] == 'equity' else None})
    terms = {'id': _uuid(raw.get('id')), 'symbol': symbol, 'root': root, 'underlying': underlying,
        'underlyingAssetId': asset, 'expiry': expiry, 'right': right, 'strikeMillis': strike,
        'status': raw['status'], 'tradable': raw['tradable'], 'style': raw['style'],
        'multiplier': raw['multiplier'], 'size': raw['size'], 'deliverables': deliverables}
    try:
        raw_hash = _hash(raw)
    except (ValueError, TypeError, OverflowError):
        raise QualificationError('INVALID_CONTRACT_TERMS') from None
    return {'contract': TERMS_VERSION, 'provider': 'alpaca', 'source': 'GET_OPTION_CONTRACT',
        'capturedAt': captured_at, 'providerEffectiveAt': None, 'rawHash': raw_hash,
        'termsHash': _hash(terms), 'terms': terms}


def qualify(symbol, greeks, now, *, terms=None, lot_terms_hash=None):
    """Alpaca-only assessment; independent Greek time remains unavailable.

    Historical lots require their original terms hash; current metadata is never
    backdated or applied to old receipts. All output codes are fixed/sanitized.
    """
    root, expiry, right, strike = identity(symbol)
    _require(isinstance(now, datetime) and now.tzinfo is not None and now.utcoffset() is not None,
             'INVALID_CONTRACT_TIME')
    reasons = []
    try:
        values = provider_greeks(greeks, right)
        greek_status = 'MISSING' if values is None else 'PARTIAL' if any(values[k] is None for k in FIELDS) else 'VALUES_ONLY'
    except ValueError:
        values, greek_status = None, 'INVALID'
    if greek_status != 'VALUES_ONLY': reasons.append('GREEKS_' + greek_status)
    reasons.append('GREEKS_PROVIDER_TIME_UNAVAILABLE')
    supported = False; terms_hash = None
    if terms is None:
        reasons.append('CONTRACT_TERMS_UNAVAILABLE')
    else:
        try:
            _require(isinstance(terms, dict) and set(terms) == {'contract', 'provider', 'source', 'capturedAt',
                'providerEffectiveAt', 'rawHash', 'termsHash', 'terms'} and terms['contract'] == TERMS_VERSION
                and terms['provider'] == 'alpaca' and terms['source'] == 'GET_OPTION_CONTRACT'
                and terms['providerEffectiveAt'] is None, 'CONTRACT_SOURCE_UNVERIFIED')
            _require(isinstance(terms['rawHash'], str) and re.fullmatch('[a-f0-9]{64}', terms['rawHash'])
                     and terms['termsHash'] == _hash(terms['terms']), 'CONTRACT_TERMS_HASH_MISMATCH')
            t = terms['terms']; terms_hash = terms['termsHash']
            _require(t['symbol'] == symbol and t['root'] == root and t['expiry'] == expiry
                     and t['right'] == right and t['strikeMillis'] == strike, 'CONTRACT_IDENTITY_MISMATCH')
            age = now - _time(terms['capturedAt'])
            _require(timedelta(0) <= age <= MAX_TERMS_AGE, 'CONTRACT_TERMS_STALE_OR_FUTURE')
            _require(t['status'] == 'active' and t['tradable'] is True, 'CONTRACT_NOT_TRADABLE')
            _require(date.fromisoformat(expiry) > now.astimezone(timezone.utc).date(), 'CONTRACT_EXPIRY_CLOSE_ONLY')
            d = t['deliverables']
            _require(not any(v['delayedSettlement'] is not False for v in d), 'CONTRACT_DELIVERY_DELAYED')
            supported = (root == t['underlying'] and t['style'] == 'american'
                and _decimal(t['multiplier']) == _decimal(t['size']) == 100 and strike % 10 == 0
                and len(d) == 1 and d[0]['type'] == 'equity' and d[0]['symbol'] == t['underlying']
                and d[0]['assetId'] == t['underlyingAssetId'] and _decimal(d[0]['amount']) == 100
                and _decimal(d[0]['allocationPercentage']) == 100 and d[0]['settlementType'] == 'T+1'
                and d[0]['settlementMethod'] in ('BTOB', 'CCC'))
            if not supported: reasons.append('ADJUSTED_OR_UNSUPPORTED_CONTRACT')
        except QualificationError as exc:
            reasons.append(exc.code); supported = False
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            reasons.append('INVALID_CONTRACT_TERMS'); supported = False
    if lot_terms_hash is not None:
        if not isinstance(lot_terms_hash, str) or not re.fullmatch('[a-f0-9]{64}', lot_terms_hash):
            reasons.append('LEGACY_LOT_TERMS_UNVERIFIED')
        elif lot_terms_hash != terms_hash:
            reasons.append('LOT_TERMS_CHANGED')
        # A matching structural hash is not historical effective-date proof.
        reasons.append('LOT_EFFECTIVE_TERMS_UNVERIFIED')
    return {'contract': VERSION, 'symbol': symbol, 'provider': 'alpaca', 'termsHash': terms_hash,
        'standardDeliverableObserved': supported, 'greeksStatus': greek_status,
        'greeksProviderTimestamp': None, 'greeksFreshnessVerified': False,
        'entryEligible': False, 'settlementEligible': False, 'externalOrder': False,
        'reasons': list(dict.fromkeys(reasons))}


class ContractTermsAdapter:
    """Replaceable GET-only boundary. Caller supplies the approved transport.

    No environment, credentials, SDK, account/order route, retry or implicit
    pagination. List responses are deliberately not accepted as a single term.
    """
    def __init__(self, transport, now):
        self.transport, self.now = transport, now

    def read(self, symbol):
        identity(symbol)
        at = self.now()
        _require(isinstance(at, datetime) and at.tzinfo is not None and at.utcoffset() is not None,
                 'INVALID_CONTRACT_TIME')
        try:
            response = self.transport.get('/v2/options/contracts/' + symbol, {})
        except Exception:
            raise QualificationError('CONTRACT_DATA_UNAVAILABLE') from None
        if response.status != 200:
            raise QualificationError('CONTRACT_DATA_UNAVAILABLE')
        captured_at = self.now()
        _require(isinstance(captured_at, datetime) and captured_at.tzinfo is not None
                 and captured_at.utcoffset() is not None and captured_at >= at, 'INVALID_CONTRACT_TIME')
        captured = captured_at.astimezone(timezone.utc).isoformat()
        return normalize_terms(response.body, symbol, captured)
