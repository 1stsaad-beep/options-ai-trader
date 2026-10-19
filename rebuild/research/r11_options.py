"""Round 11 — real weekly-call replay for the frame that passed the stock test (2h, 2 bars) + exploratory 2h/6 bars and 1h/6 bars.
Entry = end of signal bar (fill = VWAP of next 5-min option bar); exit = end of exit bar."""
import sys, json, numpy as np, pandas as pd
from types import SimpleNamespace as NS
import r4_real_options as R, r7_lib as L7
from oat_research import shortdated as SD
from pathlib import Path
OUT = Path("results/r11"); R.CACHE = OUT / "opt_cache_r11.json"
if R.CACHE.exists(): R.cache.update(json.loads(R.CACHE.read_text()))
T = pd.read_pickle(OUT / "trades.pkl")
CASES = [("120", "2 bars"), ("120", "6 bars"), ("60", "6 bars")]

def bar_end(ts, F):
    e = ts + pd.Timedelta(minutes=F); c = ts.normalize() + pd.Timedelta(hours=16)
    return min(e, c)

def mk(r, F, spot_now):
    et = bar_end(r.entry, F); xt = bar_end(r.exit, F)
    if et.hour == 16: et = et - pd.Timedelta(minutes=5)      # signal on the last bar: buy in the last 5 minutes
    s = spot_now(r.sym, r.entry); x = s * (1 + r.ret); f = max(1.0, 100.0 / s)
    return NS(symbol=r.sym, entry_time=et, exit_time=xt, strike=s * f, expiry=SD.friday_expiry(et, 3), direction=1,
              entry_spot=s, exit_spot=x, net_ret=0.0)

def main():
    res = []
    for uni in ("orig", "new"):
        m5 = {}
        def spot(sym, ts):
            if sym not in m5:
                from oat_research import data as D
                m5[sym] = D.load_csv(f"data/{'m5a' if uni == 'orig' else 'm5x'}/{sym}.csv")
            return float(m5[sym]["close"].asof(ts + pd.Timedelta(minutes=F - 5)))
        U = L7.Universe(uni)
        for Fs, h in CASES:
            F = int(Fs)
            d = T[(T.uni == uni) & (T.frame == Fs) & (T.h == h) & (T.entry >= L7.REAL[0])]
            tr = [mk(r, F, spot) for r in d.itertuples()]
            rows = L7.replay_path(tr, U.factor)
            for hs in (1.0, 2.0):
                df = L7.realize(rows, hs_mult=hs)
                df["uni"], df["frame"], df["h"], df["hs"] = uni, Fs, h, hs
                df = df.merge(d[["sym", "entry", "ret"]].assign(entry=[t.entry_time for t in tr]).rename(columns={"ret": "stock"}), on=["sym", "entry"], how="left")
                res.append(df)
            print(uni, Fs, h, len(tr), sum(r["ok"] for r in rows), flush=True)
            pd.concat(res).to_pickle(OUT / "options.pkl")
    A = pd.concat(res)
    g = A.groupby(["uni", "frame", "h", "hs"])
    S = g.apply(lambda x: pd.Series(dict(n=len(x), mean=x.ret.mean() * 100, med=x.ret.median() * 100, win=(x.ret > 0).mean() * 100,
                                         t=x.ret.mean() / x.ret.std(ddof=1) * np.sqrt(len(x)), stock=x.stock.mean() * 100,
                                         no_top10=x.ret.sort_values().iloc[:-10].mean() * 100)))
    print(S.round(2).to_string()); S.to_csv(OUT / "options_summary.csv")

if __name__ == "__main__":
    main()
