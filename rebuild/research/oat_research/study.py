"""Signal-quality study and walk-forward evaluation."""
from __future__ import annotations

import itertools
from dataclasses import replace

import numpy as np
import pandas as pd

from . import backtest as bt
from .indicators import atr


# ---------------------------------------------------------------------------
# Signal quality on the underlying (independent of option modelling)
# ---------------------------------------------------------------------------

def signal_quality(data: dict[str, pd.DataFrame], signals: dict[str, pd.DataFrame], horizon: int = 10,
                   up_atr: float = 2.0, dn_atr: float = 1.0, start=None, end=None) -> dict:
    """For every signal at close t (entry = open t+1):
    * fwd5/fwd10 : directional return to close t+5 / t+10, in ATR(t) units
    * hit        : +up_atr ATR reached before -dn_atr ATR within `horizon` bars
                   (the kind of fast move a long option needs)
    * mfe / mae  : max favourable / adverse excursion within horizon (ATR units)
    """
    rows = []
    for sym, sig in signals.items():
        df = data[sym]
        a = atr(df).to_numpy()
        o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
        dirs = sig["dir"].to_numpy()
        idx = df.index
        for t in np.nonzero(dirs)[0]:
            if t + horizon + 1 >= len(df) or not np.isfinite(a[t]) or a[t] <= 0:
                continue
            if (start is not None and idx[t] < start) or (end is not None and idx[t] > end):
                continue
            d = dirs[t]
            e = o[t + 1]
            fav = (h[t + 1:t + 1 + horizon] - e) / a[t] if d > 0 else (e - l[t + 1:t + 1 + horizon]) / a[t]
            adv = (e - l[t + 1:t + 1 + horizon]) / a[t] if d > 0 else (h[t + 1:t + 1 + horizon] - e) / a[t]
            hit = 0
            for f, ad in zip(fav, adv):
                if ad >= dn_atr:
                    break
                if f >= up_atr:
                    hit = 1
                    break
            rows.append({
                "sym": sym, "date": idx[t], "dir": d,
                "fwd5": d * (c[t + 5] - e) / a[t], "fwd10": d * (c[t + 10] - e) / a[t],
                "mfe": fav.max(), "mae": adv.max(), "hit": hit,
            })
    if not rows:
        return {"n": 0}
    r = pd.DataFrame(rows)
    return {
        "n": len(r), "calls": int((r.dir > 0).sum()), "puts": int((r.dir < 0).sum()),
        "fwd5": r.fwd5.mean(), "fwd10": r.fwd10.mean(), "hit": r.hit.mean(),
        "mfe": r.mfe.mean(), "mae": r.mae.mean(),
        "t_fwd10": r.fwd10.mean() / (r.fwd10.std() / np.sqrt(len(r))) if len(r) > 2 and r.fwd10.std() > 0 else 0,
        "rows": r,
    }


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------

def objective(trades) -> float:
    """t-statistic-like score of per-trade premium returns (needs >= 12 trades)."""
    if len(trades) < 12:
        return -np.inf
    r = np.array([t.ret for t in trades])
    sd = r.std()
    return r.mean() / sd * np.sqrt(len(r)) if sd > 0 else -np.inf


