"""Round 5 — options test of the two strategies (+ volatility filter).

1) Calibrated model (proxy IV x real-calibrated term multiplier), weekly options, 15-min bars:
   grid chosen on discovery 2016-2020, validation 2021 - 2026-04-15, holdout after.
2) Real option prices (Alpaca prints) 2024-02 -> 2026-10 for the chosen config, with the
   volatility filter: thresholds chosen on dev (2024-02 -> 2025-06), tested on 2025-07 -> 2026-10.
python r5_options.py -> results/r5/OPTIONS.md, results/r5/options.pkl"""
import itertools, json
from pathlib import Path
import numpy as np, pandas as pd
import r4_real_options as R
from oat_research import indicators as ind, mtf, setups4 as S4, shortdated as SD, options_model as om
from r4_common import costs, fmt
from r5_common import DISC, VALID, HOLD, SYMS, load

OUT = Path("results/r5")
RDEV = (pd.Timestamp("2024-02-05"), pd.Timestamp("2025-06-30 23:59"))
RTEST = (pd.Timestamp("2025-07-01"), pd.Timestamp("2026-10-16 23:59"))


def wave_signals(m5, side=1):
    rules = json.load(open(OUT / "wave_rules_15.json"))
    feats = rules["CALL" if side == 1 else "PUT"]["features"]
    cand = pd.read_pickle(OUT / "wave_cand_15.pkl")
    out = {}
    for s in SYMS:
        lo = S4.resample(m5[s], 15)
        c = cand[(cand.sym == s) & (cand.dir == side)]
        for f in feats:
            c = c[c[f].astype(float).fillna(0).astype(bool)]
        d = np.zeros(len(lo), int); d[c.t.astype(int).to_numpy()] = side
        out[s] = S4.frame(lo, d, reason=np.where(d != 0, "MTF wave grandchild W2" if side == 1 else "MTF wave B->C", ""))
    return out


def cfg_for(delta, md, ex):
    tgt, stp, hold = ex
    return SD.SDConfig("r5", SD.SDExit(target_atr=tgt, stop_atr=stp, use_signal_levels=False, max_hold_bars=hold),
                       target_delta=delta, min_days=md, budget=0.02, max_open=5, bar_minutes=15, iv_term=SD.calibrated_term)


GRID = list(itertools.product((0.5, 0.7), (2, 5), ((0.5, 1.0, 26), (0.5, 1.0, 52), (0.75, 1.0, 52), (1.0, 1.0, 104))))


def yz(df, n=20):
    o, h, l, c = df.open, df.high, df.low, df.close
    lo_ = np.log(o / c.shift(1)); lc = np.log(c / o)
    rs = np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o)
    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    return np.sqrt((lo_.rolling(n).var() + k * lc.rolling(n).var() + (1 - k) * rs.rolling(n).mean()) * 252)


def implied_vol(price, s, k, days, is_call, r=0.04):
    t = max(days, 0.02) / 365
    intrinsic = max(0.0, (s - k) if is_call else (k - s))
    if not np.isfinite(price) or price <= intrinsic + 1e-4:
        return np.nan
    lo, hi = 0.01, 5.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        p, _ = om.bs(is_call, s, k, t, mid, r)
        lo, hi = (mid, hi) if p < price else (lo, mid)
    return 0.5 * (lo + hi)


