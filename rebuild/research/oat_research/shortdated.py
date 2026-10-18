"""Round 4: short-dated (weekly, <= 7 calendar days) long Call/Put simulator.

Fixes from the round-3 audit, built in:
  * Conditional exits are decided at a bar close and FILLED AT THE NEXT BAR OPEN.
    Only exits known in advance (scheduled time stops / pre-expiry cut-off) fill at
    the close of the bar on which they are due.
  * No alphabetical priority: simultaneous signals are ranked by their `score`
    (desc), ties broken by a per-day hash rotation.
  * Metrics on a daily NAV (cash + bid marks) plus per-trade net returns that include
    both commissions; t-statistics clustered by entry week are reported by the study.

Bars: any frequency. Daily bars are stamped at midnight and are treated as open 09:30 /
close 16:00. Intraday bars are stamped at their start (exchange time) and last
`bar_minutes`.

Expiry rule: the first Friday at least `min_days` calendar days after entry (and at
most 7 + min_days). Options expire at 16:00 on that Friday.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import options_model as om
from .indicators import atr, realized_vol


# ---------------------------------------------------------------- implied vol proxy
def iv_table(daily: dict[str, pd.DataFrame], vol: dict[str, pd.Series], vrp: float = 1.10) -> dict[str, pd.Series]:
    """Daily short-term IV proxy per symbol, known after that day's close (use it the
    NEXT day). SPY: VIX9D (VIX before 2011). QQQ: VXN scaled by VIX9D/VIX. Others:
    vrp * blend(RV10, RV20, RV60) scaled by the market's short/long term ratio."""
    vix = vol.get("VIX")
    vix9 = vol.get("VIX9D")
    vxn = vol.get("VXN")
    term = None
    if vix is not None and vix9 is not None:
        term = (vix9 / vix).reindex(vix.index).ffill().clip(0.6, 1.8).fillna(1.0)
    out = {}
    for s, df in daily.items():
        c = df["close"]
        rv = (0.3 * realized_vol(c, 10) + 0.4 * realized_vol(c, 20) + 0.3 * realized_vol(c, 60))
        base = vrp * rv
        if term is not None:
            base = base * term.reindex(df.index).ffill().fillna(1.0)
        if s == "SPY" and vix is not None:
            short = (vix9 if vix9 is not None else vix).reindex(df.index).ffill() / 100
            base = short.fillna(vix.reindex(df.index).ffill() / 100).fillna(base)
        if s == "QQQ" and vxn is not None:
            q = vxn.reindex(df.index).ffill() / 100
            if term is not None:
                q = q * term.reindex(df.index).ffill().fillna(1.0)
            base = q.fillna(base)
        out[s] = base.clip(lower=0.08)
    return out


def friday_expiry(ts: pd.Timestamp, min_days: int = 1) -> pd.Timestamp:
    d = ts.normalize() + pd.Timedelta(days=min_days)
    while d.weekday() != 4:
        d += pd.Timedelta(days=1)
    return d + pd.Timedelta(hours=16)


@dataclass
class SDExit:
    target_atr: float | None = 1.0        # underlying target in DAILY ATR (close beyond -> exit next open)
    stop_atr: float | None = 1.0          # underlying stop in daily ATR (if the signal has no stop)
    use_signal_levels: bool = True        # prefer the signal's own stop/target when present
    opt_take_profit: float | None = None  # +x premium on the bid mark -> exit next open
    opt_stop: float | None = None         # -x premium
    max_hold_bars: int | None = None      # scheduled: exit at the close of the bar that reaches it
    cutoff_hours_before_expiry: float = 24.0  # scheduled: sell by the close before expiry day (0 = may hold to expiry)
    eod_flat: bool = False                # scheduled: close at the last bar of each day (intraday)


@dataclass
class SDConfig:
    name: str
    exits: SDExit = field(default_factory=SDExit)
    target_delta: float = 0.60
    min_days: int = 1                     # 1 -> this week's Friday unless entry is Thu/Fri
    budget: float = 0.02                  # premium per trade as fraction of NAV
    max_open: int = 5
    bar_minutes: int = 0                  # 0 = daily bars
    daily_expiry_syms: tuple = ()         # symbols with an expiry every weekday (SPY/QQQ since 2022)
    daily_expiry_from: str = "2022-11-15"
    ref_price: float | None = 100.0       # price the option on an underlying rescaled to this level at entry
                                          # (split-adjusted history makes old prices tiny: $0.30 AAPL would
                                          # otherwise pay absurd minimum spreads / strike steps)


