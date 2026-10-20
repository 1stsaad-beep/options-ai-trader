"""Test 4 — 'wave personality': indicator behaviour expected in each wave (user's table, PREREG_ROUND_W2.json).
Indicators are computed on the price and on the NEGATED price, so a down wave is scored with the mirrored rules
(RSI -> 100-RSI, MACD and price-vs-average signs flip) by simply reading the negated frame."""
from __future__ import annotations
from functools import lru_cache
import numpy as np
import pandas as pd
from . import bars as B


def _ind(o, h, l, c):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-d).clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    line = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean(); hist = line - line.ewm(span=9, adjust=False).mean()
    m = c.rolling(20).mean(); sd = c.rolling(20).std(ddof=0); pb = (c - (m - 2 * sd)) / (4 * sd).replace(0, np.nan)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1); atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    return pd.DataFrame(dict(c=c, rsi=rsi, rsi5=rsi.shift(5), line=line, hist=hist, pb=pb, e20=c.ewm(span=20, adjust=False).mean(),
                             e50=c.ewm(span=50, adjust=False).mean(), s200=c.rolling(200).mean(), atr=atr,
                             hmax50=hist.rolling(50).max(), hq80=hist.rolling(50).quantile(0.8), lmax50=line.rolling(50).max(),
                             rmax50=rsi.rolling(50).max(), rmin50=rsi.rolling(50).min(), cmax50=c.rolling(50).max(), cmin50=c.rolling(50).min()))


@lru_cache(maxsize=256)
def frames(sym, tf):
    b = B.bars(sym, tf)
    pos = _ind(b["open"], b["high"], b["low"], b["close"])
    neg = _ind(-b["open"], -b["low"], -b["high"], -b["close"])
    return pos, neg


def rules(label, r):
    """list of booleans for the wave label on indicator row r (already oriented to the trend direction)."""
    c, e20, e50, s200, atr = r.c, r.e20, r.e50, r.s200, r.atr
    if label == "1": return [50 <= r.rsi <= 75 and r.rsi > r.rsi5, r.hist > 0, c > e20]
    if label == "2": return [35 <= r.rsi <= 55, r.line > -0.5 * atr, e50 - atr <= c <= e20 + 0.5 * atr, c > s200]
    if label == "3": return [r.rsi > 60, r.hist >= r.hq80, r.pb > 0.8, e20 > e50 > s200, c > e20]
    if label == "4": return [38 <= r.rsi <= 55, r.line > 0 and r.hist < 0, e50 - 0.5 * atr <= c <= e20 + 0.5 * atr, c > s200]
    if label == "5": return [c >= 0.99 * r.cmax50 and r.rsi <= r.rmax50 - 5, r.hist < r.hmax50]
    if label == "A": return [35 <= r.rsi <= 55 and r.rsi < r.rsi5, r.hist < 0, c < e20]
    if label == "B": return [r.rsi <= r.rmax50 - 5, r.line < r.lmax50, abs(c - e20) <= atr]
    if label == "C": return [r.rsi < 40 or (c <= 1.01 * r.cmin50 and r.rsi >= r.rmin50 + 5)]
    return None


def trend_sign(lab, up):
    """+1 if the larger trend this wave belongs to is UP (rules are written for an up trend: 1,3,5,B rise; 2,4,A,C fall)."""
    if lab in ("1", "3", "5", "B"): return 1 if up else -1
    if lab in ("2", "4", "A", "C"): return -1 if up else 1
    return 0


def match(sym, tf, t, cur, up):
    pat, lab = cur.split(":") if ":" in cur else (cur, "")
    if pat in ("TRIANGLE", "DOUBLE_THREE", "DOUBLE_THREE_T", "TRIPLE_THREE") or lab not in ("1", "2", "3", "4", "5", "A", "B", "C"):
        return np.nan
    fr = frames(sym, tf)[0 if trend_sign(lab, up) == 1 else 1]
    t = pd.Timestamp(t)
    if t not in fr.index: return np.nan
    rr = fr.loc[t]
    if rr.isna().any(): return np.nan
    from types import SimpleNamespace
    return float(np.mean(rules(lab, SimpleNamespace(**rr.to_dict()))))
