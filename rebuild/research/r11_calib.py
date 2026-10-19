"""Round 11 step 1: convert the daily absolute thresholds into volatility-relative (z) thresholds
by FREQUENCY MATCHING on daily data only (no intraday data touched)."""
import json, numpy as np, pandas as pd
from oat_research import data as D
from r4_common import load_daily
import r7_lib as L7

def z(c, n, look=126):
    r1 = np.log(c).diff()
    sig = r1.rolling(look, min_periods=look).std()
    return (c / c.shift(n) - 1) / (sig * np.sqrt(n))

d1, _ = load_daily()
syms = {s: d1[s] for s in L7.ORIG}
syms.update({s: D.load_csv(f"data/d1x/{s}.csv") for s in L7.NEW if __import__("os").path.exists(f"data/d1x/{s}.csv")})
R, Z = [], []
for s, df in syms.items():
    c = df.close.loc["2000-01-01":]
    r = (c / c.shift(20) - 1); zz = z(c, 20)
    m = zz.notna(); R.append(r[m]); Z.append(zz[m])
R = pd.concat(R); Z = pd.concat(Z)
p_stock = float((R < -0.10).mean()); z_stock = float(Z.quantile(p_stock))
spy = d1["SPY"].close.loc["2000-01-01":]
r5 = spy / spy.shift(5) - 1; z5 = z(spy, 5); m = z5.notna()
p_spy = float((r5[m] < -0.03).mean()); z_spy = float(z5[m].quantile(p_spy))
out = dict(p_stock=p_stock, z_stock=round(z_stock, 2), p_spy=p_spy, z_spy=round(z_spy, 2),
           median_z_at_rule_stock=float(Z[R < -0.10].median()), median_z_at_rule_spy=float(z5[m][r5[m] < -0.03].median()))
json.dump(out, open("results/r11/calib.json", "w"), indent=1); print(out)