@dataclass
class SDTrade:
    symbol: str
    direction: int
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    expiry: pd.Timestamp
    strike: float
    contracts: int
    entry_px: float
    exit_px: float
    entry_spot: float
    exit_spot: float
    exit_reason: str
    reason: str
    hours_held: float
    commission: float = 0.65

    @property
    def net_ret(self) -> float:
        debit = self.contracts * (100 * self.entry_px + self.commission)
        proceeds = self.contracts * (100 * self.exit_px - self.commission)
        return (proceeds - debit) / debit

    @property
    def pnl(self) -> float:
        return self.contracts * (100 * (self.exit_px - self.entry_px) - 2 * self.commission)


@dataclass
class _P:
    sym: str
    d: int
    entry_time: pd.Timestamp
    expiry: pd.Timestamp
    k: float
    n: int
    px: float
    spot: float
    stop: float
    tgt: float
    reason: str
    bars: int = 0
    mark: float = 0.0
    pending_exit: str | None = None
    f: float = 1.0


def _times(ts: pd.Timestamp, bar_minutes: int):
    if bar_minutes == 0:
        return ts.normalize() + pd.Timedelta(hours=9, minutes=30), ts.normalize() + pd.Timedelta(hours=16)
    return ts, min(ts + pd.Timedelta(minutes=bar_minutes), ts.normalize() + pd.Timedelta(hours=16))


def _days_left(expiry, now):
    return max((expiry - now).total_seconds() / 86400.0, 0.0)


def _rank_key(sym: str, ts: pd.Timestamp, score: float):
    h = int(hashlib.md5(f"{sym}{ts.date()}".encode()).hexdigest()[:8], 16)
    return (-score if np.isfinite(score) else 0.0, h)


