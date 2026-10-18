"""Round 6 — backtest of the three proposed strategies exactly as specified.
python r6_run.py -> results/r6/RESULTS.md, results/r6/store.pkl
All numbers are BACKTESTED. 'model' = Black-Scholes with the real-calibrated IV term multiplier;
'REAL' = the same trades re-priced on real option prints (Alpaca, 2024-02 -> 2026-10)."""
import json
from dataclasses import replace
from pathlib import Path
import numpy as np, pandas as pd
import r4_real_options as R
from oat_research import data as D, intraday4 as I4, indicators as ind, shortdated as SD, strat6 as S6
from r4_common import costs, fmt
from r5_common import DISC, VALID, HOLD, SYMS, load, outcomes, summary
from r5_options import implied_vol

OUT = Path("results/r6"); OUT.mkdir(parents=True, exist_ok=True)
REAL = (pd.Timestamp("2024-02-05"), pd.Timestamp("2026-10-16 23:59"))
RDEV_END = pd.Timestamp("2025-06-30 23:59")
ETFS = {"SPY", "QQQ", "IWM"}
BIG = {"NVDA", "TSLA", "AMD", "META"}

m5, full, vols = load()
vix = vols["VIX"]
ivs = SD.iv_table(full, vols)
d1 = {s: D.load_csv(f"data/d1/{s}.csv") for s in SYMS}
seg = {s: I4.segment_bars(m5[s]) for s in SYMS}
asof = {s: I4.daily_asof(m5[s], "15:50", d1[s]) for s in SYMS}

SPEC = {
    "S1 MTF-Momentum Call": dict(tf=15, delta=0.5, md=2, ex=(0.75, 0.6, 40), iv_max=1.3),
    "S2 Downtrend-Regime Put": dict(tf=15, delta=0.5, md=2, ex=(0.75, 0.5, 52), iv_max=1.4),
    "S3 Squeeze-Breakout Call (60m)": dict(tf=60, delta=0.5, md=3, ex=(1.0, 0.5, 30), iv_max=1.25),
    "S3 Squeeze-Breakout Call (daily @15:50)": dict(tf="seg", delta=0.5, md=3, ex=(1.0, 0.5, 30), iv_max=1.25),
}


def signals(name, **kw):
    out, bars = {}, {}
    for s in SYMS:
        if name.startswith("S1"):
            b, f = S6.s1_mtf_momentum_call(m5[s], full[s], vix, **kw)
        elif name.startswith("S2"):
            b, f = S6.s2_downtrend_put(m5[s], full[s], vix, **kw)
        elif "60m" in name:
            b, f = S6.s3_squeeze_call_hourly(m5[s], full[s], vix, **kw)
        else:
            b = seg[s]
            f = I4.to_segments(S6.s3_squeeze_call_daily_asof(asof[s], full[s], vix, **kw), seg[s])
        bars[s], out[s] = b, f
    return bars, out


def cfg(name):
    sp = SPEC[name]
    tgt, stp, hold = sp["ex"]
    bm = sp["tf"] if isinstance(sp["tf"], int) else 0
    return SD.SDConfig(name, SD.SDExit(target_atr=tgt, stop_atr=stp, use_signal_levels=False, max_hold_bars=hold),
                       target_delta=sp["delta"], min_days=sp["md"], budget=0.02, max_open=4, bar_minutes=bm, iv_term=SD.calibrated_term)


def tstats(rets):
    r = np.asarray(rets, float)
    if len(r) < 3:
        return dict(n=len(r))
    w, l = r[r > 0], r[r <= 0]
    eq = np.cumprod(1 + 0.02 * r)                      # 2% of equity per trade, sequential (approximation)
    dd = float((eq / np.maximum.accumulate(eq) - 1).min())
    return dict(n=len(r), win=(r > 0).mean(), aw=w.mean() if len(w) else 0, al=l.mean() if len(l) else 0, exp=r.mean(),
                pf=w.sum() / -l.sum() if l.sum() < 0 else np.inf, t=r.mean() / r.std(ddof=1) * np.sqrt(len(r)), dd=dd)


