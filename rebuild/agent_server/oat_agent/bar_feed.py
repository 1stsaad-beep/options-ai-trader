"""Feeds newly completed bars to the code layer (alerts every bar; invalidation exits on 5m closes). Polls only the
symbols that need it: open positions and symbols with active alerts."""
from __future__ import annotations


class BarFeed:
    TFS = ("1m", "5m", "15m", "1h")

    def __init__(self, data, store, broker, layer, clock):
        self.data, self.store, self.broker, self.layer, self.clock = data, store, broker, layer, clock
        self.seen = {}                                     # (sym, tf) -> last bar start already processed

    def symbols(self):
        syms = {p.contract.underlying for p in self.broker.positions() if p.qty > 0}
        alert_tfs = {}
        from .alerts import parse
        for a in self.store.alerts_active():
            tf = parse(a["cond"]).tf
            alert_tfs.setdefault(a["sym"], set()).add(tf or "1m")
        need = {s: {"5m"} for s in syms}
        for s, tfs in alert_tfs.items(): need.setdefault(s, set()).update(tfs)
        return need

    def poll(self):
        now = self.clock()
        out = []
        for sym, tfs in self.symbols().items():
            for tf in sorted(tfs):
                bars = self.data.bars(sym, tf, 3, now)
                last = self.seen.get((sym, tf))
                new = [b for b in bars if last is None or b["t"] > last]
                if last is None: new = new[-1:]            # first poll: only the latest completed bar
                for b in new:
                    self.layer.on_bar(sym, tf, b["c"], b["t"])
                    out.append((sym, tf, b["t"]))
                if bars: self.seen[(sym, tf)] = bars[-1]["t"]
        return out
