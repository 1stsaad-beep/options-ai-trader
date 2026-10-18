"""Round 8 — test of the three strategies in 'Options_AI_Trader_Detailed_Research_AR.pdf' (literal rules).
python r8_run.py A|B|C  -> results/r8/{X}.md, results/r8/{X}.pkl
Stages: (1) underlying behaviour of the signals, (2) calibrated model, weekly contracts 3-6 DTE,
(3) REAL option prints 2024-02 -> 2026-10 with the report's contract filters (IV/RV <= 1.30, premium cap
in ATR, and for A: IV <= 0.80 x the same contract's pre-event IV), (4) registered robustness."""
import json, sys
from dataclasses import replace
from pathlib import Path
import numpy as np, pandas as pd
import r4_real_options as R
import r7_lib as L7
from oat_research import data as D, indicators as ind, intraday4 as I4, options_model as om, shortdated as SD, strat8 as S8
from r4_common import costs, fmt, load_daily
from r5_options import implied_vol

OUT = Path("results/r8"); OUT.mkdir(parents=True, exist_ok=True)
DISC = (pd.Timestamp("2016-01-01"), pd.Timestamp("2020-12-31 23:59"))
VALID = (pd.Timestamp("2021-01-01"), pd.Timestamp("2026-04-15 23:59"))
HOLD = (pd.Timestamp("2026-04-16"), pd.Timestamp("2026-10-16 23:59"))
REAL = L7.REAL
DEV_END = L7.DEV_END
ETFS = {"SPY", "QQQ", "IWM"}
BIG = {"NVDA", "TSLA", "AMD", "META"}

d1all, vols = load_daily()
VIX = vols["VIX"]


def load5(s):
    p = Path(f"data/m5a/{s}.csv")
    return D.load_csv(p if p.exists() else f"data/m5x/{s}.csv")


def daily_of(s, m5):
    d1 = d1all[s] if s in d1all else D.load_csv(f"data/d1x/{s}.csv")
    return I4.daily_asof(m5, "16:00", d1)


