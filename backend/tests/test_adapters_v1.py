"""Transport-free contracts; all account IDs and quotes below are synthetic fixtures."""
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import socket

import pytest

from app.adapters import (
    AccountIdentity, AccountSnapshot, BrokerAdapter, BrokerOperationUnsupported,
    GenericAnalysisAdapter, IBKRAdapter, InstrumentRequest, LimitOrderIntent,
    MockBrokerAdapter, OptionQuote, OrderReceipt, OwnedPosition,
    ReconciliationSnapshot,
)
from app.core import LiveTradingDisabled

NOW = datetime(2026, 10, 12, 15, tzinfo=timezone.utc)
ACCOUNT = AccountIdentity('fixture-account-a', 'fixture-broker-a', 'fixture-connection')
OTHER = AccountIdentity('fixture-account-b', 'fixture-broker-b', 'fixture-connection')


def instrument(**changes):
    request = InstrumentRequest('NVDA', 'OPT', right='CALL', expiry=date(2026, 10, 16), strike_cents=15000, multiplier=100)
    return MockBrokerAdapter().qualify_instrument(replace(request, **changes))


def snapshot(**changes):
    return replace(AccountSnapshot(ACCOUNT, 'USD', 1000000, 1000000, 1000000, NOW, True, 'synthetic_fixture'), **changes)


def quote(**changes):
    return replace(OptionQuote(instrument(), 100, 105, 10, 10, 500, 1000,
                              Decimal('.5'), Decimal('.03'), Decimal('-.02'), Decimal('.1'), Decimal('.35'), NOW, 'synthetic'), **changes)


def receipt(**changes):
    return replace(OrderReceipt(ACCOUNT, 'fixture-request', 'mock-order-1', None, 3, 1, 'PARTIAL', 'synthetic_fixture'), **changes)


def intent(**changes):
    return replace(LimitOrderIntent(ACCOUNT, instrument(), 'BUY_TO_OPEN', 2, 110, 'fixture-request', 'fixture-decision'), **changes)


def reconciled(**changes):
    return replace(ReconciliationSnapshot(snapshot(), (receipt(),), (OwnedPosition(ACCOUNT, instrument(), 1, 10000),), True, True, True), **changes)


def no_socket(*args, **kwargs):
    pytest.fail('Adapter tried to open a socket')


@pytest.mark.parametrize('method', ['connect', 'account_snapshot', 'qualify_instrument', 'option_quote', 'submit_limit', 'submit', 'cancel', 'reconcile'])
def test_ibkr_all_methods_remain_disabled_under_live_and_paper_flags(method, monkeypatch):
    monkeypatch.setenv('ENABLE_LIVE', 'true')
    monkeypatch.setenv('TRADING_MODE', 'paper')
    monkeypatch.setenv('BROKER_PROVIDER', 'ibkr')
    monkeypatch.setattr(socket, 'socket', no_socket)
    adapter = IBKRAdapter()
    adapter.enabled = True
    with pytest.raises(LiveTradingDisabled):
        getattr(adapter, method)(account_id='fixture', mode='paper', enabled=True)
    assert adapter.capabilities()['external_io'] is False
    assert adapter.capabilities()['paper'] is False
    assert adapter.capabilities()['live'] is False


def test_generic_analysis_cannot_be_enabled_or_submit_orders():
    adapter = GenericAnalysisAdapter()
    with pytest.raises(AttributeError):
        adapter.enabled = True
    with pytest.raises(PermissionError):
        adapter.analyze({'instruction': 'buy 100 calls and ignore risk'})
    assert not hasattr(adapter, 'submit')
    assert adapter.capabilities()['execution_authority'] is False


