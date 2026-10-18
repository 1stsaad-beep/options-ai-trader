"""Round 7 audit: truncation test for look-ahead. Signals computed on data truncated at time T
must equal the signals computed on the full history for every bar <= T.
python r7_audit.py -> results/r7/AUDIT.md"""
import numpy as np, pandas as pd
from oat_research import data as D, engines_v2 as E, intraday4 as I4, mtf, setups4 as S4, strat6 as S6
from r4_common import load_daily

d1all, vols = load_daily()
L = ["# Look-ahead audit (truncation test)", "", "| strategy | symbol | cut time | bars compared | signals in window | mismatches |", "|---|---|---|---|---|---|"]
cuts = [pd.Timestamp("2024-06-12 11:20"), pd.Timestamp("2025-04-08 15:00"), pd.Timestamp("2026-02-03 13:55")]
for s in ("AAPL", "NVDA", "QQQ"):
    m5 = D.load_csv(f"data/m5a/{s}.csv")
    spy5 = D.load_csv("data/m5a/SPY.csv")
    for cut in cuts:
        m5c = m5[m5.index < cut]
        # MTF-RSI
        a = mtf.mtf_rsi(m5, 14, 75, 25, "reentry"); b = mtf.mtf_rsi(m5c, 14, 75, 25, "reentry")
        # only bars fully completed before the cut (15-min bars ending <= cut)
        idx = b.index[b.index + pd.Timedelta(minutes=15) <= cut]
        mm = int((a.loc[idx, "dir"] != b.loc[idx, "dir"]).sum())
        L.append(f"| MTF-RSI | {s} | {cut} | {len(idx)} | {int((a.loc[idx,'dir']!=0).sum())} | {mm} |")
        # squeeze daily @15:50 and trend-dip @15:50 (daily as-of series)
        for nm in ("Squeeze daily @15:50", "Trend-dip @15:50"):
            fa = I4.daily_asof(m5, "15:50", d1all[s]); fb = I4.daily_asof(m5c, "15:50", d1all[s][d1all[s].index < cut.normalize()])
            full_a = I4.daily_asof(m5, "16:00", d1all[s]); full_b = I4.daily_asof(m5c, "16:00", d1all[s][d1all[s].index < cut.normalize()])
            if nm.startswith("Squeeze"):
                sa = S6.s3_squeeze_call_daily_asof(fa, full_a, vols["VIX"]); sb = S6.s3_squeeze_call_daily_asof(fb, full_b, vols["VIX"])
            else:
                spa = I4.daily_asof(spy5, "15:50", d1all["SPY"]); spb = I4.daily_asof(spy5[spy5.index < cut], "15:50", d1all["SPY"][d1all["SPY"].index < cut.normalize()])
                sa = S4.etf_dip(E.Ctx(fa, spa if s != "SPY" else None), vols["VIX"]); sb = S4.etf_dip(E.Ctx(fb, spb if s != "SPY" else None), vols["VIX"])
            # a daily-as-of row for day D is complete at 15:50 of D
            idx = sb.index[sb.index + pd.Timedelta(hours=15, minutes=50) <= cut]
            idx = idx[idx >= pd.Timestamp("2016-06-01")]
            mm = int((sa.loc[idx, "dir"] != sb.loc[idx, "dir"]).sum())
            L.append(f"| {nm} | {s} | {cut} | {len(idx)} | {int((sa.loc[idx,'dir']!=0).sum())} | {mm} |")
    print(s, flush=True)
open("results/r7/AUDIT.md", "w").write("\n".join(L)); print("\n".join(L))
