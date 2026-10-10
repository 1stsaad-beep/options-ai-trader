"""Historical long-option simulator using timestamped option quotes, not stock P&L."""
from dataclasses import dataclass
from datetime import timedelta
from math import isfinite
from typing import Callable, Iterable

from .engines import AnalysisEngine, Bar, OptionQuote, OptionsSelectionEngine, Signal, validate_bars


@dataclass(frozen=True)
class Trade:
    contract: tuple
    entry_time: object
    exit_time: object
    quantity: int
    entry_price: float
    exit_price: float
    fees: float
    pnl: float
    exit_reason: str


@dataclass(frozen=True)
class BacktestResult:
    initial_cash: float
    cash: float
    trades: tuple[Trade, ...]
    open_contract: tuple | None
    skipped_entries: int
    decision_count: int
    open_cost_basis: float = 0
    unfilled_final_signal: bool = False

    def metrics(self) -> dict:
        """Realized-only metrics; deliberately no cash-as-equity return claim."""
        pnls = [trade.pnl for trade in self.trades]
        return {
            "closed_trades": len(pnls),
            "realized_pnl": sum(pnls),
            "total_commissions": sum(trade.fees for trade in self.trades),
            "winning_closed_trades": sum(pnl > 0 for pnl in pnls),
            "losing_closed_trades": sum(pnl < 0 for pnl in pnls),
            "cash_excludes_open_position_value": True,
            "open_cost_basis": self.open_cost_basis,
            "unfilled_final_signal": self.unfilled_final_signal,
            "profitability_evidence": False,
        }


class BacktestEngine:
    def __init__(self, initial_cash: float = 10000, max_premium: float = 500,
                 commission: float = .65, slippage: float = .01, hold_bars: int = 5,
                 quote_max_age: timedelta = timedelta(seconds=60)):
        if not all(isfinite(v) for v in (initial_cash, max_premium, commission, slippage)):
            raise ValueError("Non-finite simulation parameters")
        if initial_cash <= 0 or max_premium <= 0 or commission < 0 or slippage < 0 or not isinstance(hold_bars, int) or hold_bars < 1 or quote_max_age.total_seconds() < 0:
            raise ValueError("Invalid simulation parameters")
        self.initial_cash, self.max_premium = initial_cash, max_premium
        self.commission, self.slippage, self.hold_bars = commission, slippage, hold_bars
        self.quote_max_age = quote_max_age

    def run(self, symbol: str, bars: Iterable[Bar], quotes: Iterable[OptionQuote],
            strategy: Callable[[tuple[Bar, ...]], Signal | None] | None = None):
        bars = validate_bars(bars)
        quotes = tuple(quotes)
        identities = set()
        for quote in quotes:
            identity = (quote.key, quote.timestamp)
            if identity in identities:
                raise ValueError("Duplicate contract quote timestamp; historical feed ambiguous")
            identities.add(identity)
        if not symbol:
            raise ValueError("Symbol required")
        cash, position, pending = self.initial_cash, None, None
        trades, skipped, decisions = [], 0, 0
        selector = OptionsSelectionEngine()
        for index, bar in enumerate(bars):
            # Only information timestamped at or before this execution bar is visible.
            known = {}
            for quote in quotes:
                if quote.symbol == symbol and quote.timestamp <= bar.timestamp:
                    if quote.key not in known or quote.timestamp > known[quote.key].timestamp:
                        known[quote.key] = quote
            if position is not None:
                q, quantity, entry_price, entry_time, entry_index = position
                expired = q.expiry <= bar.timestamp.date()
                current = known.get(q.key)
                fresh = current is not None and bar.timestamp - current.timestamp <= self.quote_max_age
                if expired or (index - entry_index >= self.hold_bars and fresh):
                    # Conservative expiry write-off, no fabricated intrinsic or exercise fill.
                    exit_price = 0 if expired else max(0, current.bid - self.slippage)
                    exit_fee = 0 if expired else quantity * self.commission
                    cash += exit_price * quantity * q.multiplier - exit_fee
                    fees = quantity * self.commission + exit_fee
                    pnl = (exit_price - entry_price) * quantity * q.multiplier - fees
                    trades.append(Trade(q.key, entry_time, bar.timestamp, quantity, entry_price, exit_price, fees, pnl, "EXPIRY_WRITE_OFF" if expired else "HOLD_LIMIT"))
                    position = None
            if pending is not None and position is None:
                q = selector.select(known.values(), symbol, pending.right, bar.timestamp, max_age=self.quote_max_age)
                if q is None:
                    skipped += 1
                else:
                    price = q.ask + self.slippage
                    per_contract = price * q.multiplier + self.commission
                    quantity = int(min(cash, self.max_premium) // per_contract)
                    if quantity <= 0:
                        skipped += 1
                    else:
                        cash -= quantity * per_contract
                        position = (q, quantity, price, bar.timestamp, index)
            pending = None
            if position is None and index >= 20:
                history = bars[:index + 1]
                if strategy is None:
                    signals = AnalysisEngine().analyze(history).signals
                    signal = signals[0] if signals else None
                else:
                    signal = strategy(history)
                if signal is not None:
                    if signal.timestamp != bar.timestamp or signal.right not in ("CALL", "PUT"):
                        raise ValueError("Signal must use current completed bar timestamp and long option right")
                    pending = signal
                    decisions += 1
        # An unfilled last-bar signal is not a trade; open positions are reported without a fabricated exit.
        open_cost = (position[2] * position[1] * position[0].multiplier + position[1] * self.commission) if position else 0
        return BacktestResult(self.initial_cash, cash, tuple(trades), position[0].key if position else None,
                              skipped, decisions, open_cost, pending is not None)


def synthetic_demo() -> dict:
    """Reproducible accounting fixture, deliberately a losing trade, not evidence."""
    from datetime import date, datetime, timezone
    base = datetime(2026, 1, 1, 14, 30, tzinfo=timezone.utc)
    bars = []
    for index in range(25):
        price = 100 + index * .1
        bars.append(Bar(base+timedelta(minutes=index), price, price+.3, price-.3, price+.1, 1000))
    quotes = [OptionQuote('AAPL', date(2026, 1, 15), 'CALL', 100, 1.9, 2, .5, .3, 500, b.timestamp) for b in bars]
    def once(prefix):
        return Signal('accounting_fixture', 'CALL', .5, 'Synthetic fixture only', prefix[-1].timestamp) if len(prefix) == 21 else None
    result = BacktestEngine(hold_bars=1).run('AAPL', bars, quotes, once)
    return {
        'source': 'synthetic_fixture', 'strategy': 'injected_once_for_accounting_test',
        'initial_cash': result.initial_cash, 'cash': result.cash,
        'entry_price': result.trades[0].entry_price, 'exit_price': result.trades[0].exit_price,
        'signal_time': bars[20].timestamp.isoformat(),
        'entry_time': result.trades[0].entry_time.isoformat(),
        'exit_time': result.trades[0].exit_time.isoformat(),
        'spread_paid_per_option_share': .1, 'slippage_per_side': .01,
        'commission_per_contract_per_side': .65, **result.metrics(),
    }


if __name__ == '__main__':
    import json
    print(json.dumps(synthetic_demo(), indent=2))