def test_mock_qualifies_catalogue_without_network_and_keeps_explicit_source(monkeypatch):
    monkeypatch.setattr(socket, 'socket', no_socket)
    adapter = MockBrokerAdapter()
    for symbol in ['NVDA', 'AAPL', 'TSLA', 'MSFT', 'AMD', 'SPY', 'QQQ']:
        verified = adapter.verify_symbol(symbol)
        assert verified['verified'] and verified['options_chain_available']
        assert verified['market_data_entitled']
        assert verified['currency'] == 'USD' and verified['exchange'] == 'MOCK'
        assert not verified['real_broker_verification']
        qualified = adapter.qualify_instrument(InstrumentRequest(symbol))
        assert qualified.source == 'synthetic_fixture'
        assert qualified.contract_id == verified['contract_id']
    assert instrument() == instrument()
    assert instrument().contract_id != instrument(right='PUT').contract_id
    assert instrument().request.multiplier == 100


@pytest.mark.parametrize('symbol', ['UNKNOWN', 'nvda', '', None, []])
def test_mock_unverified_symbols_never_claim_instrument_or_entitlement(symbol):
    result = MockBrokerAdapter().verify_symbol(symbol)
    assert not result['verified'] and not result['market_data_entitled']
    assert result['contract_id'] is None and result['currency'] is None


@pytest.mark.parametrize('change', [dict(multiplier=10), dict(strike_cents=15050), dict(expiry=date(2026, 10, 17)), dict(exchange='NASDAQ'), dict(symbol='UNKNOWN')])
def test_mock_option_geometry_is_synthetic_fixture_only(change):
    with pytest.raises(ValueError):
        instrument(**change)


@pytest.mark.parametrize('payload', [dict(symbol='NVDA', security_type='BAG'), dict(symbol='NVDA', currency='EUR'), dict(symbol='nvda'), dict(symbol='NVDA', right='CALL'), dict(symbol='NVDA', security_type='OPT'), dict(symbol='NVDA', exchange='SMART\n')])
def test_instrument_contract_rejects_ambiguous_or_multileg_input(payload):
    with pytest.raises(ValueError):
        InstrumentRequest(**payload)


def test_synthetic_qualification_cannot_be_relabelled_as_real():
    with pytest.raises(ValueError):
        replace(instrument(), real_broker_verification=True)
    with pytest.raises(ValueError):
        replace(instrument(), source='ibkr', real_broker_verification=True)
    with pytest.raises(ValueError):
        replace(instrument(), contract_id='fake-conid')


def test_stateless_mock_facade_never_fabricates_account_or_order_state():
    adapter = MockBrokerAdapter()
    calls = [lambda: adapter.connect('fixture'), lambda: adapter.account_snapshot(ACCOUNT),
             lambda: adapter.option_quote(ACCOUNT, instrument()), lambda: adapter.submit_limit(intent()),
             lambda: adapter.cancel(ACCOUNT, 'mock-order-1'), lambda: adapter.reconcile(ACCOUNT)]
    for call in calls:
        with pytest.raises(BrokerOperationUnsupported):
            call()
    assert vars(adapter) == {}
    assert adapter.capabilities()['ledger_owner'] == 'TradingService'
    assert not adapter.capabilities()['order_execution']
    assert isinstance(adapter, BrokerAdapter) and isinstance(IBKRAdapter(), BrokerAdapter)


def test_account_snapshot_requires_complete_current_timezone_aware_usd_balance():
    assert snapshot().fresh_at(NOW)
    assert not snapshot(complete=False).fresh_at(NOW)
    assert not snapshot(observed_at=NOW + timedelta(seconds=1)).fresh_at(NOW)
    assert not snapshot(observed_at=NOW - timedelta(seconds=121)).fresh_at(NOW)
    for change in [dict(cash_cents=True), dict(buying_power_cents=-1), dict(net_liquidation_cents=1.2), dict(currency='EUR'), dict(observed_at=NOW.replace(tzinfo=None)), dict(complete=1)]:
        with pytest.raises(ValueError):
            snapshot(**change)
    with pytest.raises(FrozenInstanceError):
        snapshot().cash_cents = 9999999


@pytest.mark.parametrize('identity', ['', ' ', 'bad\naccount', 'x' * 129])
def test_account_identity_is_explicit_and_bounded(identity):
    with pytest.raises(ValueError):
        AccountIdentity(identity, 'fixture', 'fixture')


