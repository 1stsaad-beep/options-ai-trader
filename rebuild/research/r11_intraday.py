"""Round 11 — the capitulation-rebound rule in RELATIVE (z) form on 5m / 15m / 1h / 2h bars (+ daily control).
Stock-level test, pre-registered in results/r11/PREREG.json.  python r11_intraday.py"""
import json, numpy as np, pandas as pd
from pathlib import Path
from oat_research import data as D, indicators as ind, setups4 as S4
from r4_common import load_daily
import r7_lib as L7

OUT = Path("results/r11"); CAL = json.load(open(OUT / "calib.json"))
ZS, ZM = CAL["z_stock"], CAL["z_spy"]

def zret(c, n, look=126):
    sig = np.log(c).diff().rolling(look, min_periods=look).std()
    return (c / c.shift(n) - 1) / (sig * np.sqrt(n))

def bbw_pct(c):
    return ind.rolling_percentile(ind.bb_width(c, 20), 126)

def load(which):
    d1all, _ = load_daily()
    if which == "orig":
        m5 = {s: D.load_csv(f"data/m5a/{s}.csv") for s in L7.ORIG}; d1 = {s: d1all[s] for s in L7.ORIG}
    else:
        ss = [s for s in L7.NEW if Path(f"data/m5x/{s}.csv").exists()]
        m5 = {s: D.load_csv(f"data/m5x/{s}.csv") for s in ss}; d1 = {s: D.load_csv(f"data/d1x/{s}.csv") for s in ss}
    return m5, d1, D.load_csv("data/m5a/SPY.csv"), d1all["SPY"]

def signals(bars, spy_bars, daily=False):
    c = bars["close"]
    sz = zret(spy_bars["close"], 5).reindex(c.index)
    m = (bbw_pct(c) > 0.80) & (zret(c, 20) < ZS) & (sz < ZM)
    return m.fillna(False).to_numpy()

def exits(idx, daily):
    """exit positions for each horizon"""
    n = len(idx); pos = np.arange(n)
    H = {"2 bars": np.minimum(pos + 2, n - 1), "6 bars": np.minimum(pos + 6, n - 1)}
    if not daily:
        day = idx.normalize()
        last = pd.Series(pos, index=idx).groupby(day).transform("max").to_numpy()
        H["same-day close"] = last
        nxt = np.r_[last[1:], last[-1]]            # last of next day = last index of the day after 'last'
        nl = np.minimum(last + 1, n - 1); H["next-day close"] = np.where(last + 1 < n, last[nl], n - 1)
    return H

def trades_for(sym, bars, m, daily):
    c = bars["close"].to_numpy(); idx = bars.index; out = []
    for h, ex in exits(idx, daily).items():
        busy = -1
        for i in np.flatnonzero(m):
            if i <= busy or ex[i] <= i: continue
            out.append((sym, h, idx[i], idx[ex[i]], c[ex[i]] / c[i] - 1)); busy = ex[i]
    return out

def uncond(bars, daily):
    c = bars["close"].to_numpy(); r = {}
    for h, ex in exits(bars.index, daily).items():
        v = c[ex] / c - 1; r[h] = v[ex > np.arange(len(c))]
    return r

def stats(df):
    if len(df) == 0: return dict(n=0)
    r = df.ret.to_numpy(); day = df.groupby(df.entry.dt.normalize()).ret.mean()
    t = day.mean() / day.std(ddof=1) * np.sqrt(len(day)) if len(day) > 2 else np.nan
    return dict(n=len(r), days=len(day), mean=r.mean() * 100, med=np.median(r) * 100, win=(r > 0).mean() * 100, t_day=t)

def main():
    rows, allT = [], []
    for which in ("orig", "new"):
        m5, d1, spy5, spyd = load(which)
        for F in ("1D", 5, 15, 60, 120):
            daily = F == "1D"
            sb = spyd.loc["2016-01-01":] if daily else S4.resample(spy5, F)
            T, U = [], {}
            for s in m5:
                b = d1[s].loc[m5[s].index[0].normalize():] if daily else S4.resample(m5[s], F)
                if daily:  # daily control computed on full daily history, evaluated on the same period as intraday
                    full = d1[s]; mm = signals(full, spyd, True); keep = full.index >= m5[s].index[0].normalize()
                    T += trades_for(s, full, mm & keep, True); b = full[keep]
                else:
                    T += trades_for(s, b, signals(b, sb), False)
                for h, v in uncond(b, daily).items(): U.setdefault(h, []).append(v)
            df = pd.DataFrame(T, columns=["sym", "h", "entry", "exit", "ret"]); df["uni"] = which; df["frame"] = str(F); allT.append(df)
            for h in df.h.unique():
                d = df[df.h == h]; u = np.concatenate(U[h])
                for per, mk in (("all", d.entry > "1900"), ("2016-2020", d.entry < "2021"), ("2021-2026", d.entry >= "2021")):
                    if which == "new" and per != "all": continue
                    st = stats(d[mk]); st.update(uni=which, frame=str(F), h=h, per=per, base=u.mean() * 100); rows.append(st)
            print(which, F, len(df), flush=True)
    R = pd.DataFrame(rows); R.to_csv(OUT / "stock.csv", index=False)
    pd.concat(allT).to_pickle(OUT / "trades.pkl")
    pd.set_option("display.width", 220)
    print(R.round(3).to_string(index=False))

if __name__ == "__main__":
    main()
