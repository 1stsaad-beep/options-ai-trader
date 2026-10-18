"""Round 8 — development of A/B/C after the literal test produced too few trades.
Pre-declared grid (written before running). Selection on DISCOVERY 2016-2020 only, by the underlying
expectancy of the model trades in ATR units (target/stop/time exits of the rule), n >= 40.
The chosen variant is then judged once on: model validation 2021-2026/04, holdout, and REAL option
prints 2024-02 -> 2026-10 (with and without the report's contract filters), plus a symbol set never
used in rounds 0-6 (new 30) where data allow.  Contract window widened to 3-8 DTE (stocks have only
Friday weeklies; 3-6 DTE allows entries on Mon/Tue only).
python r8_dev.py A|B|C"""
import itertools, json, sys
import numpy as np, pandas as pd
import r4_real_options as R
import r7_lib as L7
import r8_run as M
from oat_research import indicators as ind, shortdated as SD
from r4_common import costs

GRIDS = {
    "A": dict(hold_band=[0.25, 0.5, 99], gap_hi=[1.5, 3.0], spacing=[40, 1], clv_min=[0.75, 0.5]),
    "B": dict(breadth_min=[7, 5], drop=[0.5, 0.3], vol_mult=[1.5, 1.2]),
    "C": dict(z_max=[-2.0, -1.5, -1.0], lag_atr=[0.9, 0.5, 0.0], ref_up=[0.4, 0.2], confirm=[0.10, 0.0]),
}
UNIV = {
    "A": dict(dev=M.SPEC["A"]["syms"], oos=["ORCL", "INTC", "QCOM", "MU", "PYPL", "UBER", "ABNB", "PLTR", "BAC", "JPM", "WMT", "COST"]),
    "B": dict(dev=["SPY", "QQQ", "IWM"], oos=[]),
    "C": dict(dev=M.SPEC["C"]["syms"], oos=["AVGO", "NFLX", "CRM", "ADBE", "ORCL", "QCOM", "MU", "INTC"]),
}


def trim(bars, sigs, days=12):
    """Speed: keep only bars within `days` calendar days after each signal (positions cannot exist elsewhere)."""
    out, so = {}, {}
    for s, b in bars.items():
        f = sigs[s]
        sd = f.index[f["dir"] != 0].normalize().unique()
        if len(sd) == 0:
            out[s], so[s] = b.iloc[:0], f.iloc[:0]
            continue
        keep = np.zeros(len(b), bool)
        bd = b.index.normalize()
        for d in sd:
            keep |= (bd >= d) & (bd <= d + pd.Timedelta(days=days))
        out[s], so[s] = b[keep], f[keep]
    return out, so


def RUN(b, sigs, c, Dt, c1, per):
    b2, s2 = trim(b, sigs)
    b2 = {k: v for k, v in b2.items() if len(v)}
    if not b2:
        return [], None
    return SD.run(b2, {k: s2[k] for k in b2}, c, Dt.daily, Dt.ivs, c1, *per)


def cfg(X, filters):
    c = M.cfg(X, model_filters=filters, dte=(3, 8))
    return c


def und_exp(tr, Dt):
    if len(tr) < 3:
        return np.nan, len(tr)
    out = []
    for t in tr:
        d = Dt.daily[t.symbol]
        a = ind.atr(d).shift(1)
        a.index = a.index.normalize()
        av = a.get(t.entry_time.normalize(), np.nan)
        out.append(t.direction * (t.exit_spot - t.entry_spot) / av)
    return float(np.nanmean(out)), len(tr)


def main(X):
    syms = UNIV[X]["dev"]
    Dt = M.Data(syms + UNIV[X]["oos"])
    bars = {s: Dt.m5[s] for s in Dt.m5}
    c1 = costs(Dt.daily)
    keys = list(GRIDS[X])
    L = [f"# Strategy {X} — development (selection on discovery 2016–2020, underlying expectancy in ATR)", "",
         "| variant | DISC trades | DISC underlying E[ATR] | VALID trades | VALID underlying E[ATR] |", "|---|---|---|---|---|"]
    best = None
    res = []
    for vals in itertools.product(*GRIDS[X].values()):
        kw = dict(zip(keys, vals))
        sigs = M.signals(X, Dt, syms, **kw)
        b = {s: bars[s] for s in syms}
        trd, _ = RUN(b, sigs, cfg(X, False), Dt, c1, M.DISC)
        trv, _ = RUN(b, sigs, cfg(X, False), Dt, c1, M.VALID)
        ed, nd = und_exp(trd, Dt); ev, nv = und_exp(trv, Dt)
        res.append((kw, ed, nd, ev, nv))
        L.append(f"| {kw} | {nd} | {ed:+.3f} | {nv} | {ev:+.3f} |")
        print(L[-1], flush=True)
        if nd >= 40 and np.isfinite(ed) and (best is None or ed > best[1]):
            best = (kw, ed)
    if best is None:   # fall back to the largest discovery sample
        best = (max(res, key=lambda r: r[2])[0], np.nan)
    kw = best[0]
    L += ["", f"**Chosen on discovery:** {kw}", ""]
    sigs = M.signals(X, Dt, syms, **kw)
    b = {s: bars[s] for s in syms}
    L += ["## Judgement of the developed variant (backtested)", "", *L7.HDR]
    for pn, per in (("model discovery", M.DISC), ("model validation", M.VALID), ("model holdout", M.HOLD)):
        for filt in (False, True):
            tr, _ = RUN(b, sigs, cfg(X, filt), Dt, c1, per)
            L.append(L7.row(f"{pn} — {'with' if filt else 'without'} contract filters", M.tstats([t.net_ret for t in tr])))
    for uname, us in (("development symbols", syms), ("NEW symbols (never used)", UNIV[X]["oos"])):
        if not us:
            continue
        s2 = sigs if us is syms else M.signals(X, Dt, us, **kw)
        tr, _ = RUN({s: bars[s] for s in us}, s2, cfg(X, False), Dt, c1, M.REAL)
        rows = L7.replay_path(tr, {s: (R.stock_daily(s, "raw") / R.stock_daily(s, "all")).dropna() for s in us})
        rows = M.real_filters(X, rows, Dt)
        allr, df = M.realize_list(rows, only_pass=False), M.realize_list(rows)
        L.append(L7.row(f"REAL {uname} — all matched", L7.stats(allr)))
        L.append(L7.row(f"REAL {uname} — with report's contract filters", L7.stats(df)))
        if len(allr):
            per = lambda d, lo, hi: d[(d.entry > lo) & (d.entry <= hi)]
            L.append(L7.row(f"REAL {uname} — all matched, dev 24/02–25/06", L7.stats(per(allr, pd.Timestamp('2000-01-01'), M.DEV_END))))
            L.append(L7.row(f"REAL {uname} — all matched, test 25/07–26/10", L7.stats(per(allr, M.DEV_END, pd.Timestamp('2030-01-01')))))
            L.append(L7.row(f"REAL {uname} — all matched, 2× half-spread", L7.stats(M.realize_list(rows, only_pass=False, hs_mult=2.0))))
            L.append(L7.row(f"REAL {uname} — all matched, without 5 best", L7.stats(allr.drop(allr['ret'].nlargest(5).index))))
    (M.OUT / f"{X}_DEV.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[-20:]))


if __name__ == "__main__":
    main(sys.argv[1])