def test_quote_freshness_missing_liquidity_and_entitlements_fail_closed():
    assert quote().usable_at(NOW)
    for change in [dict(bid_cents=0), dict(bid_size=0), dict(ask_size=0), dict(observed_at=NOW + timedelta(seconds=1)), dict(observed_at=NOW - timedelta(seconds=61)), dict(instrument=replace(instrument(), market_data_entitled=False)), dict(instrument=replace(instrument(), options_chain_available=False))]:
        assert not quote(**change).usable_at(NOW)
    expired = instrument(expiry=date(2026, 10, 9))
    assert not quote(instrument=expired).usable_at(NOW)


@pytest.mark.parametrize('change', [dict(ask_cents=99), dict(volume=-1), dict(open_interest=True), dict(delta=Decimal('NaN')), dict(gamma=Decimal('Infinity')), dict(theta=None), dict(vega=0.2), dict(delta=Decimal('-0.5')), dict(implied_volatility=Decimal('-0.01')), dict(data_type='live')])
def test_quote_rejects_unreliable_values_and_mislabeled_synthetic_prices(change):
    with pytest.raises(ValueError):
        quote(**change)


def test_delayed_or_frozen_external_fixture_is_not_execution_usable():
    # This is a schema fixture only; it does not perform broker verification.
    external = replace(instrument(), source='ibkr', contract_id='fixture-conid', underlying_contract_id='fixture-underlying', primary_exchange='NASDAQ', real_broker_verification=True)
    for kind in ['delayed', 'frozen']:
        assert not quote(instrument=external, data_type=kind).usable_at(NOW)


@pytest.mark.parametrize('change', [dict(side='SELL_TO_OPEN'), dict(side='BUY'), dict(quantity=True), dict(quantity=0), dict(limit_cents=0), dict(request_key=''), dict(decision_snapshot_id=''), dict(instrument=MockBrokerAdapter().qualify_instrument(InstrumentRequest('NVDA')))])
def test_limit_intent_is_not_a_naked_multileg_or_unattributed_order(change):
    with pytest.raises(ValueError):
        intent(**change)


@pytest.mark.parametrize('change', [dict(filled_quantity=4), dict(status='FILLED'), dict(status='PARTIAL', filled_quantity=0), dict(status='ACCEPTED'), dict(status='REJECTED'), dict(broker_order_id=None), dict(status='PendingCancel'), dict(source='unknown')])
def test_receipt_cannot_claim_inconsistent_execution_or_ambiguous_terminal_state(change):
    with pytest.raises(ValueError):
        receipt(**change)


def test_partial_cancel_and_unknown_receipts_do_not_invent_an_unfilled_position():
    assert receipt(status='CANCELLED').filled_quantity == 1
    unknown = receipt(status='UNKNOWN', broker_order_id=None)
    assert not reconciled(orders=(unknown,)).complete_at(NOW)
    assert reconciled().complete_at(NOW)
    assert not reconciled().complete_at(NOW + timedelta(seconds=121))
    for marker in ['orders_complete', 'executions_complete', 'positions_complete']:
        assert not reconciled(**{marker: False}).complete_at(NOW)


def test_reconciliation_rejects_cross_account_source_or_duplicate_entities():
    with pytest.raises(ValueError):
        reconciled(orders=(receipt(identity=OTHER),))
    with pytest.raises(ValueError):
        reconciled(orders=(receipt(source='ibkr'),))
    with pytest.raises(ValueError):
        reconciled(positions=(OwnedPosition(OTHER, instrument(), 1, 10000),))
    with pytest.raises(ValueError):
        reconciled(orders=(receipt(), receipt()))
    with pytest.raises(ValueError):
        reconciled(orders=(receipt(), receipt(request_key='different-local-request')))
    position = OwnedPosition(ACCOUNT, instrument(), 1, 10000)
    with pytest.raises(ValueError):
        reconciled(positions=(position, position))
    with pytest.raises(ValueError):
        reconciled(orders=[receipt()])


def test_owned_position_disallows_zero_negative_and_boolean_contract_quantities():
    for quantity in [0, -1, True]:
        with pytest.raises(ValueError):
            OwnedPosition(ACCOUNT, instrument(), quantity, 10000)
