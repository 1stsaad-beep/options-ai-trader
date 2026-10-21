"""Code layer (spec §5, always on, no model cost): evaluates alerts on every closed bar, exits automatically when a
position's invalidation breaks (5m close beyond the level written at entry), time-exits same-day expiries at 15:50 ET
(10 minutes before an early close), closes everything when the monthly cap is reached, and flattens on the owner's
kill-and-flatten command. Alert hits are queued for the watcher (stage 3); the code layer never opens a trade."""
from __future__ import annotations
import datetime as dt
from . import alerts as AL, nyse


class CodeLayer:
    def __init__(self, executor, store, settings, clock, on_alert=None):
        self.x, self.store, self.s, self.clock = executor, store, settings, clock
        self.on_alert = on_alert or (lambda a, value: None)

    # ---- bars
    def on_bar(self, sym: str, tf: str, close: float, bar_end: dt.datetime):
        now = self.clock()
        fired = AL.evaluate_bar(self.store.alerts_active(sym), sym, tf, close)
        for a in fired:
            self.store.alert_fired(a["id"], now)
            self.store.event(now, "alert_hit", dict(alert=a, tf=tf, close=close, bar_end=bar_end.isoformat()), sym=sym)
            self.on_alert(a, close)
        exits = []
        if tf == "5m":
            for p in self.x.broker.positions():
                if p.contract.underlying != sym or p.qty <= 0: continue
                m = self.store.meta(p.contract.occ)
                if not m: continue
                inv = m["invalidation"]
                broken = close < inv if p.contract.right == "call" else close > inv
                if broken:
                    r = self.x.exit(p, "INVALIDATION",
                                    f"كسر مستوى الإبطال {inv:.2f}: إغلاق شمعة 5 دقائق عند {close:.2f}")
                    exits.append((p.contract.occ, r))
        return fired, exits

    def on_last(self, sym: str, price: float):
        now = self.clock()
        fired = AL.evaluate_last(self.store.alerts_active(sym), sym, price)
        for a in fired:
            self.store.alert_fired(a["id"], now)
            self.store.event(now, "alert_hit", dict(alert=a, last=price), sym=sym)
            self.on_alert(a, price)
        return fired

    # ---- periodic tick (every few seconds)
    def time_exit_at(self, today: dt.date):
        sess = nyse.session(today)
        if sess is None: return None
        hh, mm = map(int, self.s.same_day_exit_hhmm.split(":"))
        t = nyse.to_utc(today.year, today.month, today.day, hh, mm)
        return min(t, sess.close_utc - dt.timedelta(minutes=10))

    def tick(self):
        now = self.clock()
        today = nyse.wall(now).date()
        out = []
        cap = self.x.cost.reached(now)
        flatten = bool(self.store.get("flatten_requested", False))
        t_exit = self.time_exit_at(today)
        for p in self.x.broker.positions():
            if p.qty <= 0: continue
            if flatten:
                out.append((p.contract.occ, "KILL_FLATTEN", self.x.exit(p, "KILL_FLATTEN", "أمر المالك: إيقاف وإغلاق كل المراكز")))
            elif cap:
                out.append((p.contract.occ, "COST_CAP", self.x.exit(p, "COST_CAP", "بلغ الإنفاق الشهري الحد — إغلاق المراكز المفتوحة")))
            elif p.contract.expiry == today and t_exit and now >= t_exit:
                out.append((p.contract.occ, "TIME_EXIT", self.x.exit(p, "TIME_EXIT", f"خروج زمني لعقد ينتهي اليوم ({nyse.hm(t_exit)} ET)")))
        if flatten and not self.x.broker.positions():
            self.store.put("flatten_requested", False)
        return out
