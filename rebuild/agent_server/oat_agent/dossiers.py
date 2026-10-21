"""Per-stock dossiers (spec §9): code-built statistics refreshed daily from history + the agent's own notes (its own
wave counts, which setups worked there). Read before every decision. No ATLAS engine output is stored here."""
from __future__ import annotations
import statistics as st


def stats_from_daily(bars):
    """bars: completed daily bars oldest first (>= 2)."""
    if len(bars) < 2: return {}
    rng = [100 * (b["h"] - b["l"]) / b["c"] for b in bars if b["c"]]
    gaps = []
    for prev, b in zip(bars, bars[1:]):
        g = 100 * (b["o"] / prev["c"] - 1)
        if abs(g) >= 0.5:
            filled = b["l"] <= prev["c"] if g > 0 else b["h"] >= prev["c"]
            gaps.append(dict(gap_pct=g, filled=filled, day_with_gap=(b["c"] > b["o"]) == (g > 0)))
    out = dict(sessions=len(bars), avg_range_pct=round(st.mean(rng), 3), median_range_pct=round(st.median(rng), 3),
               gaps=len(gaps))
    if gaps:
        out.update(gap_fill_rate=round(sum(g["filled"] for g in gaps) / len(gaps), 3),
                   gap_continuation_rate=round(sum(g["day_with_gap"] for g in gaps) / len(gaps), 3),
                   gaps_up=sum(g["gap_pct"] > 0 for g in gaps), gaps_down=sum(g["gap_pct"] < 0 for g in gaps))
    return out


class Dossiers:
    def __init__(self, store):
        self.store = store

    def read(self, sym):
        return self.store.get(f"dossier:{sym}", {"sym": sym, "stats": {}, "notes": [], "updated": None})

    def write_notes(self, sym, now, note, tags=None):
        d = self.read(sym)
        d["notes"] = (d.get("notes") or [])[-49:] + [{"t": now.isoformat(), "note": str(note)[:2000], "tags": tags or []}]
        d["updated"] = now.isoformat()
        self.store.put(f"dossier:{sym}", d)
        return d

    def refresh_stats(self, sym, now, daily_bars):
        d = self.read(sym)
        d["stats"] = stats_from_daily(daily_bars)
        d["stats_updated"] = now.isoformat()
        self.store.put(f"dossier:{sym}", d)
        return d
