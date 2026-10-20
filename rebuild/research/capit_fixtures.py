"""Builds trader_core/test/fixtures/capitulation_cases.json — reference values of the capitulation-rebound rule
computed with the research definitions (oat_research.indicators) so the Dart port can be checked number for number."""
import json, glob, os
import pandas as pd
from oat_research import indicators as ind

def load(p):
    d = pd.read_csv(p, comment="#", parse_dates=["time"]); d["date"] = d.time.dt.tz_convert("America/New_York").dt.date
    return d.set_index("date")["close"]

spy = load("data/d1/SPY.csv")
spy_roc5 = spy / spy.shift(5) - 1
fires, cases = [], []
for p in sorted(glob.glob("data/d1/*.csv")):
    sym = os.path.basename(p)[:-4]
    if sym == "SPY": continue
    c = load(p); c = c[c.index.isin(spy.index)]
    pct = ind.rolling_percentile(ind.bb_width(c, 20), 126); roc = c / c.shift(20) - 1
    s5 = spy_roc5.reindex(c.index)
    f = (pct > 0.8) & (roc < -0.10) & (s5 < -0.03)
    for d in f[f].index: fires.append((sym, d))
    def case(d, note):
        i = c.index.get_loc(d); j = spy.index.get_loc(d)
        cases.append(dict(symbol=sym, date=str(d), note=note,
                          closes=[round(x, 6) for x in c.iloc[i - 160:i]], price=round(float(c.iloc[i]), 6),
                          spyCloses=[round(x, 6) for x in spy.iloc[j - 10:j]], spyPrice=round(float(spy.iloc[j]), 6),
                          expected=dict(fire=bool(f.loc[d]), bbwPct=float(pct.loc[d]), roc20=float(roc.loc[d]), spyRoc5=float(s5.loc[d]))))
    if sym in ("AAPL", "NVDA", "AMZN", "TSLA"):
        for d in [x for x in f[f].index if str(x) >= "2020-01-01"][:2]: case(d, "signal")
        nz = [x for x in c.index if str(x) in ("2024-06-12", "2025-01-15")]
        for d in nz: case(d, "no signal")
        near = (pct > 0.8) & (roc < -0.10) & ~(s5 < -0.03)
        nd = [x for x in near[near].index if str(x) >= "2018-01-01"][:1]
        for d in nd: case(d, "no signal (stock fell but SPY did not)")
print(len(fires), "fires total; dates since 2025:", sorted({str(d) for s, d in fires if str(d) >= "2025-01-01"}))
# rounding the inputs must not flip any expected value: recompute from rounded inputs
import numpy as np
for k in cases:
    cc = pd.Series(k["closes"] + [k["price"]]); w = ind.bb_width(cc, 20); pp = float(ind.rolling_percentile(w, 126).iloc[-1])
    k["expected"]["bbwPct"] = round(pp, 6); k["expected"]["roc20"] = round(k["price"] / k["closes"][-20] - 1, 6)
    k["expected"]["spyRoc5"] = round(k["spyPrice"] / k["spyCloses"][-5] - 1, 6)
    k["expected"]["fire"] = bool(pp > 0.8 and k["expected"]["roc20"] < -0.10 and k["expected"]["spyRoc5"] < -0.03)
out = "../trader_core/test/fixtures/capitulation_cases.json"
json.dump(dict(source="research capit_fixtures.py (Yahoo daily closes, data/d1)", cases=cases), open(out, "w"), indent=1)
print(len(cases), "cases ->", out); print(pd.DataFrame([dict(s=k["symbol"], d=k["date"], n=k["note"], **k["expected"]) for k in cases]).to_string())