def walk_forward(data, make_signals, grid: dict, base_cfg: bt.StrategyConfig, costs, train_years=3, test_years=1,
                 first_test_year=None, last_year=None, cost_overrides=None, verbose=True):
    """make_signals(params: dict) -> dict[sym, signal frame] (computed on the full
    history; every rule is causal so this does not leak). Parameters are chosen on
    the train window only, then applied unchanged to the following test window.
    Returns concatenated out-of-sample trades and a per-window log."""
    years = sorted({d.year for df in data.values() for d in df.index})
    first_test_year = first_test_year or years[0] + train_years + 1  # +1 year for indicator warm-up
    last_year = last_year or years[-1]
    keys = list(grid)
    combos = [dict(zip(keys, v)) for v in itertools.product(*[grid[k] for k in keys])]
    cache = {}
    oos_trades, log = [], []
    y = first_test_year
    while y <= last_year:
        tr_s, tr_e = pd.Timestamp(y - train_years, 1, 1), pd.Timestamp(y - 1, 12, 31)
        te_s, te_e = pd.Timestamp(y, 1, 1), pd.Timestamp(min(y + test_years - 1, last_year), 12, 31)
        best, best_score = None, -np.inf
        for combo in combos:
            key = tuple(sorted(combo.items()))
            if key not in cache:
                cache[key] = make_signals(combo)
            cfg = _apply(base_cfg, combo)
            trades, _ = bt.run(data, cache[key], cfg, costs, tr_s, tr_e, cost_overrides=cost_overrides)
            sc = objective(trades)
            if sc > best_score:
                best, best_score = combo, sc
        if best is None:
            best = combos[0]
        key = tuple(sorted(best.items()))
        cfg = _apply(base_cfg, best)
        trades, curve = bt.run(data, cache[key], cfg, costs, te_s, te_e, cost_overrides=cost_overrides)
        m = bt.metrics(trades, curve)
        log.append({"test": f"{te_s.year}-{te_e.year}", "params": best, "train_score": best_score, **{
            k: m.get(k) for k in ("trades", "win_rate", "expectancy", "profit_factor", "total_return", "max_dd")}})
        if verbose:
            print(f"  WF {te_s.year}: params={best} train={best_score:.2f} -> trades={m.get('trades')} "
                  f"exp={m.get('expectancy', float('nan')):.3f} ret={m.get('total_return', float('nan')):.3f}")
        oos_trades.extend(trades)
        y += test_years
    return oos_trades, log


def _apply(cfg: bt.StrategyConfig, combo: dict) -> bt.StrategyConfig:
    """Keys prefixed 'x_' go to ExitRules, 'c_' to StrategyConfig; others are signal params."""
    ex = cfg.exits
    ex_kw = {k[2:]: v for k, v in combo.items() if k.startswith("x_")}
    c_kw = {k[2:]: v for k, v in combo.items() if k.startswith("c_")}
    return replace(cfg, exits=replace(ex, **ex_kw), **c_kw)


def oos_equity(trades, alloc: float = 0.04, initial: float = 100_000.0) -> pd.Series:
    """Sequential fixed-fraction curve over OOS trades ordered by exit date: each
    trade puts `alloc` of equity into premium (2% risk with a 50% premium stop =
    4%). Ignores overlap between trades — an approximation for comparing engines."""
    eq, pts = initial, []
    for t in sorted(trades, key=lambda t: t.exit_date):
        eq *= 1 + alloc * t.ret
        pts.append((t.exit_date, eq))
    return pd.Series(dict(pts), dtype=float)


def curve_dd(curve: pd.Series) -> float:
    if curve.empty:
        return 0.0
    return float((curve / curve.cummax() - 1).min())


def trade_stats(trades) -> dict:
    if not trades:
        return {"trades": 0}
    r = np.array([t.ret for t in trades])
    w, lo = r[r > 0], r[r <= 0]
    years = {}
    for t in trades:
        years.setdefault(t.exit_date.year, []).append(t.ret)
    return {
        "trades": len(r), "win_rate": (r > 0).mean(), "avg_win": w.mean() if len(w) else 0,
        "avg_loss": lo.mean() if len(lo) else 0, "expectancy": r.mean(), "median": float(np.median(r)),
        "payoff": (w.mean() / -lo.mean()) if len(w) and len(lo) and lo.mean() < 0 else np.nan,
        "profit_factor": w.sum() / -lo.sum() if lo.sum() < 0 else np.inf,
        "t_stat": r.mean() / (r.std() / np.sqrt(len(r))) if len(r) > 2 and r.std() > 0 else 0,
        "positive_years": sum(np.mean(v) > 0 for v in years.values()), "years": len(years),
        "by_year": {y: (len(v), float(np.mean(v))) for y, v in sorted(years.items())},
    }
