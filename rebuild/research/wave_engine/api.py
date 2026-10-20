"""Public API of the wave engine for an analysis app (ATLAS).  JSON-ready output, no trading signals.

    analyze(sym, asof=None)                     -> engine 1: automatic multi-generation count, best two scenarios
    analyze_drawn(sym, tf, t0, p0, t1, p1)      -> engine 2: the user drew a wave; count what came after it
    log_forecast(result, path) / score_log(path) -> forward log for the live evaluation (stage 7)

Data: by default the research CSV files; a backend calls bars.set_provider(daily=..., m5=..., monthly=...).
IMPORTANT (research verdict, results/wave/STAGE5_WALK.md + ROUND_W2.md): no pre-registered test found a
forecasting edge versus a drift-matched random baseline.  Output is a DESCRIPTIVE count; every result carries
NOTICE_AR and must be shown with it."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from . import bars as B, count as C, gen as G, patterns as PT, project as PR, explain as EX

ENGINE_VERSION = "wave-1.0 (2026-10-20)"
NOTICE_AR = ("تحليل وصفي لترقيم موجات إليوت — اختُبر على 45 سهمًا ولم يُثبت قدرة تنبؤية تفوق خط الأساس العشوائي. "
             "لا يُستخدم كإشارة تداول.")
TF_AR = {"M": "شهري", "W": "أسبوعي", "D": "يومي", "60": "ساعة", "5": "5 دقائق"}
PAT_AR = {"IMPULSE": "دافعة", "LEADING_DIAG": "قطري بادئ", "ENDING_DIAG": "قطري منتهٍ", "ZIGZAG": "زجزاج",
          "FLAT": "مسطح", "TRIANGLE": "مثلث", "DOUBLE_THREE": "ثلاثية مزدوجة", "DOUBLE_THREE_T": "ثلاثية مزدوجة بمثلث",
          "TRIPLE_THREE": "ثلاثية ثلاثية"}


def _ts(t):
    return pd.Timestamp(t).isoformat()


def _gen_json(z, g):
    c = z.current()
    tg = PR.targets(z)
    start_t = pd.Timestamp(c["leg_start_t"])
    pos, neg = EX.evidence(z)
    return dict(
        generation=g, tf=z.tf, tf_ar=TF_AR.get(z.tf, z.tf), zigzag_k=float(z.k),
        pattern=" + ".join(p for p, _ in z.parts), pattern_ar=" + ".join(PAT_AR.get(p, p) for p, _ in z.parts),
        current=dict(pattern=c["pattern"], wave=c["leg"], index=int(c["leg_index"]), of=int(c["legs_total"]),
                     complete=bool(c["complete"]), up=bool(c["leg_up"]), motive=bool(c["motive_leg"]),
                     start_t=_ts(start_t), start_p=round(float(c["leg_start_p"]), 4)),
        labels=[dict(t=_ts(t), p=round(float(p), 4), label=str(l), pattern=pat) for t, p, l, pat in z.labels()],
        invalidation=round(float(z.invalidation()), 4),
        targets=[dict(name=n, price=round(float(v), 4)) for n, v in tg["levels"]],
        minimum=None if tg["minimum"] is None else round(float(tg["minimum"]), 4),
        time_windows=[dict(name=n, bars=None if not np.isfinite(b) else round(float(b), 1),
                           at=None if not np.isfinite(b) else _ts(PR.to_time(start_t, b, z.tf))) for n, b in tg["time"]],
        bars_so_far=None if not np.isfinite(tg["bars_so_far"]) else float(tg["bars_so_far"]),
        evidence_for_ar=pos, evidence_against_ar=neg, score=round(float(z.score), 3))


def _chains_json(chains):
    two = G.best_two(chains)
    pr = G.probabilities(chains)
    idx = {id(c): i for i, c in enumerate(chains)}
    out = []
    for rank, ch in enumerate(two, 1):
        out.append(dict(rank=rank, relative_weight=round(pr[idx[id(ch)]], 3),
                        generations=[_gen_json(z, g + 1) for g, z in enumerate(ch.gens)]))
    return out


def _descend(sym, chains, asof, beam=6, max_gen=9, stop_tf="5", min_bars=60):
    """same generation loop as gen.run, from given starting chains."""
    for g in range(1, max_gen):
        new, grew = [], False
        for ch in chains:
            if len(ch.gens) >= 2 and ch.last.tf == ch.gens[-2].tf == stop_tf:
                new.append(ch); continue
            cur = ch.last.current()
            t0 = pd.Timestamp(cur["leg_start_t"])
            tf = G.pick_tf(sym, t0, asof, ch.last.tf, min_bars)
            if tf is None:
                new.append(ch); continue
            direction = 1 if cur["leg_up"] else -1
            pats = list(PT.MOTIVE) if cur["motive_leg"] else G.CORRECTIVE
            kids = [z for z in G.counts_for(sym, tf, t0, asof, direction=direction, patterns=pats, top=beam,
                                            anchor_p=cur["leg_start_p"]) if len(z.parts) == 1 and len(z.parts[0][1]) > 2]
            if not kids:
                new.append(ch); continue
            grew = True
            for z in kids[:3]:
                new.append(G.Chain(ch.score + z.score, ch.gens + [z]))
        new.sort(key=lambda c: (-len(c.gens), -c.score))
        chains = new[:beam]
        if not grew: break
    return chains


def _asof(sym, asof):
    if asof is not None: return pd.Timestamp(asof)
    try:
        return B.available(sym, "5")[1]
    except FileNotFoundError:
        return B.available(sym, "D")[1]


def analyze(sym, asof=None, beam=6, stop_tf="5"):
    """Engine 1: monthly count -> children -> ... down to the finest timeframe with data."""
    asof = _asof(sym, asof)
    chains = G.run(sym, asof=asof, beam=beam, stop_tf=stop_tf)
    return dict(engine="auto", version=ENGINE_VERSION, symbol=sym, asof=_ts(asof), notice_ar=NOTICE_AR,
                last_price=float(B.bars(sym, "D", None, asof)["close"].iloc[-1]), scenarios=_chains_json(chains))


def analyze_drawn(sym, tf, t0, p0, t1, p1, asof=None, beam=6, stop_tf="5"):
    """Engine 2: the user drew a (completed) wave from (t0, p0) to (t1, p1) on timeframe tf.
    Everything after its end is counted (first move against the drawn wave), then generations go down as in
    engine 1.  The drawn end is the anchor: the count starts exactly at p1."""
    asof = _asof(sym, asof)
    t1 = pd.Timestamp(t1); up = float(p1) > float(p0)
    ctf = G.pick_tf(sym, t1, asof, tf, min_bars=30) or tf
    # first pattern after the drawn wave moves against it; allow motive or corrective, one or two patterns
    sc = G.counts_for(sym, ctf, t1, asof, direction=-1 if up else 1, top=beam * 2, anchor_p=float(p1))
    if not sc:
        return dict(engine="drawn", version=ENGINE_VERSION, symbol=sym, asof=_ts(asof), notice_ar=NOTICE_AR,
                    drawn=dict(tf=tf, t0=_ts(t0), p0=float(p0), t1=_ts(t1), p1=float(p1)), scenarios=[],
                    message_ar="لا توجد شموع كافية بعد نهاية الموجة المرسومة")
    chains = _descend(sym, [G.Chain(z.score, [z]) for z in sc][:beam], asof, beam=beam, stop_tf=stop_tf)
    return dict(engine="drawn", version=ENGINE_VERSION, symbol=sym, asof=_ts(asof), notice_ar=NOTICE_AR,
                drawn=dict(tf=tf, t0=_ts(t0), p0=float(p0), t1=_ts(t1), p1=float(p1), up=up),
                last_price=float(B.bars(sym, "D", None, asof)["close"].iloc[-1]), scenarios=_chains_json(chains))


# ------------------------------------------------------------------ live evaluation log (stage 7)
def log_forecast(result, path):
    """Append one line per scenario: what the LAST generation expects (direction, nearest target, invalidation,
    first time window).  Never edited afterwards."""
    rows = []
    for s in result.get("scenarios", []):
        g = s["generations"][-1]; cur = g["current"]
        tgt = g["targets"][0]["price"] if g["targets"] else None
        win = next((w["at"] for w in g["time_windows"] if w["at"]), None)
        rows.append(dict(logged=_ts(pd.Timestamp.now(tz="UTC").tz_localize(None)), engine=result["engine"],
                         version=result["version"], symbol=result["symbol"], asof=result["asof"], rank=s["rank"],
                         tf=g["tf"], state=f"{cur['pattern']}:{cur['wave']}", up=cur["up"], price=result.get("last_price"),
                         target=tgt, invalidation=g["invalidation"], window=win))
    with open(path, "a", encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows


def score_log(path, horizon_days=20):
    """Resolve logged forecasts on later bars: target first / invalidation first / neither within horizon.
    Compare with the same move sizes at random dates (drift-matched baseline) before believing any number."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["target"] is None or r["price"] is None: continue
        b = B.bars(r["symbol"], "D", pd.Timestamp(r["asof"]).normalize() + pd.Timedelta(days=1), None).iloc[:horizon_days]
        if not len(b): continue
        up = r["target"] > r["price"]
        hit_t = b["high"] >= r["target"] if up else b["low"] <= r["target"]
        hit_i = b["low"] <= r["invalidation"] if up else b["high"] >= r["invalidation"]
        a = int(np.argmax(hit_t.values)) if hit_t.any() else 10 ** 9
        c = int(np.argmax(hit_i.values)) if hit_i.any() else 10 ** 9
        out.append(dict(r, outcome="target" if a < c else "invalidated" if c < a else ("both_same_day" if a < 10 ** 9 else "open")))
    return pd.DataFrame(out)
