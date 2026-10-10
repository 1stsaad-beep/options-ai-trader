"""Typed broker boundaries: no external transport and no second Mock order ledger.

TradingService remains the sole owner of durable mock accounts and execution.
Qualification schemas express data requirements, not permission to trade.
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import re
from typing import Literal, Protocol, runtime_checkable
from .core import LiveTradingDisabled

Source = Literal['synthetic_fixture', 'ibkr']
Side = Literal['BUY_TO_OPEN', 'SELL_TO_CLOSE']
OrderStatus = Literal['ACCEPTED', 'PARTIAL', 'FILLED', 'CANCELLED', 'REJECTED', 'UNKNOWN']


class BrokerOperationUnsupported(RuntimeError):
    """Operation is unavailable; never fabricate a success receipt."""


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 128 or any(ord(c) < 32 for c in value):
        raise ValueError(f'Invalid {name}')


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')


def _timestamp(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Timestamp must include a timezone')


def _source(value):
    if value not in ('synthetic_fixture', 'ibkr'):
        raise ValueError('Unknown data source')


@dataclass(frozen=True)
class AccountIdentity:
    application_account_id: str
    broker_account_id: str
    connection_id: str

    def __post_init__(self):
        for name in ('application_account_id', 'broker_account_id', 'connection_id'):
            _text(getattr(self, name), name)


@dataclass(frozen=True)
class AccountSnapshot:
    identity: AccountIdentity
    currency: str
    net_liquidation_cents: int
    buying_power_cents: int
    cash_cents: int
    observed_at: datetime
    complete: bool
    source: Source

    def __post_init__(self):
        if not isinstance(self.identity, AccountIdentity) or self.currency != 'USD':
            raise ValueError('V1 snapshots require an explicit USD account identity')
        for name in ('net_liquidation_cents', 'buying_power_cents', 'cash_cents'):
            _integer(getattr(self, name), name)
        if type(self.complete) is not bool:
            raise ValueError('Snapshot completeness must be boolean')
        _timestamp(self.observed_at)
        _source(self.source)

    def fresh_at(self, now: datetime, max_age_seconds: int = 120) -> bool:
        _timestamp(now)
        _integer(max_age_seconds, 'max_age_seconds', 1)
        return self.complete and 0 <= (now - self.observed_at).total_seconds() <= max_age_seconds


@dataclass(frozen=True)
class InstrumentRequest:
    symbol: str
    security_type: Literal['STK', 'OPT'] = 'STK'
    exchange: str = 'SMART'
    currency: str = 'USD'
    right: Literal['CALL', 'PUT'] | None = None
    expiry: date | None = None
    strike_cents: int | None = None
    multiplier: int | None = None

    def __post_init__(self):
        if not isinstance(self.symbol, str) or not re.fullmatch(r'[A-Z][A-Z0-9.]{0,9}', self.symbol):
            raise ValueError('Invalid normalized symbol')
        if self.security_type not in ('STK', 'OPT') or self.currency != 'USD':
            raise ValueError('V1 supports USD stocks and single-leg options only')
        if not isinstance(self.exchange, str) or not re.fullmatch(r'[A-Z][A-Z0-9]{0,19}', self.exchange):
            raise ValueError('Invalid exchange')
        if self.security_type == 'STK':
            if any(value is not None for value in (self.right, self.expiry, self.strike_cents, self.multiplier)):
                raise ValueError('Stock qualification cannot include option fields')
        else:
            if self.right not in ('CALL', 'PUT') or type(self.expiry) is not date:
                raise ValueError('Option qualification requires right and expiry')
            _integer(self.strike_cents, 'strike_cents', 1)
            _integer(self.multiplier, 'multiplier', 1)


@dataclass(frozen=True)
class QualifiedInstrument:
    request: InstrumentRequest
    contract_id: str
    underlying_contract_id: str
    primary_exchange: str
    trading_class: str
    market_data_entitled: bool
    options_chain_available: bool
    source: Source
    real_broker_verification: bool

    def __post_init__(self):
        if not isinstance(self.request, InstrumentRequest):
            raise ValueError('Qualification requires validated instrument fields')
        for name in ('contract_id', 'underlying_contract_id', 'primary_exchange', 'trading_class'):
            _text(getattr(self, name), name)
        for name in ('market_data_entitled', 'options_chain_available', 'real_broker_verification'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'{name} must be boolean')
        _source(self.source)
        mock_ids = self.contract_id.startswith('mock:') and self.underlying_contract_id.startswith('mock:')
        if self.source == 'synthetic_fixture' and (self.real_broker_verification or not mock_ids):
            raise ValueError('Synthetic instruments cannot claim real broker verification')
        if self.source == 'ibkr' and (not self.real_broker_verification or self.contract_id.startswith('mock:') or self.underlying_contract_id.startswith('mock:') or self.primary_exchange == 'MOCK'):
            raise ValueError('IBKR qualification requires actual broker verification')


@dataclass(frozen=True)
class OptionQuote:
    instrument: QualifiedInstrument
    bid_cents: int
    ask_cents: int
    bid_size: int
    ask_size: int
    volume: int
    open_interest: int
    delta: Decimal
    gamma: Decimal
    theta: Decimal
    vega: Decimal
    implied_volatility: Decimal
    observed_at: datetime
    data_type: Literal['synthetic', 'live', 'delayed', 'frozen']

    def __post_init__(self):
        if not isinstance(self.instrument, QualifiedInstrument) or self.instrument.request.security_type != 'OPT':
            raise ValueError('An option quote requires a qualified option')
        for name in ('bid_cents', 'ask_cents', 'bid_size', 'ask_size', 'volume', 'open_interest'):
            _integer(getattr(self, name), name)
        if self.ask_cents <= 0 or self.bid_cents > self.ask_cents:
            raise ValueError('Invalid bid/ask market')
        for name in ('delta', 'gamma', 'theta', 'vega', 'implied_volatility'):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f'{name} must be a finite Decimal')
        if not Decimal('-1') <= self.delta <= Decimal('1') or min(self.gamma, self.vega, self.implied_volatility) < 0:
            raise ValueError('Invalid Greeks or implied volatility')
        if (self.instrument.request.right == 'CALL' and self.delta < 0) or (self.instrument.request.right == 'PUT' and self.delta > 0):
            raise ValueError('Delta direction does not match option right')
        _timestamp(self.observed_at)
        if self.data_type not in ('synthetic', 'live', 'delayed', 'frozen'):
            raise ValueError('Unknown market-data type')
        if (self.data_type == 'synthetic') != (self.instrument.source == 'synthetic_fixture'):
            raise ValueError('Quote source/type mismatch')

    def usable_at(self, now: datetime, max_age_seconds: int = 60) -> bool:
        """Data-quality diagnostic only; the risk engine still must admit orders."""
        _timestamp(now)
        _integer(max_age_seconds, 'max_age_seconds', 1)
        return (
            self.instrument.market_data_entitled and self.instrument.options_chain_available
            and self.data_type in ('synthetic', 'live') and self.bid_cents > 0
            and self.bid_size > 0 and self.ask_size > 0
            and self.instrument.request.expiry >= now.date()
            and 0 <= (now - self.observed_at).total_seconds() <= max_age_seconds
        )


@dataclass(frozen=True)
class LimitOrderIntent:
    """Requested action only: ownership, risk, expiry and locks remain service gates."""
    identity: AccountIdentity
    instrument: QualifiedInstrument
    side: Side
    quantity: int
    limit_cents: int
    request_key: str
    decision_snapshot_id: str

    def __post_init__(self):
        if not isinstance(self.identity, AccountIdentity) or not isinstance(self.instrument, QualifiedInstrument):
            raise ValueError('Order intent requires account and qualified instrument')
        if self.instrument.request.security_type != 'OPT' or self.side not in ('BUY_TO_OPEN', 'SELL_TO_CLOSE'):
            raise ValueError('Only long single-leg option entries and owned closes are supported')
        _integer(self.quantity, 'quantity', 1)
        _integer(self.limit_cents, 'limit_cents', 1)
        _text(self.request_key, 'request_key')
        _text(self.decision_snapshot_id, 'decision_snapshot_id')


@dataclass(frozen=True)
class OrderReceipt:
    identity: AccountIdentity
    request_key: str
    broker_order_id: str | None
    permanent_id: str | None
    quantity: int
    filled_quantity: int
    status: OrderStatus
    source: Source

    def __post_init__(self):
        if not isinstance(self.identity, AccountIdentity):
            raise ValueError('Receipt requires explicit account identity')
        _text(self.request_key, 'request_key')
        for value in (self.broker_order_id, self.permanent_id):
            if value is not None:
                _text(value, 'broker identifier')
        _integer(self.quantity, 'quantity', 1)
        _integer(self.filled_quantity, 'filled_quantity')
        if self.filled_quantity > self.quantity or self.status not in ('ACCEPTED', 'PARTIAL', 'FILLED', 'CANCELLED', 'REJECTED', 'UNKNOWN'):
            raise ValueError('Invalid receipt state')
        if self.status == 'PARTIAL' and not 0 < self.filled_quantity < self.quantity:
            raise ValueError('Partial fill quantity mismatch')
        if self.status == 'FILLED' and self.filled_quantity != self.quantity:
            raise ValueError('Filled receipt quantity mismatch')
        if self.status in ('ACCEPTED', 'REJECTED') and self.filled_quantity != 0:
            raise ValueError('Receipt state conflicts with executed quantity')
        if self.status not in ('UNKNOWN', 'REJECTED') and self.broker_order_id is None:
            raise ValueError('Resolved broker receipt requires broker order identifier')
        _source(self.source)


@dataclass(frozen=True)
class OwnedPosition:
    identity: AccountIdentity
    instrument: QualifiedInstrument
    quantity: int
    cost_cents: int

    def __post_init__(self):
        if not isinstance(self.identity, AccountIdentity) or not isinstance(self.instrument, QualifiedInstrument):
            raise ValueError('Position requires explicit account and instrument')
        if self.instrument.request.security_type != 'OPT':
            raise ValueError('Only owned option positions are supported')
        _integer(self.quantity, 'quantity', 1)
        _integer(self.cost_cents, 'cost_cents')


@dataclass(frozen=True)
class ReconciliationSnapshot:
    """Transport evidence container; no account trust or ledger is mutated here."""
    account: AccountSnapshot
    orders: tuple[OrderReceipt, ...]
    positions: tuple[OwnedPosition, ...]
    executions_complete: bool
    orders_complete: bool
    positions_complete: bool

    def __post_init__(self):
        if not isinstance(self.account, AccountSnapshot) or type(self.orders) is not tuple or type(self.positions) is not tuple:
            raise ValueError('Reconciliation requires immutable snapshot containers')
        for name in ('executions_complete', 'orders_complete', 'positions_complete'):
            if type(getattr(self, name)) is not bool:
                raise ValueError('End markers must be explicit booleans')
        seen, broker_ids = set(), set()
        for receipt in self.orders:
            if not isinstance(receipt, OrderReceipt) or receipt.identity != self.account.identity or receipt.source != self.account.source:
                raise ValueError('Cross-account/source order in reconciliation')
            if receipt.request_key in seen:
                raise ValueError('Duplicate request in reconciliation')
            if receipt.broker_order_id is not None and receipt.broker_order_id in broker_ids:
                raise ValueError('Duplicate broker order in reconciliation')
            seen.add(receipt.request_key)
            if receipt.broker_order_id is not None:
                broker_ids.add(receipt.broker_order_id)
        seen = set()
        for position in self.positions:
            if not isinstance(position, OwnedPosition) or position.identity != self.account.identity or position.instrument.source != self.account.source:
                raise ValueError('Cross-account/source position in reconciliation')
            if position.instrument.contract_id in seen:
                raise ValueError('Duplicate position in reconciliation')
            seen.add(position.instrument.contract_id)

    def complete_at(self, now: datetime) -> bool:
        """Completeness only; never a substitute for risk or ledger reconciliation."""
        return (
            self.account.fresh_at(now) and self.executions_complete and self.orders_complete
            and self.positions_complete and all(order.status != 'UNKNOWN' for order in self.orders)
        )


@runtime_checkable
class BrokerAdapter(Protocol):
    def capabilities(self) -> dict: ...
    def connect(self, connection_id: str) -> None: ...
    def account_snapshot(self, identity: AccountIdentity) -> AccountSnapshot: ...
    def qualify_instrument(self, request: InstrumentRequest) -> QualifiedInstrument: ...
    def option_quote(self, identity: AccountIdentity, instrument: QualifiedInstrument) -> OptionQuote: ...
    def submit_limit(self, intent: LimitOrderIntent) -> OrderReceipt: ...
    def cancel(self, identity: AccountIdentity, broker_order_id: str) -> OrderReceipt: ...
    def reconcile(self, identity: AccountIdentity) -> ReconciliationSnapshot: ...


MOCK_SYMBOLS = frozenset({'NVDA', 'AAPL', 'TSLA', 'SPY', 'QQQ', 'MSFT', 'AMD'})


class MockBrokerAdapter:
    """Stateless qualification facade, not another ledger or broker connection."""

    def verify_symbol(self, symbol):
        verified = isinstance(symbol, str) and symbol in MOCK_SYMBOLS
        return {
            'symbol': symbol, 'verified': verified, 'market_data_entitled': verified,
            'source': 'synthetic_fixture', 'real_broker_verification': False,
            'instrument_type': 'STK' if verified else None, 'exchange': 'MOCK' if verified else None,
            'currency': 'USD' if verified else None,
            'contract_id': f'mock:stock:{symbol}' if verified else None,
            'options_chain_available': verified,
        }

    def qualify_instrument(self, request: InstrumentRequest) -> QualifiedInstrument:
        if not isinstance(request, InstrumentRequest) or request.symbol not in MOCK_SYMBOLS:
            raise ValueError('Instrument is not in the explicit synthetic catalogue')
        if request.exchange not in ('SMART', 'MOCK'):
            raise ValueError('Mock catalogue cannot verify a real exchange')
        underlying = f'mock:stock:{request.symbol}'
        if request.security_type == 'OPT':
            if request.multiplier != 100 or request.expiry.weekday() != 4 or not 5000 <= request.strike_cents <= 100000 or request.strike_cents % 100:
                raise ValueError('Option is outside the synthetic standard-contract fixture')
            key = f'{request.symbol}|{request.right}|{request.expiry.isoformat()}|{request.strike_cents}|{request.multiplier}'
            contract_id = 'mock:option:' + hashlib.sha256(key.encode()).hexdigest()[:32]
        else:
            contract_id = underlying
        return QualifiedInstrument(request, contract_id, underlying, 'MOCK', request.symbol, True, True, 'synthetic_fixture', False)

    def capabilities(self):
        return {
            'broker': 'mock', 'paper': True, 'live': False, 'market_data': 'synthetic_fixture',
            'external_io': False, 'qualification': True, 'account_snapshot': False,
            'order_execution': False, 'ledger_owner': 'TradingService',
        }

    def _unsupported(self):
        raise BrokerOperationUnsupported('Use transactional TradingService; the adapter facade has no account/order state')

    def connect(self, connection_id: str = '') -> None:
        self._unsupported()

    def account_snapshot(self, identity: AccountIdentity) -> AccountSnapshot:
        self._unsupported()

    def option_quote(self, identity: AccountIdentity, instrument: QualifiedInstrument) -> OptionQuote:
        self._unsupported()

    def submit_limit(self, intent: LimitOrderIntent) -> OrderReceipt:
        self._unsupported()

    def cancel(self, identity: AccountIdentity, broker_order_id: str) -> OrderReceipt:
        self._unsupported()

    def reconcile(self, identity: AccountIdentity) -> ReconciliationSnapshot:
        self._unsupported()


class IBKRAdapter:
    """No configuration flag or method argument can activate this scaffold."""
    def capabilities(self):
        return {'broker': 'ibkr', 'paper': False, 'live': False, 'status': 'disabled_scaffold', 'external_io': False}

    def _disabled(self):
        raise LiveTradingDisabled('IBKR disabled: no account, Paper, market-data or order connection is permitted')

    def connect(self, *args, **kwargs):
        self._disabled()

    def account_snapshot(self, *args, **kwargs):
        self._disabled()

    def qualify_instrument(self, *args, **kwargs):
        self._disabled()

    def option_quote(self, *args, **kwargs):
        self._disabled()

    def submit_limit(self, *args, **kwargs):
        self._disabled()

    def submit(self, *args, **kwargs):
        self._disabled()

    def cancel(self, *args, **kwargs):
        self._disabled()

    def reconcile(self, *args, **kwargs):
        self._disabled()


class GenericAnalysisAdapter:
    """Disabled future read-only analysis boundary with no execution authority."""
    @property
    def enabled(self):
        return False

    def capabilities(self):
        return {'enabled': False, 'read_only': True, 'execution_authority': False, 'source': 'external_disabled'}

    def analyze(self, *args, **kwargs):
        raise PermissionError('Generic analysis integration is disabled; no API calls are implemented')
