"""Round 12 universe: volatile liquid US stocks (5% moves are common). Daily (Yahoo) -> data/d1v/, 5-minute (Alpaca SIP, 2020+) -> data/m5v/."""
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd
import fetch_yahoo as Y
import fetch_alpaca as A

VOL = ["COIN", "MSTR", "SMCI", "MARA", "RIOT", "RIVN", "LCID", "SHOP", "ROKU", "SNAP", "PINS", "DKNG", "RBLX", "U", "AFRM",
       "UPST", "SOFI", "HOOD", "NET", "CRWD", "DDOG", "ZS", "SNOW", "MDB", "OKTA", "TWLO", "ENPH", "FSLR", "PLUG", "NIO",
       "XPEV", "BABA", "PDD", "JD", "MRNA", "BNTX", "CCL", "AAL", "UAL", "DAL", "CVNA", "W", "ETSY", "CHWY", "PTON",
       "ARM", "APP", "IONQ", "RKLB", "SE", "MELI", "TTD", "ON", "LRCX", "AMAT", "MRVL", "CELH", "TSLA", "AMD", "NVDA"]

if __name__ == "__main__":
    out = Path("data"); now = int(time.time()); p1 = int(datetime(2015, 1, 1, tzinfo=timezone.utc).timestamp())
    kid, sec = A.keys()
    end = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    import sys
    todo = sys.argv[1:] or VOL
    for s in todo:
        if (out / "m5v" / f"{s}.csv").exists(): continue
        try:
            n = Y.save(out / "d1v" / f"{s}.csv", Y.rows(Y.get(s, {"period1": p1, "period2": now, "interval": "1d", "events": "div%7Csplit",
                                                                "includeAdjustedClose": "true"}), True), "daily, dividend/split adjusted")
            rows = A.fetch(s, "5Min", "2020-01-01T00:00:00Z", end, kid, sec)
            df = pd.DataFrame(rows); t = pd.to_datetime(df["t"], utc=True)
            ny = t.dt.tz_convert("America/New_York"); mins = ny.dt.hour * 60 + ny.dt.minute
            keep = ((mins >= 570) & (mins < 960)).to_numpy(); df, t = df[keep], t[keep]
            o = pd.DataFrame({"time": t.dt.strftime("%Y-%m-%dT%H:%M:%SZ").to_numpy(), "open": df["o"].to_numpy(), "high": df["h"].to_numpy(),
                              "low": df["l"].to_numpy(), "close": df["c"].to_numpy(), "volume": df["v"].to_numpy()})
            p = out / "m5v" / f"{s}.csv"; p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("w") as f:
                f.write(f"# Source: Alpaca SIP 5Min bars, adjustment=all, regular session; fetched {end[:10]}; time = bar start UTC\n")
                o.to_csv(f, index=False)
            print(s, n, len(o), flush=True)
        except Exception as e:
            print(s, "ERROR", str(e)[:120], flush=True)
