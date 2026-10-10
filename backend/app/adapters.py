"""V1 adapter boundaries. External integrations intentionally have no network code."""
from typing import Protocol
from .core import LiveTradingDisabled

class BrokerAdapter(Protocol):
    def capabilities(self) -> dict: ...

MOCK_SYMBOLS = frozenset({'NVDA','AAPL','TSLA','SPY','QQQ','MSFT','AMD'})

class MockBrokerAdapter:
    def verify_symbol(self, symbol):
        return {'symbol':symbol,'verified':symbol in MOCK_SYMBOLS,'market_data_entitled':symbol in MOCK_SYMBOLS,'source':'synthetic_fixture','real_broker_verification':False}

    def capabilities(self):
        return {'broker':'mock','paper':True,'live':False,'market_data':'synthetic_fixture'}

class IBKRAdapter:
    def capabilities(self):
        return {'broker':'ibkr','paper':False,'live':False,'status':'disabled_scaffold'}
    def connect(self, *args, **kwargs):
        raise LiveTradingDisabled('IBKR integration is disabled; no account connection is allowed in V1 demo')
    def submit(self, *args, **kwargs):
        raise LiveTradingDisabled('IBKR order submission is disabled')

class GenericAnalysisAdapter:
    """Future read-only analysis boundary. No external I/O is implemented.

    Enabling an external source requires a later implementation and review;
    configuration flags or assigning attributes cannot authorize execution.
    """
    @property
    def enabled(self):
        return False

    def capabilities(self):
        return {'enabled': False, 'read_only': True, 'execution_authority': False,
                'source': 'external_disabled'}

    def analyze(self, *args, **kwargs):
        raise PermissionError('Generic analysis integration is disabled; no API calls are implemented')
