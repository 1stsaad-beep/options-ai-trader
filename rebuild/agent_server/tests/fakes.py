import datetime as dt
from oat_agent import nyse
from oat_agent.models import Contract


class FakeData:
    def __init__(self):
        self.bar_map, self.snap, self.contracts, self.snaps = {}, {}, {}, {}

    def bars(self, sym, tf, n, now, ext_hours=False):
        return [b for b in self.bar_map.get((sym, tf), []) if b["t"] <= now][-n:]

    def snapshot(self, sym):
        return self.snap[sym]

    def option_contracts(self, sym, expiry):
        return self.contracts.get((sym, expiry), [])

    def option_snapshots(self, sym, expiry):
        return self.snaps.get((sym, expiry), {})

    # helpers
    def chain(self, sym, expiry, strikes, quote_fn, ts):
        cs, ss = [], {}
        for k in strikes:
            for right in ("call", "put"):
                c = Contract(sym, right, expiry, k)
                cs.append(dict(symbol=c.occ, type=right, strike_price=str(k), open_interest=str(100 + int(k)), expiration_date=expiry.isoformat()))
                bid, ask = quote_fn(right, k)
                ss[c.occ] = dict(latestQuote=dict(bp=bid, ap=ask, t=ts.isoformat()), greeks=dict(delta=0.3 if right == "call" else -0.3),
                                 impliedVolatility=0.4, dailyBar=dict(v=10))
        self.contracts[(sym, expiry)] = cs
        self.snaps[(sym, expiry)] = ss


def bars_5m(day: dt.date, closes, vol=1000):
    t0 = nyse.to_utc(day.year, day.month, day.day, 9, 30)
    return [dict(t=t0 + dt.timedelta(minutes=5 * i), o=c, h=c + 0.5, l=c - 0.5, c=c, v=vol) for i, c in enumerate(closes)]
