"""Round 4b: does the REAL implied volatility at entry separate winners from losers?
IV is inverted from the real entry print (Black-Scholes, raw spot, listed strike, exact time
to expiry); RV = 20-day realised vol known the day before. Rule candidates are chosen on
dev (2024-02 -> 2025-06) and checked on test (2025-07 -> 2026-10).
python r4_iv_filter.py -> results/r4/IV_FILTER.md"""
import json, math
import numpy as np, pandas as pd
import r4_real_options as R
from r4_real_dev import DEV, TEST, trades_for, stats
from r4_final import build
from oat_research import options_model as om, indicators as ind
from r4_common import OUT, fmt

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

B = build()
factor = {s: (R.stock_daily(s, "raw") / R.stock_daily(s, "all")).dropna() for s in B["full"]}
rv = {s: ind.realized_vol(df["close"], 20).shift(1) for s, df in B["full"].items()}
CONF = {"A Trend-dip @15:50": {}, "C ORB-5 in play": {}, "D Noise-area momentum": {},
        "Pre-FOMC (ETFs)": {"delta": 0.5, "exit_at": "12:00"}}
L = ["# Real implied volatility at entry as a filter", "",
     "IV/RV = implied vol of the bought contract (real print) / 20-day realised vol of the underlying.", ""]
frames = []
for name, kw in CONF.items():
    for per_name, per in (("dev", DEV), ("test", TEST)):
        df = R.replay(trades_for(B, name, kw or {"delta": None} and {}, per) if False else trades_for(B, name, kw, per), factor)
        ok = df[df.status == "ok"].copy()
        ok["iv"] = [implied_vol(p, s, k, d, c) for p, s, k, d, c in zip(ok.real_px, ok.raw_spot, ok.k, ok.days_left, ok.is_call)]
        ok["rv"] = [rv[s].reindex([e.normalize()]).iloc[0] for s, e in zip(ok.sym, ok.entry)]
        ok["ratio"] = ok.iv / ok.rv
        ok["strategy"], ok["period"] = name, per_name
        frames.append(ok)
    R.CACHE.write_text(json.dumps(R.cache))
allr = pd.concat(frames, ignore_index=True)
allr.to_pickle(OUT / "iv_filter.pkl")
L += ["| strategy | period | n | median IV/RV | REAL exp: IV/RV below dev median | REAL exp: above | n below |", "|---|---|---|---|---|---|---|"]
for name in CONF:
    d = allr[(allr.strategy == name) & (allr.period == "dev")]
    thr = d.ratio.median()
    for per in ("dev", "test"):
        x = allr[(allr.strategy == name) & (allr.period == per)].dropna(subset=["ratio"])
        lo, hi = x[x.ratio <= thr], x[x.ratio > thr]
        L.append(f"| {name} | {per} | {len(x)} | {x.ratio.median():.2f} | {fmt(lo.real.mean(), True)} | {fmt(hi.real.mean(), True)} | {len(lo)} |")
L += ["", f"Threshold = the DEV median IV/RV of each strategy (fixed before looking at test)."]
pooled = allr.dropna(subset=["ratio"])
L += ["", "## Pooled (all four), real return by IV/RV bucket", "", "| IV/RV bucket | dev n | dev REAL exp | test n | test REAL exp |", "|---|---|---|---|---|"]
for lo_, hi_ in ((0, 0.9), (0.9, 1.1), (1.1, 1.3), (1.3, 1.6), (1.6, 99)):
    a = pooled[(pooled.period == "dev") & (pooled.ratio > lo_) & (pooled.ratio <= hi_)]
    b = pooled[(pooled.period == "test") & (pooled.ratio > lo_) & (pooled.ratio <= hi_)]
    L.append(f"| {lo_}–{hi_} | {len(a)} | {fmt(a.real.mean(), True)} | {len(b)} | {fmt(b.real.mean(), True)} |")
(OUT / "IV_FILTER.md").write_text("\n".join(L), encoding="utf-8")
print("\n".join(L))