def row(label, st):
    if st["n"] < 3:
        return f"| {label} | {st['n']} | — | — | — | — | — | — | — |"
    return (f"| {label} | {st['n']} | {fmt(st['win'])} | {fmt(st['aw'], True)} | {fmt(st['al'], True)} | **{fmt(st['exp'], True)}** | "
            f"{fmt(st['pf'])} | {fmt(st['t'])} | {fmt(st['dd'], True)} |")


HDR = ["| test | n | win | avg win | avg loss | return/trade | PF | t | maxDD* |", "|---|---|---|---|---|---|---|---|---|"]
factor = {s: (R.stock_daily(s, "raw") / R.stock_daily(s, "all")).dropna() for s in SYMS}
rv20 = {s: ind.realized_vol(f.close, 20) for s, f in full.items()}


def prev(series, day):
    sr = series.copy(); sr.index = sr.index.normalize(); j = sr.index.searchsorted(day) - 1
    return float(sr.iloc[j]) if j >= 0 else np.nan


def real(name, bars, sigs):
    tr, _ = SD.run(bars, sigs, cfg(name), full, ivs, costs(full), *REAL)
    df = R.replay(tr, factor)
    R.CACHE.write_text(json.dumps(R.cache))
    ok = df[df.status == "ok"].copy()
    if ok.empty:
        return ok, len(tr)
    ok["iv"] = [implied_vol(p, s_, k, d, c) for p, s_, k, d, c in zip(ok.real_px, ok.raw_spot, ok.k, ok.days_left, ok.is_call)]
    ok["iv_rv"] = ok.iv / [prev(rv20[s], e.normalize()) for s, e in zip(ok.sym, ok.entry)]
    h = np.where(ok.sym.isin(ETFS), 0.015, 0.03)
    ok["real_2x"] = (100 * ok.real_exit_px * (1 - 2 * h) - 0.65 - (100 * ok.real_px * (1 + 2 * h) + 0.65)) / (100 * ok.real_px * (1 + 2 * h) + 0.65)
    return ok, len(tr)


