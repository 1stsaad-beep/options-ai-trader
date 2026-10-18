"""How big must the underlying move be (in ATR) for a long option to break even
after spread + theta?  Model-based, using the real AAPL/SPY price paths for vol."""
import numpy as np
from oat_research import data as D, options_model as om, indicators as ind

for sym, spread in (("aapl", 0.04), ("spy", 0.02)):
    df = D.load_csv(f"../trader_core/test/fixtures/{sym}_d1.csv")
    c = om.OptionCosts(spread_pct=spread)
    iv = om.iv_series(df, c).dropna()
    a = ind.atr(df)
    t = df.index.get_loc(iv.index[-150])  # a typical mid-sample day
    s, v, atr = df.close.iloc[t], iv.iloc[t], a.iloc[t]
    print(f"{sym.upper()}: spot {s:.2f}, IV proxy {v:.1%}, ATR {atr:.2f} ({atr/s:.2%})")
    for delta, dte in ((0.45, 30), (0.6, 35), (0.7, 45)):
        k = om.choose_strike(True, s, dte, v, delta, c)
        buy = om.buy_price(om.mid_price(True, s, k, dte, v, c), c)
        row = []
        for hold in (3, 5, 10):
            # smallest move (ATR units) that makes the exit price >= entry price
            lo, hi = 0.0, 6.0
            for _ in range(40):
                m = (lo + hi) / 2
                sell = om.sell_price(om.mid_price(True, s + m * atr, k, dte - hold * 7 / 5, v, c), c)
                lo, hi = (lo, m) if sell >= buy else (m, hi)
            row.append(f"{hold}d: {hi:.2f} ATR")
        print(f"   delta {delta} DTE {dte}: premium {buy:.2f} -> breakeven move " + ", ".join(row))
