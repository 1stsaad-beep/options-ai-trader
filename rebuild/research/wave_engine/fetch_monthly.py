"""Full monthly history since listing (Yahoo, split/dividend adjusted) for the top generation -> data/mo/<SYM>.csv"""
import time
from pathlib import Path
import fetch_yahoo as Y
import r7_lib as L7
if __name__ == "__main__":
    out = Path("data/mo"); out.mkdir(parents=True, exist_ok=True)
    for s in L7.ORIG + L7.NEW:
        try:
            n = Y.save(out / f"{s}.csv", Y.rows(Y.get(s, {"period1": 0, "period2": int(time.time()), "interval": "1mo",
                                                         "events": "div%7Csplit", "includeAdjustedClose": "true"}), True), "monthly, adjusted, since listing")
            print(s, n, flush=True)
        except Exception as e:
            print(s, "ERR", str(e)[:80], flush=True)
        time.sleep(0.5)
