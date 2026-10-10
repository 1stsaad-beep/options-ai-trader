"""Causal exits and accounting on synthetic option quotes; not profitability evidence."""
import pytest
from datetime import timedelta
from app.backtest import BacktestEngine
from app.engines import Signal
from test_engines import bars, quote


def once(prefix):
    return Signal('fixture', 'CALL', .5, 'synthetic', prefix[-1].timestamp) if len(prefix) == 21 else None


def stream(history, trigger_bid):
    return [quote(b.timestamp, bid=(trigger_bid if i >= 22 else 1.9), ask=(trigger_bid+.1 if i >= 22 else 2)) for i, b in enumerate(history)]


@pytest.mark.parametrize('bid,reason', [(1.2,'STOP_LOSS'),(3.,'TAKE_PROFIT')])
def test_exit_trigger_cannot_fill_until_next_fresh_observation(bid, reason):
    h=bars(25)
    result=BacktestEngine(hold_bars=100,stop_loss_pct=20,take_profit_pct=30).run('AAPL',h,stream(h,bid),once)
    trade=result.trades[0]
    assert trade.entry_time==h[21].timestamp
    assert trade.exit_time==h[23].timestamp
    assert trade.exit_reason==reason
    assert trade.exit_price==pytest.approx(bid-.01)
    assert trade.fees==pytest.approx(2*.65*trade.quantity)
    assert result.cash==pytest.approx(10000+trade.pnl)


def test_exit_waits_through_quote_outage_and_uses_recovery_price():
    h=bars(26);qs=stream(h,1.2)
    qs=[q for i,q in enumerate(qs) if i not in (23,24)]
    qs[-1]=quote(h[-1].timestamp,bid=.7,ask=.8)
    result=BacktestEngine(hold_bars=100,stop_loss_pct=20,quote_max_age=timedelta(0)).run('AAPL',h,qs,once)
    assert result.trades[0].exit_time==h[25].timestamp
    assert result.trades[0].exit_price==pytest.approx(.69)
    assert result.missing_valuations==2
    assert result.equity_curve[23][1] is None
    assert result.metrics()['drawdown_complete'] is False


def test_last_observation_exit_is_pending_not_fabricated_fill():
    h=bars(23)
    result=BacktestEngine(hold_bars=100,stop_loss_pct=20).run('AAPL',h,stream(h,1.2),once)
    assert result.trades==()
    assert result.open_contract is not None
    assert result.pending_exit=='STOP_LOSS'
    assert result.metrics()['paid_commissions_including_open']>0


def test_future_append_preserves_equity_prefix_and_entry():
    h=bars(26);qs=stream(h,3)
    engine=BacktestEngine(hold_bars=100,take_profit_pct=30)
    short=engine.run('AAPL',h[:23],qs,once)
    full=engine.run('AAPL',h,qs,once)
    assert short.equity_curve==full.equity_curve[:23]
    assert full.trades[0].entry_time==h[21].timestamp


def test_daily_loss_limit_blocks_reentry_without_blocking_exit():
    h=bars(30)
    always=lambda p: Signal('fixture','CALL',.5,'synthetic',p[-1].timestamp)
    r=BacktestEngine(hold_bars=1,daily_loss_limit=1).run('AAPL',h,[quote(b.timestamp) for b in h],always)
    assert len(r.trades)==1
    assert r.skipped_entries>0
    assert r.open_contract is None
    assert r.metrics()['max_observed_drawdown']>0
    assert r.metrics()['profitability_evidence'] is False


@pytest.mark.parametrize('name,value', [('stop_loss_pct',0),('stop_loss_pct',100),('stop_loss_pct',float('nan')),('take_profit_pct',-1),('daily_loss_limit',float('inf')),('daily_loss_limit',True)])
def test_invalid_risk_parameters_fail_closed(name,value):
    with pytest.raises(ValueError): BacktestEngine(**{name:value})
