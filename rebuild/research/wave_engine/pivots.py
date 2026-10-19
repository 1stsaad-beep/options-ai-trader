"""Stage 1 — pivots.  Elliott counting works on swing points, not candles: a 20-year monthly history becomes
~40-80 pivots, so there is no candle cap and memory is tiny.

zigzag(): causal ATR zigzag.  A swing extreme becomes a CONFIRMED pivot only when price has reversed from it by
k x ATR; `conf` records that bar's time.  At any as-of time only pivots with conf <= as-of are known, plus the
TENTATIVE running extreme of the current leg (which can still move = the classic 'repaint' that must never be used
as if it were known in a backtest)."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class Pivots:
    t: np.ndarray        # pivot bar time
    p: np.ndarray        # pivot price (high for H, low for L)
    kind: np.ndarray     # +1 high, -1 low
    i: np.ndarray        # bar index
    conf: np.ndarray     # time the pivot became known
    tent: tuple | None   # (t, p, kind, i) running extreme of the current unfinished leg
    k: float
    tf: str = ""

    def __len__(self):
        return len(self.p)

    def frame(self):
        return pd.DataFrame({"t": self.t, "p": self.p, "kind": self.kind, "i": self.i, "conf": self.conf})


def atr(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    out = np.empty_like(tr); a = tr[0]
    for j, x in enumerate(tr):
        a = x if j == 0 else a + (x - a) / n if j < n else a + (x - a) / n
        out[j] = a
    return out


def zigzag(df: pd.DataFrame, k: float = 2.0, atr_n: int = 14, tf: str = "") -> Pivots:
    h, l = df["high"].to_numpy(float), df["low"].to_numpy(float)
    tt = df.index.to_numpy(); te = (df["t_end"] if "t_end" in df else df.index.to_series()).to_numpy()
    a = atr(df, atr_n); n = len(h)
    T, P, K, I, C = [], [], [], [], []
    if n == 0:
        return Pivots(*(np.array([]) for _ in range(5)), None, k, tf)
    d = 0; hi_i = lo_i = 0
    for j in range(1, n):
        thr = k * a[j]
        if h[j] > h[hi_i]: hi_i = j
        if l[j] < l[lo_i]: lo_i = j
        if d >= 0 and h[hi_i] - l[j] >= thr and hi_i < j and (d == 1 or h[hi_i] - l[lo_i] >= thr and lo_i < hi_i or d == 0):
            if d == 0 and lo_i < hi_i:       # first swing: also record the starting low
                T.append(tt[lo_i]); P.append(l[lo_i]); K.append(-1); I.append(lo_i); C.append(te[j])
            T.append(tt[hi_i]); P.append(h[hi_i]); K.append(1); I.append(hi_i); C.append(te[j])
            d = -1; lo_i = j
        elif d <= 0 and h[j] - l[lo_i] >= thr and lo_i < j:
            if d == 0 and hi_i < lo_i:
                T.append(tt[hi_i]); P.append(h[hi_i]); K.append(1); I.append(hi_i); C.append(te[j])
            T.append(tt[lo_i]); P.append(l[lo_i]); K.append(-1); I.append(lo_i); C.append(te[j])
            d = 1; hi_i = j
    tent = None
    if d == 1: tent = (tt[hi_i], h[hi_i], 1, hi_i)
    elif d == -1: tent = (tt[lo_i], l[lo_i], -1, lo_i)
    return Pivots(np.array(T), np.array(P, float), np.array(K, int), np.array(I, int), np.array(C), tent, k, tf)


def asof(pv: Pivots, t) -> Pivots:
    """the pivots that were KNOWN at time t (for walk-forward use)."""
    m = pv.conf <= np.datetime64(pd.Timestamp(t))
    return Pivots(pv.t[m], pv.p[m], pv.kind[m], pv.i[m], pv.conf[m], None, pv.k, pv.tf)


def choose_tf(t0, t1, min_bars: int = 60, sym: str | None = None):
    """coarsest timeframe that gives the interval at least `min_bars` bars (adaptive child timeframe)."""
    from .bars import TF_ORDER, bars
    for tf in TF_ORDER:
        if sym is None: continue
        b = bars(sym, tf, t0, t1)
        if len(b) >= min_bars:
            return tf, b
    return TF_ORDER[-1], bars(sym, TF_ORDER[-1], t0, t1) if sym else None


def multi_k(df: pd.DataFrame, ks=(0.75, 1, 1.5, 2, 3, 4, 6, 9), target=(8, 60), tf: str = ""):
    """pivot sets at several thresholds; keep those whose pivot count suits counting (a parent wave of 5 or 3 legs,
    each with internal structure, needs roughly 8-60 pivots)."""
    out = []
    for k in ks:
        pv = zigzag(df, k, tf=tf)
        if target[0] <= len(pv) <= target[1]:
            out.append(pv)
    return out
