"""Capitulation-Rebound scanner (round 10 rule) — scans liquid US stocks with weekly options NOW.

Rule (daily bars):
  1. Bollinger BandWidth(20, 2) percentile over the last 126 days  > 80 %
  2. ROC(20) of the stock                                          < -10 %
  3. ROC(5) of SPY                                                 < -3 %
Signal -> buy a ~0.50-delta Call (first Friday >= 4 days), exit near the close two sessions later.

Data: Yahoo Finance daily (the last row is today's bar if the market is open = live as-of value).
python scan_capitulation.py [SYMBOLS...]  -> prints a table and writes scan_results/<date>.csv
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import fetch_yahoo as Y

UNIVERSE = [
    # mega/large caps with liquid weekly options
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX", "CRM", "ORCL", "ADBE", "INTC", "QCOM", "MU",
    "TXN", "AMAT", "LRCX", "KLAC", "MRVL", "ARM", "SMCI", "PLTR", "SNOW", "CRWD", "PANW", "NOW", "SHOP", "UBER", "ABNB", "COIN",
    "MSTR", "HOOD", "SOFI", "PYPL", "SQ", "RBLX", "DKNG", "ROKU", "SNAP", "PINS", "DIS", "NKE", "SBUX", "MCD", "WMT", "COST",
    "TGT", "HD", "LOW", "KO", "PEP", "PG", "JNJ", "PFE", "MRK", "LLY", "ABBV", "UNH", "CVS", "BMY", "GILD", "AMGN", "MRNA",
    "JPM", "BAC", "WFC", "C", "GS", "MS", "SCHW", "V", "MA", "AXP", "BA", "CAT", "DE", "GE", "LMT", "RTX", "F", "GM", "RIVN",
    "XOM", "CVX", "OXY", "SLB", "COP", "FCX", "NEM", "T", "VZ", "CMCSA", "AAL", "DAL", "UAL", "CCL", "BABA", "PDD", "JD", "NIO",
]


def daily(sym: str) -> pd.DataFrame:
    now = int(time.time())
    js = Y.get(sym, {"period1": now - 420 * 86400, "period2": now, "interval": "1d", "includeAdjustedClose": "true"})
    rows = Y.rows(js, True)
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df["t"], unit="s", utc=True).dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
    return df[~df.index.duplicated(keep="last")]


def bbw_pct(close: pd.Series, n=20, k=2.0, look=126) -> pd.Series:
    m = close.rolling(n).mean()
    sd = close.rolling(n).std(ddof=0)
    w = 2 * k * sd / m
    return w.rolling(look, min_periods=look).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)


def main(symbols):
    spy = daily("SPY")["close"]
    spy_roc5 = spy.iloc[-1] / spy.iloc[-6] - 1
    asof = spy.index[-1]
    rows = []
    for s in symbols:
        try:
            d = daily(s)
        except Exception as e:  # noqa: BLE001
            rows.append(dict(symbol=s, error=str(e)[:60]))
            continue
        c = d["close"]
        if len(c) < 150:
            continue
        p = float(bbw_pct(c).iloc[-1])
        roc20 = float(c.iloc[-1] / c.iloc[-21] - 1)
        ok1, ok2, ok3 = p > 0.80, roc20 < -0.10, spy_roc5 < -0.03
        rows.append(dict(symbol=s, date=c.index[-1].date(), close=round(float(c.iloc[-1]), 2), bbw_pct=round(p * 100, 1),
                         roc20=round(roc20 * 100, 2), spy_roc5=round(spy_roc5 * 100, 2),
                         c1_bbw=ok1, c2_roc20=ok2, c3_spy=ok3, n_ok=int(ok1) + int(ok2) + int(ok3), SIGNAL=ok1 and ok2 and ok3))
        time.sleep(0.15)
    df = pd.DataFrame(rows)
    out = Path("scan_results"); out.mkdir(exist_ok=True)
    df.to_csv(out / f"capitulation_{asof:%Y-%m-%d}.csv", index=False)
    print(f"As of {asof:%Y-%m-%d} (US).  SPY 5-day change: {spy_roc5*100:+.2f} %  -> market condition {'MET' if spy_roc5 < -0.03 else 'NOT met'} (needs < -3 %)")
    ok = df.dropna(subset=["n_ok"]).sort_values(["SIGNAL", "n_ok", "roc20"], ascending=[False, False, True])
    print("\nSIGNALS (all 3 conditions):")
    print(ok[ok.SIGNAL].to_string(index=False) if ok.SIGNAL.any() else "  none")
    print("\nWATCHLIST — stock conditions 1+2 met (waiting only for the market condition):")
    w = ok[ok.c1_bbw & ok.c2_roc20 & ~ok.SIGNAL]
    print(w[["symbol", "close", "bbw_pct", "roc20"]].to_string(index=False) if len(w) else "  none")
    print("\nCLOSEST — ROC20 below -7 % or BBW pct above 70 %:")
    near = ok[((ok.roc20 < -7) | (ok.bbw_pct > 70)) & ~(ok.c1_bbw & ok.c2_roc20)]
    print(near[["symbol", "close", "bbw_pct", "roc20"]].head(15).to_string(index=False) if len(near) else "  none")
    return df


if __name__ == "__main__":
    main(sys.argv[1:] or UNIVERSE)