def run(bars: dict[str, pd.DataFrame], signals: dict[str, pd.DataFrame], cfg: SDConfig,
        daily: dict[str, pd.DataFrame], ivs: dict[str, pd.Series], costs: dict[str, om.OptionCosts],
        start=None, end=None, initial: float = 100_000.0):
    """signals[sym] indexed like bars[sym]: dir, stop, target, score, reason, [min_days, xsched, xcond].
    bars may carry an `end` column (bar end time) for irregular session segments."""
    syms = list(bars)
    stamps = sorted(set().union(*[bars[s].index for s in syms]))
    if start is not None:
        stamps = [t for t in stamps if t >= start]
    if end is not None:
        stamps = [t for t in stamps if t <= end]
    # per-symbol fast lookups
    O = {s: bars[s]["open"].to_numpy() for s in syms}
    C = {s: bars[s]["close"].to_numpy() for s in syms}
    ENDS = {s: (pd.DatetimeIndex(bars[s]["end"]) if "end" in bars[s] else None) for s in syms}
    IDX = {s: {t: i for i, t in enumerate(bars[s].index)} for s in syms}
    XS = {s: set(sig.index[sig["xsched"].astype(bool).to_numpy()]) if "xsched" in sig else set() for s, sig in signals.items()}
    XC = {s: set(sig.index[sig["xcond"].astype(bool).to_numpy()]) if "xcond" in sig else set() for s, sig in signals.items()}
    events: dict = {}
    for s, sig in signals.items():
        nz = sig[sig["dir"] != 0]
        for t, r in nz.iterrows():
            events.setdefault(t, []).append((s, int(r["dir"]), float(r.get("stop", np.nan)), float(r.get("target", np.nan)),
                                             str(r.get("reason", "")), float(r.get("score", 0.0)), float(r.get("min_days", np.nan))))
    # previous-day IV and ATR, looked up by day
    def prev_map(series: pd.Series):
        sr = series.copy()
        sr.index = sr.index.normalize()
        return sr

    IVd = {s: prev_map(ivs[s]) for s in syms}
    ATd = {s: prev_map(atr(daily[s])) for s in syms}
    cache: dict = {}

    def prev_val(kind, sym, day):
        key = (kind, sym, day)
        if key not in cache:
            sr = (IVd if kind == "iv" else ATd)[sym]
            j = sr.index.searchsorted(day) - 1
            cache[key] = float(sr.iloc[j]) if j >= 0 else np.nan
        return cache[key]

    def times(sym, ts, i):
        if ENDS[sym] is not None:
            return ts, ENDS[sym][i]
        return _times(ts, cfg.bar_minutes)

    pos: dict[str, _P] = {}
    trades: list[SDTrade] = []
    cash = initial
    nav_rows = []
    pending: list[tuple] = []
    ex = cfg.exits

    def close_pos(p, t_exit, px_spot, why, c):
        nonlocal cash
        mid = om.mid_price(p.d > 0, px_spot * p.f, p.k, _days_left(p.expiry, t_exit), prev_val("iv", p.sym, t_exit.normalize()), c)
        bid = om.sell_price(mid, c)
        cash += p.n * (100 * bid - c.commission)
        trades.append(SDTrade(p.sym, p.d, p.entry_time, t_exit, p.expiry, p.k, p.n, p.px, bid, p.spot, px_spot, why, p.reason,
                              (t_exit - p.entry_time).total_seconds() / 3600, c.commission))
        del pos[p.sym]

    for ts in stamps:
        day = ts.normalize()
        # 1) fills at this bar's OPEN
        for sym in list(pos):
            p = pos[sym]
            i = IDX[sym].get(ts)
            if p.pending_exit and i is not None:
                t_open, _ = times(sym, ts, i)
                close_pos(p, t_open, O[sym][i], p.pending_exit, costs[sym])
        if pending:
            pending.sort(key=lambda x: _rank_key(x[0], ts, x[5]))
            for sym, d, stop, tgt, reason, score, md in pending:
                i = IDX[sym].get(ts)
                if sym in pos or len(pos) >= cfg.max_open or i is None:
                    continue
                t_open, _ = times(sym, ts, i)
                iv = prev_val("iv", sym, day)
                a = prev_val("atr", sym, day)
                if not (np.isfinite(iv) and np.isfinite(a)):
                    continue
                spot = O[sym][i]
                mdays = int(md) if np.isfinite(md) else cfg.min_days
                if sym in cfg.daily_expiry_syms and t_open >= pd.Timestamp(cfg.daily_expiry_from):
                    expiry = t_open.normalize() + pd.Timedelta(days=mdays, hours=16)
                    while expiry.weekday() >= 5:
                        expiry += pd.Timedelta(days=1)
                else:
                    expiry = friday_expiry(t_open, mdays)
                dl = _days_left(expiry, t_open)
                c = costs[sym]
                f = max(1.0, cfg.ref_price / spot) if cfg.ref_price else 1.0  # only scale UP tiny adjusted prices
                k = om.choose_strike(d > 0, spot * f, max(dl, 0.25), iv, cfg.target_delta, c)
                ask = om.buy_price(om.mid_price(d > 0, spot * f, k, dl, iv, c), c)
                nav = cash + sum(q.n * 100 * om.sell_price(q.mark, costs[q.sym]) for q in pos.values())
                n = math.floor(nav * cfg.budget / (100 * ask + c.commission))
                n = min(n, math.floor(cash / (100 * ask + c.commission)))
                if n < 1:
                    continue
                st = stop if (ex.use_signal_levels and np.isfinite(stop)) else (spot - d * ex.stop_atr * a if ex.stop_atr else np.nan)
                tg = tgt if (ex.use_signal_levels and np.isfinite(tgt)) else (spot + d * ex.target_atr * a if ex.target_atr else np.nan)
                cash -= n * (100 * ask + c.commission)
                pos[sym] = _P(sym, d, t_open, expiry, k, n, ask, spot, st, tg, reason, mark=ask, f=f)
            pending = []
        # 2) marks and exit decisions at this bar's CLOSE
        for sym in list(pos):
            p = pos[sym]
            i = IDX[sym].get(ts)
            if i is None:
                continue
            _, t_close = times(sym, ts, i)
            spot = C[sym][i]
            c = costs[sym]
            mid = om.mid_price(p.d > 0, spot * p.f, p.k, _days_left(p.expiry, t_close), prev_val("iv", sym, day), c)
            p.mark = mid
            p.bars += 1
            bid = om.sell_price(mid, c)
            sched = None
            if (p.expiry - t_close).total_seconds() / 3600 <= ex.cutoff_hours_before_expiry + 1e-9:
                sched = "pre_expiry"
            elif ex.max_hold_bars is not None and p.bars >= ex.max_hold_bars:
                sched = "time"
            elif ex.eod_flat and (ENDS[sym] is not None or cfg.bar_minutes) and (i + 1 >= len(C[sym]) or bars[sym].index[i + 1].normalize() != day):
                sched = "eod"
            elif ts in XS.get(sym, ()):
                sched = "rule_scheduled"
            if sched:
                cash += p.n * (100 * bid - c.commission)
                trades.append(SDTrade(sym, p.d, p.entry_time, t_close, p.expiry, p.k, p.n, p.px, bid, p.spot, spot, sched,
                                      p.reason, (t_close - p.entry_time).total_seconds() / 3600, c.commission))
                del pos[sym]
                continue
            why = None
            if np.isfinite(p.stop) and (spot - p.stop) * p.d < 0:
                why = "underlying_stop"
            elif np.isfinite(p.tgt) and (spot - p.tgt) * p.d >= 0:
                why = "underlying_target"
            elif ex.opt_stop is not None and bid <= p.px * (1 - ex.opt_stop):
                why = "option_stop"
            elif ex.opt_take_profit is not None and bid >= p.px * (1 + ex.opt_take_profit):
                why = "option_target"
            elif ts in XC.get(sym, ()):
                why = "rule_exit"
            if why:
                p.pending_exit = why
        # 3) new signals at this close -> next bar open
        for e in events.get(ts, ()):
            if e[0] not in pos:
                pending.append(e)
        nav = cash + sum(q.n * 100 * om.sell_price(q.mark, costs[q.sym]) for q in pos.values())
        nav_rows.append((ts, nav, len(pos)))
    nav = pd.DataFrame(nav_rows, columns=["ts", "nav", "open"]).set_index("ts")
    nav_daily = nav["nav"].groupby(nav.index.normalize()).last()
    return trades, nav_daily


