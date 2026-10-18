"""Round 7 library: universes (original 15 / new 30), the frozen candidate strategies, and a
real-price replay that keeps the option's 5-minute price PATH so exits on the option price
itself (take-profit / stop) can be evaluated on real prints."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import r4_real_options as R
from oat_research import data as D, engines_v2 as E, indicators as ind, intraday4 as I4, mtf, setups4 as S4, shortdated as SD, strat6 as S6
from r4_common import costs, fmt, load_daily

ORIG = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "JPM", "XOM", "UNH", "COST"]
NEW = ["AVGO", "NFLX", "CRM", "ORCL", "ADBE", "INTC", "QCOM", "MU", "BAC", "WFC", "GS", "C", "V", "MA", "PYPL",
       "DIS", "NKE", "WMT", "HD", "KO", "PEP", "MRK", "PFE", "LLY", "BA", "CAT", "CVX", "UBER", "ABNB", "PLTR"]
ETFS = {"SPY", "QQQ", "IWM"}
REAL = (pd.Timestamp("2024-02-05"), pd.Timestamp("2026-10-16 23:59"))
DEV_END = pd.Timestamp("2025-06-30 23:59")


class Universe:
    def __init__(self, which: str):
        d1all, self.vols = load_daily()
        if which == "orig":
            self.syms = ORIG
            self.m5 = {s: D.load_csv(f"data/m5a/{s}.csv") for s in ORIG}
            d1 = {s: d1all[s] for s in ORIG}
        else:
            self.syms = [s for s in NEW if Path(f"data/m5x/{s}.csv").exists()]
            self.m5 = {s: D.load_csv(f"data/m5x/{s}.csv") for s in self.syms}
            d1 = {s: D.load_csv(f"data/d1x/{s}.csv") for s in self.syms}
        self.d1 = d1
        self.full = {s: I4.daily_asof(self.m5[s], "16:00", d1[s]) for s in self.syms}
        self.asof = {s: I4.daily_asof(self.m5[s], "15:50", d1[s]) for s in self.syms}
        self.seg = {s: I4.segment_bars(self.m5[s]) for s in self.syms}
        spy_asof = I4.daily_asof(D.load_csv("data/m5a/SPY.csv"), "15:50", d1all["SPY"])
        self.ctx = {s: E.Ctx(self.asof[s], spy_asof if s != "SPY" else None) for s in self.syms}
        self.ivs = SD.iv_table(self.full, self.vols)
        self.vix = self.vols["VIX"]
        self._factor = None

    @property
    def factor(self):
        if self._factor is None:
            self._factor = {s: (R.stock_daily(s, "raw") / R.stock_daily(s, "all")).dropna() for s in self.syms}
        return self._factor


# ---------------------------------------------------------------- frozen candidates (rules as published in rounds 4-6)
def sig_mtf_rsi(U, **kw):
    bars = {s: S4.resample(U.m5[s], 15) for s in U.syms}
    sigs = {}
    for s in U.syms:
        f = mtf.mtf_rsi(U.m5[s], kw.get("n", 14), kw.get("ob", 75), kw.get("os_", 25), kw.get("trigger", "reentry"))
        f["dir"] = np.where(f["dir"] > 0, 1, 0)
        if kw.get("regime"):
            up = S6._prev_daily(U.full[s]["close"] > ind.sma(U.full[s]["close"], 200), f)
            f.loc[~(up == True), "dir"] = 0
        sigs[s] = f
    return bars, sigs, 15


def sig_squeeze_daily(U, **kw):
    sigs = {s: I4.to_segments(S6.s3_squeeze_call_daily_asof(U.asof[s], U.full[s], U.vix, pct=kw.get("pct", 0.2),
                                                            vol_mult=kw.get("vol_mult", 1.5)), U.seg[s]) for s in U.syms}
    return {s: U.seg[s] for s in U.syms}, sigs, 0


def sig_trend_dip(U, **kw):
    sigs = {s: I4.to_segments(S4.etf_dip(U.ctx[s], U.vix), U.seg[s]) for s in U.syms}
    return {s: U.seg[s] for s in U.syms}, sigs, 0


CANDIDATES = {
    "MTF-RSI Call": (sig_mtf_rsi, dict(delta=0.5, md=2, ex=(0.75, 1.0, 52))),
    "Squeeze-Breakout Call (daily @15:50)": (sig_squeeze_daily, dict(delta=0.5, md=3, ex=(1.0, 0.5, 30))),
    "Trend-Dip Call @15:50": (sig_trend_dip, dict(delta=0.5, md=2, ex=(0.75, 1.0, None))),
}


def cfg(name, bm, delta, md, ex):
    tgt, stp, hold = ex
    return SD.SDConfig(name, SD.SDExit(target_atr=tgt, stop_atr=stp, use_signal_levels=False, max_hold_bars=hold),
                       target_delta=delta, min_days=md, budget=0.02, max_open=4, bar_minutes=bm, iv_term=SD.calibrated_term)


def trades(U, name, sig_kw=None, **ov):
    fn, base = CANDIDATES[name]
    bars, sigs, bm = fn(U, **(sig_kw or {}))
    p = dict(base); p.update(ov)
    tr, _ = SD.run(bars, sigs, cfg(name, bm, p["delta"], p["md"], p["ex"]), U.full, U.ivs, costs(U.full), *REAL)
    return tr


# ---------------------------------------------------------------- real replay keeping the option path
def replay_path(tr, factor):
    out = []
    for t in tr:
        f = factor[t.symbol]
        day = t.entry_time.normalize()
        if day not in f.index:
            continue
        fx = float(f.loc[day])
        k_raw = t.strike / max(1.0, 100.0 / t.entry_spot) * fx
        cands = []
        for inc in (1.0, 2.5, 5.0, 10.0, 0.5):
            k = round(k_raw / inc) * inc
            if k > 0 and k not in cands:
                cands.append(k)
        got = None
        for ed in (t.expiry.normalize(), t.expiry.normalize() - pd.Timedelta(days=1)):
            syms = [R.occ(t.symbol, ed, t.direction > 0, k) for k in cands]
            bars = R.option_bars(syms, t.entry_time - pd.Timedelta(minutes=5), t.exit_time + pd.Timedelta(minutes=5))
            best = None
            for k, s in zip(cands, syms):
                if s in bars:
                    e = R.fill(bars[s], t.entry_time)
                    if np.isfinite(e) and (best is None or abs(k - k_raw) < abs(best[0] - k_raw)):
                        best = (k, s, e, bars[s])
            if best:
                got = best
                break
        if not got:
            out.append(dict(t=t, ok=False)); continue
        k, s, e, b = got
        at_close = t.exit_time.hour == 16 and t.exit_time.minute == 0
        x = R.fill(b, t.exit_time, before=at_close)
        if not np.isfinite(x):
            later = b[b.index >= t.exit_time]
            x = float(later["vw"].iloc[0]) if len(later) else np.nan
        if not np.isfinite(x) and t.exit_time >= t.expiry - pd.Timedelta(minutes=1):
            x = max(0.0, (t.exit_spot * fx - k) * (1 if t.direction > 0 else -1))
        out.append(dict(t=t, ok=np.isfinite(x), k=k, contract=s, e=e, x=x, path=b[(b.index > t.entry_time) & (b.index < t.exit_time)],
                        raw_spot=t.entry_spot * fx))
    R.CACHE.write_text(json.dumps(R.cache))
    return out


def realize(rows, tp=None, sl=None, hs_mult=1.0, mid=False):
    """Per-trade real return. Optional option-price exits on the real path: when a 5-min bar
    CLOSES >= entry*(1+tp) (or <= entry*(1-sl)) the position is sold at the NEXT bar's VWAP."""
    res = []
    for r in rows:
        if not r["ok"]:
            continue
        t, e, x = r["t"], r["e"], r["x"]
        why = "rule"
        if tp is not None or sl is not None:
            p = r["path"]
            cl = p["c"].to_numpy(); vw = p["vw"].to_numpy()
            for j in range(len(cl)):
                if (tp is not None and cl[j] >= e * (1 + tp)) or (sl is not None and cl[j] <= e * (1 - sl)):
                    x = vw[j + 1] if j + 1 < len(cl) else cl[j]
                    why = "tp" if (tp is not None and cl[j] >= e * (1 + tp)) else "sl"
                    break
        h = (0.015 if t.symbol in ETFS else 0.03) * hs_mult * (0 if mid else 1)
        buy, sell = e * (1 + h), x * (1 - h)
        res.append(dict(sym=t.symbol, entry=t.entry_time, ret=(100 * sell - 0.65 - (100 * buy + 0.65)) / (100 * buy + 0.65),
                        model=t.net_ret, why=why))
    return pd.DataFrame(res)


def stats(df):
    if df is None or len(df) < 3:
        return dict(n=0 if df is None else len(df))
    r = df["ret"].to_numpy()
    w, l = r[r > 0], r[r <= 0]
    eq = np.cumprod(1 + 0.02 * r)
    return dict(n=len(r), win=(r > 0).mean(), aw=w.mean() if len(w) else 0, al=l.mean() if len(l) else 0, exp=r.mean(),
                pf=w.sum() / -l.sum() if l.sum() < 0 else np.inf, t=r.mean() / r.std(ddof=1) * np.sqrt(len(r)),
                dd=float((eq / np.maximum.accumulate(eq) - 1).min()))


HDR = ["| test | n | win | avg win | avg loss | return/trade | PF | t | maxDD* |", "|---|---|---|---|---|---|---|---|---|"]


def row(label, st):
    if st["n"] < 3:
        return f"| {label} | {st['n']} | — | — | — | — | — | — | — |"
    return (f"| {label} | {st['n']} | {fmt(st['win'])} | {fmt(st['aw'], True)} | {fmt(st['al'], True)} | **{fmt(st['exp'], True)}** | "
            f"{fmt(st['pf'])} | {fmt(st['t'])} | {fmt(st['dd'], True)} |")
