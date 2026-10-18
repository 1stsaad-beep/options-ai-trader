"""Round 7 out-of-sample universe: 30 liquid US stocks with weekly options that were NEVER used in
rounds 0-6. Daily (Yahoo, 1998+) -> data/d1x/, 5-minute (Alpaca SIP, 2023+) -> data/m5x/.
python fetch_new_universe.py"""
import sys
from pathlib import Path
import fetch_yahoo as Y
import fetch_alpaca as A

NEW = ["AVGO", "NFLX", "CRM", "ORCL", "ADBE", "INTC", "QCOM", "MU", "BAC", "WFC", "GS", "C", "V", "MA", "PYPL",
       "DIS", "NKE", "WMT", "HD", "KO", "PEP", "MRK", "PFE", "LLY", "BA", "CAT", "CVX", "UBER", "ABNB", "PLTR"]

if __name__ == "__main__":
    import time
    from datetime import datetime, timezone, timedelta
    import pandas as pd
    out = Path("data")
    now = int(time.time()); p1 = int(datetime(1998, 1, 1, tzinfo=timezone.utc).timestamp())
    kid, sec = A.keys()
    end = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for s in NEW:
        n = Y.save(out / "d1x" / f"{s}.csv", Y.rows(Y.get(s, {"period1": p1, "period2": now, "interval": "1d", "events": "div%7Csplit",
                                                            "includeAdjustedClose": "true"}), True), "daily, dividend/split adjusted")
        rows = A.fetch(s, "5Min", "2023-01-01T00:00:00Z", end, kid, sec)
        df = pd.DataFrame(rows)
        t = pd.to_datetime(df["t"], utc=True)
        ny = t.dt.tz_convert("America/New_York"); mins = ny.dt.hour * 60 + ny.dt.minute
        keep = ((mins >= 570) & (mins < 960)).to_numpy()
        df, t = df[keep], t[keep]
        o = pd.DataFrame({"time": t.dt.strftime("%Y-%m-%dT%H:%M:%SZ").to_numpy(), "open": df["o"].to_numpy(), "high": df["h"].to_numpy(),
                          "low": df["l"].to_numpy(), "close": df["c"].to_numpy(), "volume": df["v"].to_numpy()})
        p = out / "m5x" / f"{s}.csv"; p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w") as f:
            f.write(f"# Source: Alpaca SIP 5Min bars, adjustment=all, regular session; fetched {end[:10]}; time = bar start UTC\n")
            o.to_csv(f, index=False)
        print(s, n, len(o), flush=True)