def main():
    m5, full, vols = load()
    ivs = SD.iv_table(full, vols)
    bars = {s: S4.resample(m5[s], 15) for s in SYMS}
    strat = {
        "MTF-RSI Calls (15m re-entry, RSI14 25)": {s: mtf.mtf_rsi(m5[s], 14, 75, 25, "reentry") for s in SYMS},
        "MTF Elliott Calls (developed)": wave_signals(m5, 1),
    }
    for k in list(strat):
        strat[k] = {s: f.assign(dir=np.where(f["dir"] > 0, 1, 0)) for s, f in strat[k].items()}   # calls only
    c1 = costs(full)
    L = ["# Round 5 — options test", "", "## A. Calibrated model (IV proxy × real-calibrated term multiplier), weekly options", "",
         "| strategy | period | chosen delta / min days / (target, stop, max bars) | n | win | exp/trade | PF | t(week) |", "|---|---|---|---|---|---|---|---|"]
    store = {}
    for name, sigs in strat.items():
        b = {s: bars[s] for s in sigs}
        best, scb, grid = None, -9e9, {}
        for g in GRID:
            sm = SD.summarize(*SD.run(b, sigs, cfg_for(*g), full, ivs, c1, *DISC))
            grid[g] = sm
            sc = sm.get("exp", -9) if sm["n"] >= 60 else -9
            if sc > scb: best, scb = g, sc
        store[name] = dict(chosen=best, grid=grid)
        for pn, per in (("DISC", DISC), ("VALID", VALID), ("HOLD", HOLD)):
            tr, nav = SD.run(b, sigs, cfg_for(*best), full, ivs, c1, *per)
            sm = SD.summarize(tr, nav)
            store[name][pn] = sm
            L.append(f"| {name} | {pn} | {best} | {sm['n']} | {fmt(sm.get('win'))} | {fmt(sm.get('exp'), True)} | {fmt(sm.get('pf_cash'))} | {fmt(sm.get('t_week'))} |")
            print(L[-1], flush=True)
    # ---------------- real prices + volatility filter
    factor = {s: (R.stock_daily(s, "raw") / R.stock_daily(s, "all")).dropna() for s in SYMS}
    rv20 = {s: ind.realized_vol(f.close, 20) for s, f in full.items()}
    yz20 = {s: yz(f) for s, f in full.items()}
    atr = {s: ind.atr(f) for s, f in full.items()}

    def prev(series, day):
        sr = series.copy(); sr.index = sr.index.normalize(); j = sr.index.searchsorted(day) - 1
        return float(sr.iloc[j]) if j >= 0 else np.nan

    L += ["", "## B. Real option prices (2024-02 → 2026-10), same trades", ""]
    reals = {}
    for name, sigs in strat.items():
        b = {s: bars[s] for s in sigs}
        tr, _ = SD.run(b, sigs, cfg_for(*store[name]["chosen"]), full, ivs, c1, RDEV[0], RTEST[1])
        df = R.replay(tr, factor)
        R.CACHE.write_text(json.dumps(R.cache))
        ok = df[df.status == "ok"].copy()
        ok["iv"] = [implied_vol(p, s_, k, d, c) for p, s_, k, d, c in zip(ok.real_px, ok.raw_spot, ok.k, ok.days_left, ok.is_call)]
        day = ok.entry.dt.normalize()
        ok["rv20"] = [prev(rv20[s], d) for s, d in zip(ok.sym, day)]
        ok["yz20"] = [prev(yz20[s], d) for s, d in zip(ok.sym, day)]
        ok["atr_pct"] = [prev(atr[s], d) / prev(full[s].close, d) for s, d in zip(ok.sym, day)]
        ok["iv_rv"] = ok.iv / ok.rv20
        ok["iv_yz"] = ok.iv / ok.yz20
        # break-even move: ATRs the stock must move in ONE day to cover one day of decay + the round-trip spread
        be = []
        for r in ok.itertuples():
            if not np.isfinite(r.iv): be.append(np.nan); continue
            hs = 0.015 if r.sym in ("SPY", "QQQ", "IWM") else 0.03
            ask = r.real_px * (1 + hs)
            v1 = om.bs(r.is_call, r.raw_spot, r.k, max(r.days_left - 1, 0.05) / 365, r.iv)
            val1, delta = v1[0] * (1 - hs), abs(om.bs(r.is_call, r.raw_spot, r.k, r.days_left / 365, r.iv)[1])
            be.append((ask - val1) / max(delta, 0.05) / (r.atr_pct * r.raw_spot))
        ok["be_atr"] = be
        ok["per"] = np.where(ok.entry <= RDEV[1], "dev", "test")
        reals[name] = ok
        for per in ("dev", "test"):
            x = ok[ok.per == per]
            L.append(f"- **{name} — {per}:** n {len(x)}, REAL exp {fmt(x.real.mean(), True)}, @VWAP {fmt(x.real_vwap.mean(), True)}, "
                     f"win {fmt((x.real > 0).mean())}, median IV/RV20 {x.iv_rv.median():.2f}, median break-even {x.be_atr.median():.2f} ATR/day, model {fmt(x.model.mean(), True)}")
    L += ["", "## C. Volatility filter — thresholds chosen on dev, applied once to test", "",
          "| strategy | filter | threshold (from dev) | dev kept n / REAL exp | test kept n / REAL exp | test unfiltered |", "|---|---|---|---|---|---|"]
    for name, ok in reals.items():
        dv, ts = ok[ok.per == "dev"], ok[ok.per == "test"]
        for col, grid in (("iv_rv", (1.0, 1.1, 1.2, 1.3, 1.5)), ("iv_yz", (1.0, 1.1, 1.2, 1.3, 1.5)), ("be_atr", (0.2, 0.3, 0.4, 0.5, 0.6))):
            best = None
            for th in grid:
                k = dv[dv[col] <= th]
                if len(k) >= 20 and (best is None or k.real.mean() > best[1]):
                    best = (th, k.real.mean(), len(k))
            if best is None:
                L.append(f"| {name} | {col} | — | <20 trades | — | {fmt(ts.real.mean(), True)} |"); continue
            kt = ts[ts[col] <= best[0]]
            L.append(f"| {name} | {col} ≤ th | {best[0]} | {best[2]} / {fmt(best[1], True)} | {len(kt)} / **{fmt(kt.real.mean(), True)}** | {fmt(ts.real.mean(), True)} |")
    (OUT / "OPTIONS.md").write_text("\n".join(L), encoding="utf-8")
    pd.to_pickle(dict(store=store, reals=reals), OUT / "options.pkl")
    print("\n".join(L))


if __name__ == "__main__":
    main()