SPEC = {
    "A": dict(syms=["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "AVGO", "NFLX", "CRM", "ADBE"], cap=0.70, side=1),
    "B": dict(syms=["SPY", "QQQ", "IWM"], cap=0.60, side=-1),
    "C": dict(syms=["AAPL", "MSFT", "NVDA", "AMD", "AMZN", "GOOGL", "META", "TSLA"], cap=0.70, side=1),
}


class Data:
    def __init__(self, syms):
        self.m5 = {s: load5(s) for s in set(syms) | {"SPY", "QQQ"}}
        self.daily = {s: daily_of(s, self.m5[s]) for s in self.m5}
        self.ivs = SD.iv_table(self.daily, vols)
        self._sect = None

    @property
    def sectors(self):
        if self._sect is None:
            self._sect = {p.stem: D.load_csv(p) for p in sorted(Path("data/m5s").glob("*.csv"))}
        return self._sect


def signals(X, Dt, syms, **kw):
    out = {}
    for s in syms:
        if X == "A":
            out[s] = S8.strat_a(Dt.m5[s], Dt.daily[s], Dt.daily["SPY"], VIX, **kw)
        elif X == "B":
            out[s] = S8.strat_b(Dt.m5[s], Dt.daily[s], Dt.daily["SPY"], Dt.sectors, VIX, **kw)
        else:
            out[s] = S8.strat_c(Dt.m5[s], Dt.daily[s], Dt.m5["QQQ"], Dt.daily["QQQ"], VIX, **kw)
    return out


def cfg(X, model_filters=True, delta=0.5, ivrv=1.3, dte=(3, 6)):
    return SD.SDConfig(X, SD.SDExit(target_atr=None, stop_atr=None, use_signal_levels=True), target_delta=delta, min_days=dte[0], budget=0.02,
                       max_open=3, bar_minutes=5, iv_term=SD.calibrated_term, max_days=dte[1], target_days=4,
                       daily_expiry_syms=("SPY", "QQQ"), premium_cap_atr=SPEC[X]["cap"] if model_filters else None,
                       ivrv_max=ivrv if model_filters else None)


def tstats(r):
    return L7.stats(pd.DataFrame({"ret": np.asarray(r, float)})) if len(r) >= 3 else dict(n=len(r))


def und_line(label, tr):
    if len(tr) < 3:
        return f"| {label} | {len(tr)} | — | — | — | — |"
    mv = np.array([t.direction * (t.exit_spot - t.entry_spot) for t in tr])
    reasons = pd.Series([t.exit_reason for t in tr]).value_counts(normalize=True)
    return (f"| {label} | {len(tr)} | {np.mean(mv / np.array([t.entry_spot for t in tr])) * 100:+.3f}% | "
            f"{reasons.get('underlying_target', 0) * 100:.0f}% | {reasons.get('underlying_stop', 0) * 100:.0f}% | "
            f"{(1 - reasons.get('underlying_target', 0) - reasons.get('underlying_stop', 0)) * 100:.0f}% |")


def real_filters(X, rows, Dt):
    """Apply the report's contract filters on REAL prints (IV/RV, premium cap; A: IV drop vs pre-event)."""
    keep = []
    for r in rows:
        if not r["ok"]:
            continue
        t = r["t"]
        hs = 0.015 if t.symbol in ETFS else 0.03
        day = t.entry_time.normalize()
        dly = Dt.daily[t.symbol]
        prevd = dly.index[dly.index < day]
        if len(prevd) < 21:
            continue
        ref_day = prevd[-2] if X == "A" else prevd[-1]          # A: the session BEFORE the event session
        a0 = float(ind.atr(dly).loc[ref_day])
        rv = float(ind.realized_vol(dly["close"], 20).loc[ref_day])
        fx = r["raw_spot"] / t.entry_spot
        dl = (t.expiry - t.entry_time).total_seconds() / 86400
        iv = implied_vol(r["e"], r["raw_spot"], r["k"], dl, t.direction > 0)
        ask = r["e"] * (1 + hs)
        r["iv"], r["ivrv"], r["cost_atr"] = iv, iv / rv if rv > 0 else np.nan, (ask + 0.0065) / (a0 * fx)
        ok = np.isfinite(iv) and r["ivrv"] <= 1.30 and r["cost_atr"] <= SPEC[X]["cap"]
        if ok and X == "A":
            # same contract, 15:45 on the last session before the event session (entry day - 2 sessions)
            ev_prev = prevd[-2] if len(prevd) >= 2 else None
            ref = None
            if ev_prev is not None:
                b = R.option_bars([r["contract"]], ev_prev + pd.Timedelta(hours=15, minutes=30), ev_prev + pd.Timedelta(hours=16))
                if r["contract"] in b and len(b[r["contract"]]):
                    px = float(b[r["contract"]]["vw"].iloc[-1])
                    spot_prev = float(Dt.daily[t.symbol]["close"].loc[ev_prev]) * fx
                    dl0 = (t.expiry - (ev_prev + pd.Timedelta(hours=15, minutes=45))).total_seconds() / 86400
                    ref = implied_vol(px, spot_prev, r["k"], dl0, True)
            r["pre_iv"] = ref
            ok = ref is not None and np.isfinite(ref) and iv <= 0.80 * ref
        r["pass"] = bool(ok)
        keep.append(r)
    R.CACHE.write_text(json.dumps(R.cache))
    return keep


def realize_list(rows, only_pass=True, **kw):
    sel = [r for r in rows if r.get("pass") or not only_pass]
    return L7.realize(sel, **kw)


def main(X):
    sp = SPEC[X]
    syms = sp["syms"]
    Dt = Data(syms)
    sigs = signals(X, Dt, syms)
    bars = {s: Dt.m5[s] for s in syms}
    c1, c2 = costs(Dt.daily), costs(Dt.daily, mult=2.0)
    nsig = sum(int((f["dir"] != 0).sum()) for f in sigs.values())
    L = [f"# Strategy {X} — literal test (backtested)", "", f"Signals 2016–2026 (all symbols): {nsig}", "",
         "## 1. Underlying (model trades, before option filters)", "",
         "| period | trades | underlying move/trade (dir.) | hit target | hit stop | time exit |", "|---|---|---|---|---|---|"]
    trs_nf = {}
    for pn, per in (("discovery 2016–20", DISC), ("validation 2021–26/04", VALID), ("holdout 26/04–26/10", HOLD)):
        tr, _ = SD.run(bars, sigs, cfg(X, model_filters=False), Dt.daily, Dt.ivs, c1, *per)
        trs_nf[pn] = tr
        L.append(und_line(pn, tr))
    L += ["", "## 2. Calibrated model, weekly options 3–6 DTE, report's filters (model IV/RV ≤ 1.30, premium cap)", "", *L7.HDR]
    model = {}
    for pn, per in (("discovery", DISC), ("validation", VALID), ("holdout", HOLD)):
        tr, nav = SD.run(bars, sigs, cfg(X), Dt.daily, Dt.ivs, c1, *per)
        model[pn] = tr
        L.append(L7.row(f"model — {pn}", tstats([t.net_ret for t in tr])))
    L.append(L7.row("model — discovery+validation, no contract filters", tstats([t.net_ret for t in trs_nf["discovery 2016–20"] + trs_nf["validation 2021–26/04"]])))
    trv = model["validation"]
    L.append(L7.row("model validation — 2× costs", tstats([t.net_ret for t in SD.run(bars, sigs, cfg(X), Dt.daily, Dt.ivs, c2, *VALID)[0]])))
    for y in range(2016, 2027):
        yy = [t.net_ret for t in model["discovery"] + model["validation"] + model["holdout"] if t.entry_time.year == y]
        if yy:
            L.append(L7.row(f"model — year {y}", tstats(yy)))
    # REAL
    tr, _ = SD.run(bars, sigs, cfg(X, model_filters=False), Dt.daily, Dt.ivs, c1, *REAL)
    rows = L7.replay_path(tr, {s: (R.stock_daily(s, "raw") / R.stock_daily(s, "all")).dropna() for s in syms})
    rows = real_filters(X, rows, Dt)
    allr = realize_list(rows, only_pass=False)
    df = realize_list(rows)
    L += ["", f"## 3. REAL option prices 2024-02 → 2026-10 ({len(tr)} trades before filters; {len(allr)} matched to a traded contract; "
          f"{len(df)} pass the report's contract filters)", "", *L7.HDR]
    L.append(L7.row("REAL — all matched (no contract filters)", L7.stats(allr)))
    L.append(L7.row("REAL — with the report's filters (THE RULE)", L7.stats(df)))
    if len(df):
        per = lambda d, lo, hi: d[(d.entry > lo) & (d.entry <= hi)]
        L.append(L7.row("REAL rule — dev 2024-02→2025-06", L7.stats(per(df, pd.Timestamp("2000-01-01"), DEV_END))))
        L.append(L7.row("REAL rule — test 2025-07→2026-10", L7.stats(per(df, DEV_END, pd.Timestamp("2030-01-01")))))
        L.append(L7.row("REAL rule — 2× half-spread", L7.stats(realize_list(rows, hs_mult=2.0))))
        L.append(L7.row("REAL rule — at VWAP", L7.stats(realize_list(rows, mid=True))))
        L.append(L7.row("REAL rule — without 5 best", L7.stats(df.drop(df["ret"].nlargest(5).index))))
        L.append(L7.row("REAL rule — ETFs", L7.stats(df[df.sym.isin(ETFS)])))
        L.append(L7.row("REAL rule — stocks", L7.stats(df[~df.sym.isin(ETFS)])))
        L.append(L7.row("REAL rule — without NVDA/TSLA/AMD/META", L7.stats(df[~df.sym.isin(BIG)])))
        for y in (2024, 2025, 2026):
            L.append(L7.row(f"REAL rule — year {y}", L7.stats(df[df.entry.dt.year == y])))
    fails = pd.Series([("iv/rv" if r.get("ivrv", 0) > 1.3 else "cap" if r.get("cost_atr", 0) > sp["cap"] else "iv-drop/pre-event")
                       for r in rows if not r.get("pass")]).value_counts()
    L += ["", "Rejected by the contract filters: " + ", ".join(f"{k} {v}" for k, v in fails.items())]
    (OUT / f"{X}.md").write_text("\n".join(L), encoding="utf-8")
    pd.to_pickle(dict(model=model, rows=[{k: v for k, v in r.items() if k != "path"} for r in rows]), OUT / f"{X}.pkl")
    print("\n".join(L))


if __name__ == "__main__":
    main(sys.argv[1])