def main():
    L = ["# Round 6 — the three proposed strategies, backtested as specified", "",
         "All results are **backtested**. *model* = Black-Scholes, IV proxy × real-calibrated term multiplier; "
         "*REAL* = the same trades re-priced on real option prints (Alpaca, 2024-02-05 → 2026-10-16), fill = 5-min VWAP ± half-spread (ETF 1.5 %, stock 3 %) + $0.65/contract/side.",
         "Return per trade is on premium paid incl. commissions. maxDD* = sequential equity with 2 % of equity per trade (model rows: daily NAV of the simulator).", ""]
    store = {}
    for name in SPEC:
        sp = SPEC[name]
        bars, sigs = signals(name)
        L += [f"## {name}", ""]
        # A. underlying
        bpd = 26 if sp["tf"] == 15 else 7 if sp["tf"] == 60 else 5
        L += ["**A. Underlying (daily-ATR units, direction-adjusted), entry next bar open**", "",
              "| period | n | +0.5 ATR before stop same day | within 2d | close same day | close day 2 | t(day 2) |", "|---|---|---|---|---|---|---|"]
        for pn, per in (("discovery 2016–20", DISC), ("validation 2021–26/04", VALID), ("holdout 26/04–26/10", HOLD)):
            ws = [outcomes(bars[s], sigs[s], full[s], bpd, per) for s in SYMS]
            ws = [w for w in ws if not w.empty]
            w = pd.concat(ws) if ws else pd.DataFrame()
            s_ = summary(w)
            if s_["n"] == 0:
                L.append(f"| {pn} | 0 | — | — | — | — | — |"); continue
            L.append(f"| {pn} | {s_['n']} | {s_['p05_d1']*100:.0f}% | {s_['p05_d2']*100:.0f}% | {s_['r_eod']:+.3f} | {s_['r_d2']:+.3f} | {fmt(s_['t_d2'])} |")
        # B. model
        L += ["", "**B. Weekly options — model (backtested)**", "", *HDR]
        c1, c2 = costs(full), costs(full, mult=2.0)
        mt = {}
        for pn, per in (("discovery", DISC), ("validation", VALID), ("holdout", HOLD)):
            tr, nav = SD.run(bars, sigs, cfg(name), full, ivs, c1, *per)
            st = tstats([t.net_ret for t in tr]); sm = SD.summarize(tr, nav)
            if st["n"] >= 3: st["dd"] = sm.get("max_dd", np.nan)
            mt[pn] = tr
            L.append(row(f"model — {pn}", st))
        trv = mt["validation"]
        L.append(row("model validation — 2× costs", tstats([t.net_ret for t in SD.run(bars, sigs, cfg(name), full, ivs, c2, *VALID)[0]])))
        top = sorted(trv, key=lambda t: t.net_ret, reverse=True)[:5]
        L.append(row("model validation — without 5 best", tstats([t.net_ret for t in trv if t not in top])))
        L.append(row("model validation — ETFs", tstats([t.net_ret for t in trv if t.symbol in ETFS])))
        L.append(row("model validation — single stocks", tstats([t.net_ret for t in trv if t.symbol not in ETFS])))
        for y in range(2021, 2027):
            L.append(row(f"model — year {y}", tstats([t.net_ret for t in trv + mt["holdout"] if t.entry_time.year == y])))
        # C. real
        ok, ntr = real(name, bars, sigs)
        L += ["", f"**C. Weekly options — REAL option prices 2024-02 → 2026-10 (backtested; {len(ok)} of {ntr} trades matched to a traded contract)**", "", *HDR]
        if len(ok):
            filt = ok[ok.iv_rv <= sp["iv_max"]]
            L.append(row("REAL — all", tstats(ok.real)))
            L.append(row(f"REAL — with IV/RV20 ≤ {sp['iv_max']} (as specified)", tstats(filt.real)))
            L.append(row("REAL — dev 2024-02→2025-06", tstats(ok[ok.entry <= RDEV_END].real)))
            L.append(row("REAL — test 2025-07→2026-10", tstats(ok[ok.entry > RDEV_END].real)))
            L.append(row("REAL — filtered, test only", tstats(filt[filt.entry > RDEV_END].real)))
            L.append(row("REAL — 2× half-spread", tstats(ok.real_2x)))
            L.append(row("REAL — at VWAP, no spread", tstats(ok.real_vwap)))
            L.append(row("REAL — without 5 best", tstats(ok.real.drop(ok.real.nlargest(5).index))))
            L.append(row("REAL — ETFs", tstats(ok[ok.sym.isin(ETFS)].real)))
            L.append(row("REAL — single stocks", tstats(ok[~ok.sym.isin(ETFS)].real)))
            L.append(row("REAL — without NVDA/TSLA/AMD/META", tstats(ok[~ok.sym.isin(BIG)].real)))
            for y in (2024, 2025, 2026):
                L.append(row(f"REAL — year {y}", tstats(ok[ok.entry.dt.year == y].real)))
            L.append(f"\nModel on the same matched trades: {fmt(ok.model.mean(), True)} per trade; median real/model entry price: "
                     f"{(ok.real_px / ok.model_px).median():.2f}; median IV/RV20 at entry: {ok.iv_rv.median():.2f}.")
        store[name] = dict(model=mt, real=ok)
        L.append("")
        print(name, "done", flush=True)
        (OUT / "RESULTS.md").write_text("\n".join(L), encoding="utf-8")
    pd.to_pickle(store, OUT / "store.pkl")


if __name__ == "__main__":
    main()
