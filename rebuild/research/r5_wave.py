"""Round 5 — MTF Elliott: collect every grandchild (15m / 5m) wave-2 and wave-B setup with
its daily and hourly wave labels, divergence flags and ~25 enhancement features, plus the
underlying outcome. python r5_wave.py [15|5] -> results/r5/wave_cand_{tf}.pkl"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
from oat_research import elliott_mtf as EW, indicators as ind, mtf, setups4 as S4, timing as T
from oat_research.intraday import WDParams
from oat_research.wave_lab import candidates
from r5_common import SYMS, load, prev_day_atr

OUT = Path("results/r5"); OUT.mkdir(parents=True, exist_ok=True)


def extra(df, rows, daily):
    """Enhancement features computed at the setup (all causal: known at the trigger bar)."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = ind.atr(df).to_numpy()
    e20, e50, e200 = (ind.ema(df["close"], n).to_numpy() for n in (20, 50, 200))
    piv = ind.pivots(df, 3, 2)
    # previous day high / low (known intraday)
    dh = daily["high"].shift(1); dl = daily["low"].shift(1)
    dh.index = dh.index.normalize(); dl.index = dl.index.normalize()
    pdh = dh.reindex(df.index.normalize()).to_numpy(); pdl = dl.reindex(df.index.normalize()).to_numpy()
    f = {k: [] for k in ("ma_touch20", "ma_touch50", "above_e200", "e50_gt_e200", "sr_polarity", "sr_prev_day", "fib_golden",
                         "fib_deep", "fib_time", "double_extreme", "engulf_or_hammer", "w2_lt_w1_time", "leg1_fast")}
    for r in rows.itertuples():
        d, i0, i1, i2, t = r.dir, r.i0, r.i1, r.i2, r.t
        A = a[i2] if np.isfinite(a[i2]) else a[t]
        p2 = r.p2
        f["ma_touch20"].append(bool(abs(p2 - e20[i2]) <= 0.3 * A))
        f["ma_touch50"].append(bool(abs(p2 - e50[i2]) <= 0.3 * A))
        f["above_e200"].append(bool((c[t] > e200[t]) if d > 0 else (c[t] < e200[t])))
        f["e50_gt_e200"].append(bool((e50[t] > e200[t]) if d > 0 else (e50[t] < e200[t])))
        # polarity: an older swing of the OPPOSITE side (old resistance for a bull W2) near the W2 extreme
        old = [q for q in piv if q[1] < i0 and q[3] == (d > 0) and abs(q[2] - p2) <= 0.3 * A]
        f["sr_polarity"].append(bool(old))
        ref = pdl[t] if d > 0 else pdh[t]
        f["sr_prev_day"].append(bool(np.isfinite(ref) and abs(p2 - ref) <= 0.3 * A))
        f["fib_golden"].append(bool(0.5 <= r.retr <= 0.618 + 0.03))
        f["fib_deep"].append(bool(0.618 < r.retr <= 0.886))
        tr_ = (i2 - i1) / max(1, i1 - i0)
        f["fib_time"].append(bool(0.382 <= tr_ <= 1.0))
        f["w2_lt_w1_time"].append(bool(tr_ < 1.0))
        f["leg1_fast"].append(bool((i1 - i0) <= 20))
        same = [q for q in piv if i1 < q[0] < i2 and q[3] == (d < 0)]
        f["double_extreme"].append(bool(any(abs(q[2] - p2) <= 0.15 * A for q in same)))
        j = i2
        body = abs(c[j] - o[j]); rng = max(h[j] - l[j], 1e-9)
        if d > 0:
            hammer = (min(o[j], c[j]) - l[j]) >= 2 * body and (h[j] - max(o[j], c[j])) <= body
            eng = j + 1 < len(c) and c[j + 1] > o[j + 1] and c[j + 1] >= o[j] and o[j + 1] <= c[j]
        else:
            hammer = (h[j] - max(o[j], c[j])) >= 2 * body and (min(o[j], c[j]) - l[j]) <= body
            eng = j + 1 < len(c) and c[j + 1] < o[j + 1] and c[j + 1] <= o[j] and o[j + 1] >= c[j]
        f["engulf_or_hammer"].append(bool(hammer or (eng and j + 1 <= t)))
    for k, v in f.items():
        rows[k] = v
    return rows


def main(tf=15):
    m5, full, vols = load()
    allrows = []
    for s in SYMS:
        lo = S4.resample(m5[s], tf)
        h1 = S4.resample(m5[s], 60)
        daily = full[s]
        dl = EW.label_series(daily, k_atr=2.0)
        dl_prev = dl.shift(1); dl_prev.index = dl_prev.index.normalize()
        hl = EW.label_series(h1, k_atr=1.5)
        end_lo, end_h = mtf.bar_end(lo, tf), mtf.bar_end(h1, 60)
        hdir = mtf.align(hl["wdir"].astype(float), end_h, end_lo).to_numpy()
        hwave = mtf.align(hl["wave"], end_h, end_lo).to_numpy()
        ddir = dl_prev["wdir"].reindex(lo.index.normalize()).to_numpy()
        dwave = dl_prev["wave"].reindex(lo.index.normalize()).to_numpy()
        lwl = EW.label_series(lo, k_atr=1.5)
        # daily trend helpers (previous day)
        dc = daily["close"]; s50 = ind.sma(dc, 50); s200 = ind.sma(dc, 200)
        up50 = ((dc > s50) & (s50 > s50.shift(10))).shift(1); up50.index = up50.index.normalize()
        ab200 = (dc > s200).shift(1); ab200.index = ab200.index.normalize()
        rows = candidates(lo, WDParams(swing_atr=1.5, leg1_min_atr=3.0, arm_bars=10))
        if rows.empty:
            continue
        rows = extra(lo, rows, daily)
        rows["sym"] = s
        rows["h_dir"], rows["h_wave"] = hdir[rows.t], hwave[rows.t]
        rows["d_dir"], rows["d_wave"] = ddir[rows.t], dwave[rows.t]
        rows["g_dir"], rows["g_wave"] = lwl["wdir"].to_numpy()[rows.t], lwl["wave"].to_numpy()[rows.t]
        rows["d_up50"] = up50.reindex(lo.index.normalize()).to_numpy()[rows.t]
        rows["d_above200"] = ab200.reindex(lo.index.normalize()).to_numpy()[rows.t]
        a = prev_day_atr(lo, daily)
        w = T.walk(lo, list(zip(rows.t.astype(int), rows.dir.astype(int))), a, horizon_days=3, bars_per_day=390 // tf)
        w = w.drop(columns=["date", "dir"])
        rows = rows.merge(w, on="t", how="inner")
        allrows.append(rows)
        print(s, len(rows), flush=True)
    df = pd.concat(allrows, ignore_index=True)
    df.to_pickle(OUT / f"wave_cand_{tf}.pkl")
    print(len(df))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 15)