def summarize(trades: list[SDTrade], nav: pd.Series) -> dict:
    out = {"n": len(trades)}
    if trades:
        r = np.array([t.net_ret for t in trades])
        pnl = np.array([t.pnl for t in trades])
        w, l = r[r > 0], r[r <= 0]
        weeks = pd.Series(r, index=[t.entry_time.to_period("W") for t in trades])
        g = weeks.groupby(level=0).mean()
        out.update(
            win=float((r > 0).mean()), avg_win=float(w.mean()) if len(w) else 0.0, avg_loss=float(l.mean()) if len(l) else 0.0,
            exp=float(r.mean()), median=float(np.median(r)),
            pf_cash=float(pnl[pnl > 0].sum() / -pnl[pnl < 0].sum()) if (pnl < 0).any() else float("inf"),
            t_iid=float(r.mean() / r.std(ddof=1) * np.sqrt(len(r))) if len(r) > 2 and r.std() > 0 else 0.0,
            t_week=float(g.mean() / g.std(ddof=1) * np.sqrt(len(g))) if len(g) > 2 and g.std() > 0 else 0.0,
            hours_median=float(np.median([t.hours_held for t in trades])),
        )
    if nav is not None and len(nav) > 2:
        dd = float((nav / nav.cummax().clip(lower=nav.iloc[0]) - 1).min())
        yrs = (nav.index[-1] - nav.index[0]).days / 365.25
        ret = nav.pct_change().dropna()
        out.update(cagr=float((nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1) if yrs > 0 and nav.iloc[-1] > 0 else -1.0,
                   max_dd=dd, sharpe=float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else 0.0,
                   total=float(nav.iloc[-1] / nav.iloc[0] - 1))
    return out
