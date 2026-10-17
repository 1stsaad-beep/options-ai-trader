"""Provider values only: mathematical sanity is not entitlement or freshness."""
import math

FIELDS = ('delta', 'gamma', 'theta', 'vega', 'rho')


def provider_greeks(raw, right):
    if right not in ('C', 'P') or (raw is not None and not isinstance(raw, dict)):
        raise ValueError('Invalid provider Greeks')
    if raw is None:
        return None
    values = {key: raw.get(key) for key in FIELDS}
    for key, value in values.items():
        if value is None:
            continue
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('Invalid provider Greeks')
        if key == 'delta' and not ((0 <= value <= 1) if right == 'C' else (-1 <= value <= 0)):
            raise ValueError('Invalid provider delta')
        if key in ('gamma', 'vega') and value < 0:
            raise ValueError('Invalid long option sensitivity')
    return values


def quality(values):
    """Alpaca OptionsGreeks has no independent provider timestamp. Never copy
    the latest quote/trade time, HTTP receipt time or updated_since into it.
    Neither this shape check nor an indicative quote qualifies a contract.
    """
    status = 'MISSING' if values is None else 'PARTIAL' if any(values[k] is None for k in FIELDS) else 'VALUES_ONLY'
    return {'contract': 'option-greeks-quality-v1', 'valuesStatus': status,
        'providerTimestampAvailable': False, 'freshnessVerified': False, 'entryEligible': False,
        'reasons': ([] if status == 'VALUES_ONLY' else ['GREEKS_MISSING_VALUES']) +
            ['GREEKS_PROVIDER_TIME_UNAVAILABLE', 'CONTRACT_TERMS_UNAVAILABLE', 'INDICATIVE_OPTIONS_NOT_EXECUTABLE']}
