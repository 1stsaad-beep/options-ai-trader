"""Opt-in, bounded GET-only contract metadata transport. No order capability."""
import http.client
import json
from urllib.parse import urlencode
from .provider_https import provider_connection

from .market_data import DataResponse, MarketDataError
from .option_eligibility import identity, QualificationError

TERMS_PREFIX = '/v2/options/contracts/'
SNAPSHOTS = '/v1beta1/options/snapshots'
MAX_RESPONSE_BYTES = 256 * 1024


def allowed_metadata_query(path, params):
    if not isinstance(path, str) or not isinstance(params, dict):
        return False
    try:
        if path.startswith(TERMS_PREFIX) and params == {}:
            identity(path[len(TERMS_PREFIX):])
            return True
        if path == SNAPSHOTS and set(params) == {'symbols', 'feed'} and params['feed'] == 'opra':
            values = params['symbols'].split(',')
            if not 1 <= len(values) <= 30 or len(set(values)) != len(values):
                return False
            for value in values:
                identity(value)
            return True
    except (QualificationError, TypeError, AttributeError):
        pass
    return False


class AlpacaMetadataTransport:
    """Fixed hosts and exact read routes; credentials are never sent elsewhere.

    Construction does no IO. The worker must separately opt into metadata reads.
    No redirects, SDK, environment host overrides, pagination or implicit retry.
    """
    def __init__(self, credentials):
        self._credentials = credentials

    def get(self, path, params):
        if not allowed_metadata_query(path, params):
            raise MarketDataError('DATA_ROUTE_FORBIDDEN')
        host = 'paper-api.alpaca.markets' if path.startswith(TERMS_PREFIX) else 'data.alpaca.markets'
        try:
            with provider_connection(host, timeout=4) as (connection, remaining):
                query = '?' + urlencode(params) if params else ''
                connection.request('GET', path + query, headers={
                    'APCA-API-KEY-ID': self._credentials.key_id,
                    'APCA-API-SECRET-KEY': self._credentials.secret_key,
                    'Accept': 'application/json',
                })
                remaining()
                response = connection.getresponse()
                remaining()
                headers = {k.lower(): v for k, v in response.getheaders()
                           if k.lower() in ('retry-after', 'x-ratelimit-remaining', 'x-ratelimit-reset')}
                if response.status != 200:
                    return DataResponse(response.status, headers, {})
                body = response.read(MAX_RESPONSE_BYTES + 1)
                remaining()
                if len(body) > MAX_RESPONSE_BYTES:
                    raise MarketDataError('DATA_RESPONSE_TOO_LARGE')
                def pairs(items):
                    result = {}
                    for key, value in items:
                        if key in result:
                            raise ValueError()
                        result[key] = value
                    return result
                def invalid(_):
                    raise ValueError()
                value = json.loads(body, object_pairs_hook=pairs, parse_constant=invalid)
                if not isinstance(value, dict):
                    raise ValueError()
                return DataResponse(200, headers, value)
        except (OSError, http.client.HTTPException):
            raise MarketDataError('DATA_CONNECTION_UNAVAILABLE') from None
        except (ValueError, UnicodeError, RecursionError):
            raise MarketDataError('INVALID_PROVIDER_RESPONSE') from None
