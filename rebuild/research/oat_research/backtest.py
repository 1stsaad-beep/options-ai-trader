"""Event-driven daily portfolio backtester for long Calls / long Puts.

Timing (no look-ahead):
  * Signals are computed from bars up to and including day t (close).
  * Entries fill at the OPEN of day t+1 (option priced from open_t+1 with IV_t).
  * Positions are marked at each close; exit rules are evaluated at the close and
    fill at that close's modelled sell price.
Rules enforced exactly like the app:
  * one direction per symbol per account; Call and Put never coexist (lock);
  * a symbol exited at close t can be re-entered (either side) from open t+1 only;
  * max open positions, risk per trade, max premium per position, cash limit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import options_model as om
from .indicators import atr


@dataclass
class ExitRules:
    option_stop: float | None = 0.50      # exit if premium <= entry*(1-x)
    option_target: float | None = 1.00    # exit if premium >= entry*(1+x)
    trail_arm: float | None = 0.50        # trailing arms after +x on premium
    trail_drop: float = 0.30              # exit on drop of x from peak premium
    time_stop_days: int | None = 10       # trading days
    use_signal_stop: bool = True          # underlying stop from the signal
    use_signal_target: bool = True        # underlying target from the signal
    atr_stop: float | None = None         # fallback underlying stop in ATR
    atr_target: float | None = None
    min_dte_exit: int = 7                 # close when <= x calendar days left
    exit_on_opposite: bool = True


@dataclass
class StrategyConfig:
    name: str
    exits: ExitRules = field(default_factory=ExitRules)
    dte: int = 35
    target_delta: float = 0.60
    risk_per_trade: float = 0.02          # fraction of equity at risk (premium * stop)
    max_position_pct: float = 0.10        # max premium per position as fraction of equity
    max_open: int = 5
    allow_calls: bool = True
    allow_puts: bool = True


@dataclass
class Trade:
    symbol: str
    direction: int
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_px: float          # option price paid per share (incl. spread)
    exit_px: float
    contracts: int
    strike: float
    entry_spot: float
    exit_spot: float
    exit_reason: str
    reason: str
    bars_held: int

    @property
    def ret(self) -> float:  # return on premium after spread, before commission
        return self.exit_px / self.entry_px - 1

    def pnl(self, commission: float) -> float:
        return (self.exit_px - self.entry_px) * 100 * self.contracts - 2 * commission * self.contracts


@dataclass
class _Pos:
    symbol: str
    direction: int
    entry_date: pd.Timestamp
    expiry: pd.Timestamp
    strike: float
    contracts: int
    entry_px: float
    entry_spot: float
    stop: float | None
    target: float | None
    reason: str
    peak_mid: float
    bars: int = 0
    last_mid: float = 0.0


def run(data: dict[str, pd.DataFrame], signals: dict[str, pd.DataFrame], cfg: StrategyConfig,
        costs: om.OptionCosts = om.OptionCosts(), start: pd.Timestamp | None = None,
        end: pd.Timestamp | None = None, initial: float = 100_000.0, vix: pd.Series | None = None,
        cost_overrides: dict[str, om.OptionCosts] | None = None):
    """signals[sym]: DataFrame indexed like data[sym] with columns
    dir (+1/-1/0), stop (float|nan), target (float|nan), reason (str)."""
    ivs, atrs = {}, {}
    for s, df in data.items():
        c = (cost_overrides or {}).get(s, costs)
        ivs[s] = om.iv_series(df, c, vix if s in ("SPY",) else None)
        atrs[s] = atr(df)
    dates = sorted(set().union(*[df.index for df in data.values()]))
    if start is not None:
        dates = [d for d in dates if d >= start]
    if end is not None:
        dates = [d for d in dates if d <= end]
    cash = initial
    open_pos: dict[str, _Pos] = {}
    trades: list[Trade] = []
    curve = []
    pending: dict[str, tuple[int, float, float, str]] = {}  # symbol -> signal from previous close

    for d in dates:
        # ---- 1) entries at today's open from yesterday's signals ----
        for sym, (direction, stop, target, reason) in list(pending.items()):
            df = data[sym]
            if d not in df.index or sym in open_pos or len(open_pos) >= cfg.max_open:
                continue
            c = (cost_overrides or {}).get(sym, costs)
            i = df.index.get_loc(d)
            if i < 1:
                continue
            iv = ivs[sym].iloc[i - 1]
            spot = df["open"].iloc[i]
            if not np.isfinite(iv):
                continue
            is_call = direction > 0
            k = om.choose_strike(is_call, spot, cfg.dte, iv, cfg.target_delta, c)
            mid = om.mid_price(is_call, spot, k, cfg.dte, iv, c)
            px = om.buy_price(mid, c)
            equity = cash + sum(p.last_mid * 100 * p.contracts for p in open_pos.values())
            stop_frac = cfg.exits.option_stop or 1.0
            n_risk = math.floor(equity * cfg.risk_per_trade / (px * 100 * stop_frac))
            n_cap = math.floor(equity * cfg.max_position_pct / (px * 100))
            n_cash = math.floor(cash / (px * 100 + c.commission))
            n = min(n_risk, n_cap, n_cash)
            if n < 1:
                continue
            cash -= n * (px * 100 + c.commission)
            open_pos[sym] = _Pos(sym, direction, d, d + pd.Timedelta(days=cfg.dte), k, n, px, spot,
                                 stop, target, reason, mid, 0, mid)
        pending.clear()

        # ---- 2) mark & exits at today's close ----
        for sym in list(open_pos):
            p = open_pos[sym]
            df = data[sym]
            if d not in df.index:
                continue
            c = (cost_overrides or {}).get(sym, costs)
            i = df.index.get_loc(d)
            spot = df["close"].iloc[i]
            iv = ivs[sym].iloc[i]
            days_left = (p.expiry - d).days
            is_call = p.direction > 0
            mid = om.mid_price(is_call, spot, p.strike, days_left, iv, c)
            p.last_mid = mid
            p.peak_mid = max(p.peak_mid, mid)
            p.bars += 1
            ex = cfg.exits
            sell = om.sell_price(mid, c)
            reason = None
            if ex.option_stop is not None and sell <= p.entry_px * (1 - ex.option_stop):
                reason = "option_stop"
            elif ex.use_signal_stop and p.stop is not None and np.isfinite(p.stop) and (
                    (is_call and spot < p.stop) or (not is_call and spot > p.stop)):
                reason = "underlying_stop"
            elif days_left <= ex.min_dte_exit:
                reason = "dte"
            elif ex.trail_arm is not None and p.peak_mid >= p.entry_px * (1 + ex.trail_arm) and \
                    mid <= p.peak_mid * (1 - ex.trail_drop):
                reason = "trailing"
            elif ex.option_target is not None and sell >= p.entry_px * (1 + ex.option_target):
                reason = "option_target"
            elif ex.use_signal_target and p.target is not None and np.isfinite(p.target) and (
                    (is_call and spot >= p.target) or (not is_call and spot <= p.target)):
                reason = "underlying_target"
            elif ex.time_stop_days is not None and p.bars >= ex.time_stop_days:
                reason = "time"
            elif ex.exit_on_opposite:
                sig = signals[sym]
                if d in sig.index and sig["dir"].loc[d] == -p.direction:
                    reason = "opposite"
            if reason:
                cash += sell * 100 * p.contracts - c.commission * p.contracts
                trades.append(Trade(sym, p.direction, p.entry_date, d, p.entry_px, sell, p.contracts, p.strike,
                                    p.entry_spot, spot, reason, p.reason, p.bars))
                del open_pos[sym]

        # ---- 3) signals at today's close -> pending entries for tomorrow ----
        for sym, sig in signals.items():
            if sym in open_pos or d not in sig.index:
                continue
            row = sig.loc[d]
            direction = int(row["dir"])
            if direction == 0 or (direction > 0 and not cfg.allow_calls) or (direction < 0 and not cfg.allow_puts):
                continue
            pending[sym] = (direction, float(row.get("stop", np.nan)), float(row.get("target", np.nan)),
                            str(row.get("reason", "")))
        equity = cash + sum(p.last_mid * 100 * p.contracts for p in open_pos.values())
        curve.append((d, equity, len(open_pos)))

    curve_df = pd.DataFrame(curve, columns=["date", "equity", "open"]).set_index("date")
    return trades, curve_df


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def metrics(trades: list[Trade], curve: pd.DataFrame, commission: float = 0.65) -> dict:
    out = {"trades": len(trades)}
    if curve is not None and len(curve) > 1:
        eq = curve["equity"]
        peak = eq.cummax()
        dd = (eq / peak - 1).min()
        years = (eq.index[-1] - eq.index[0]).days / 365.25
        cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 and eq.iloc[-1] > 0 else -1
        r = eq.pct_change().dropna()
        sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0.0
        out.update(total_return=eq.iloc[-1] / eq.iloc[0] - 1, cagr=cagr, max_dd=dd, sharpe=sharpe,
                   exposure=(curve["open"] > 0).mean())
    if trades:
        rets = np.array([t.ret for t in trades])
        pnl = np.array([t.pnl(commission) for t in trades])
        wins, losses = rets[rets > 0], rets[rets <= 0]
        gp, gl = pnl[pnl > 0].sum(), -pnl[pnl <= 0].sum()
        out.update(
            win_rate=(rets > 0).mean(),
            avg_win=wins.mean() if len(wins) else 0.0,
            avg_loss=losses.mean() if len(losses) else 0.0,
            payoff=(wins.mean() / -losses.mean()) if len(wins) and len(losses) and losses.mean() < 0 else np.nan,
            expectancy=rets.mean(),
            median_ret=float(np.median(rets)),
            profit_factor=gp / gl if gl > 0 else np.inf,
            avg_bars=np.mean([t.bars_held for t in trades]),
            calls=sum(t.direction > 0 for t in trades),
            puts=sum(t.direction < 0 for t in trades),
        )
    return out


def yearly(curve: pd.DataFrame) -> pd.Series:
    eq = curve["equity"]
    return eq.resample("YE").last().pct_change().fillna(eq.resample("YE").last().iloc[0] / eq.iloc[0] - 1)


def exit_breakdown(trades: list[Trade]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    df = pd.DataFrame([{"reason": t.exit_reason, "ret": t.ret} for t in trades])
    return df.groupby("reason")["ret"].agg(["count", "mean"]).sort_values("count", ascending=False)
