"""Standard indicators computed in CODE (spec §4 get_indicators). Pure Python, oldest-first lists, None where the
indicator is not defined yet. Definitions (fixed, documented so results are reproducible):
- SMA(n); EMA(n) seeded with the SMA of the first n values, alpha = 2/(n+1)
- RSI(14) Wilder; ATR(14) Wilder (true range); ADX/+DI/-DI(14) Wilder
- MACD(12, 26, 9): EMA12 - EMA26, signal EMA9 of the line, histogram = line - signal
- Bollinger(20, 2): SMA20 +/- 2 x population standard deviation; width = (upper - lower) / middle
- Keltner(20, 10, 2): EMA20 +/- 2 x ATR10
- Session VWAP with +/-1 and +/-2 volume-weighted standard deviation bands (resets each New York session)
- Anchored VWAP from an anchor time
- Volume profile: fixed number of price bins over the bars; POC = bin with most volume; value area = 70 % of volume
- Relative volume: cumulative session volume up to the current bar time vs the average over the previous sessions
- Relative strength: symbol return minus benchmark return over the same bars"""
from __future__ import annotations
import math
from . import nyse


def sma(x, n):
    out, s = [None] * len(x), 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n: s -= x[i - n]
        if i >= n - 1: out[i] = s / n
    return out


def ema(x, n):
    out = [None] * len(x)
    if len(x) < n: return out
    a = 2 / (n + 1)
    e = sum(x[:n]) / n
    out[n - 1] = e
    for i in range(n, len(x)):
        e = a * x[i] + (1 - a) * e
        out[i] = e
    return out


def _wilder(x, n, start):
    """Wilder smoothing of x beginning at index start (first value = mean of x[start:start+n])."""
    out = [None] * len(x)
    if len(x) - start < n: return out
    s = sum(x[start:start + n]) / n
    out[start + n - 1] = s
    for i in range(start + n, len(x)):
        s = (s * (n - 1) + x[i]) / n
        out[i] = s
    return out


def rsi(c, n=14):
    out = [None] * len(c)
    if len(c) <= n: return out
    g = [0.0] + [max(c[i] - c[i - 1], 0.0) for i in range(1, len(c))]
    l = [0.0] + [max(c[i - 1] - c[i], 0.0) for i in range(1, len(c))]
    ag, al = _wilder(g, n, 1), _wilder(l, n, 1)
    for i in range(len(c)):
        if ag[i] is None: continue
        out[i] = 100.0 if al[i] == 0 else 100 - 100 / (1 + ag[i] / al[i])
    return out


def true_range(h, l, c):
    return [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]


def atr(h, l, c, n=14):
    return _wilder(true_range(h, l, c), n, 0)


def macd(c, fast=12, slow=26, signal=9):
    ef, es = ema(c, fast), ema(c, slow)
    line = [None if a is None or b is None else a - b for a, b in zip(ef, es)]
    first = next((i for i, v in enumerate(line) if v is not None), None)
    sig = [None] * len(c)
    if first is not None:
        s = ema(line[first:], signal)
        sig[first:] = s
    hist = [None if a is None or b is None else a - b for a, b in zip(line, sig)]
    return line, sig, hist


def bollinger(c, n=20, k=2.0):
    mid = sma(c, n)
    up, lo, width = [None] * len(c), [None] * len(c), [None] * len(c)
    for i in range(n - 1, len(c)):
        w = c[i - n + 1:i + 1]
        m = mid[i]
        sd = math.sqrt(sum((v - m) ** 2 for v in w) / n)
        up[i], lo[i] = m + k * sd, m - k * sd
        width[i] = (up[i] - lo[i]) / m if m else None
    return mid, up, lo, width


def keltner(h, l, c, n=20, atr_n=10, k=2.0):
    mid, a = ema(c, n), atr(h, l, c, atr_n)
    up = [None if m is None or x is None else m + k * x for m, x in zip(mid, a)]
    lo = [None if m is None or x is None else m - k * x for m, x in zip(mid, a)]
    return mid, up, lo


def adx(h, l, c, n=14):
    pdm = [0.0] + [max(h[i] - h[i - 1], 0.0) if h[i] - h[i - 1] > l[i - 1] - l[i] else 0.0 for i in range(1, len(c))]
    ndm = [0.0] + [max(l[i - 1] - l[i], 0.0) if l[i - 1] - l[i] > h[i] - h[i - 1] else 0.0 for i in range(1, len(c))]
    tr = true_range(h, l, c)
    str_, sp, sn = _wilder(tr, n, 1), _wilder(pdm, n, 1), _wilder(ndm, n, 1)
    pdi = [None if t in (None, 0) else 100 * p / t for p, t in zip(sp, str_)]
    ndi = [None if t in (None, 0) else 100 * q / t for q, t in zip(sn, str_)]
    dx = [None if a is None or b is None or a + b == 0 else 100 * abs(a - b) / (a + b) for a, b in zip(pdi, ndi)]
    first = next((i for i, v in enumerate(dx) if v is not None), None)
    adx_ = [None] * len(c)
    if first is not None:
        adx_[first:] = _wilder([v if v is not None else 0.0 for v in dx[first:]], n, 0)
    return adx_, pdi, ndi


def session_vwap(bars):
    """bars: dicts with t (UTC datetime), h, l, c, v. Resets at each New York date."""
    out = []
    key, pv, vv, pv2 = None, 0.0, 0.0, 0.0
    for b in bars:
        k = nyse.date_key(b["t"])
        if k != key: key, pv, vv, pv2 = k, 0.0, 0.0, 0.0
        tp = (b["h"] + b["l"] + b["c"]) / 3
        pv += tp * b["v"]; vv += b["v"]; pv2 += tp * tp * b["v"]
        if vv <= 0: out.append(None); continue
        m = pv / vv
        sd = math.sqrt(max(pv2 / vv - m * m, 0.0))
        out.append(dict(vwap=m, up1=m + sd, dn1=m - sd, up2=m + 2 * sd, dn2=m - 2 * sd))
    return out


def anchored_vwap(bars, anchor_t):
    pv = vv = 0.0
    out = []
    for b in bars:
        if b["t"] < anchor_t: out.append(None); continue
        tp = (b["h"] + b["l"] + b["c"]) / 3
        pv += tp * b["v"]; vv += b["v"]
        out.append(pv / vv if vv > 0 else None)
    return out


def volume_profile(bars, bins=40, value_area=0.70):
    if not bars: return None
    lo, hi = min(b["l"] for b in bars), max(b["h"] for b in bars)
    if hi <= lo: return dict(poc=lo, vah=hi, val=lo, bins=[(lo, sum(b["v"] for b in bars))])
    step = (hi - lo) / bins
    vol = [0.0] * bins
    for b in bars:                                      # spread each bar's volume evenly over its range
        a = min(int((b["l"] - lo) / step), bins - 1)
        z = min(int((b["h"] - lo) / step), bins - 1)
        share = b["v"] / (z - a + 1)
        for j in range(a, z + 1): vol[j] += share
    poc_i = max(range(bins), key=lambda j: vol[j])
    total, inside, a, z = sum(vol), vol[poc_i], poc_i, poc_i
    while total > 0 and inside / total < value_area and (a > 0 or z < bins - 1):
        up = vol[z + 1] if z < bins - 1 else -1
        dn = vol[a - 1] if a > 0 else -1
        if up >= dn: z += 1; inside += vol[z]
        else: a -= 1; inside += vol[a]
    mid = lambda j: lo + (j + 0.5) * step
    return dict(poc=mid(poc_i), vah=lo + (z + 1) * step, val=lo + a * step,
                bins=[(round(mid(j), 4), round(v, 2)) for j, v in enumerate(vol)])


def relative_volume(bars, sessions=10):
    """Cumulative volume of the latest session up to the last bar's time of day, divided by the average cumulative
    volume of the previous `sessions` sessions up to the same time of day."""
    if not bars: return None
    by = {}
    for b in bars: by.setdefault(nyse.date_key(b["t"]), []).append(b)
    days = sorted(by)
    cur = by[days[-1]]
    tod = nyse.wall(cur[-1]["t"]).time()
    now_cum = sum(b["v"] for b in cur)
    prev = [sum(b["v"] for b in by[d] if nyse.wall(b["t"]).time() <= tod) for d in days[-1 - sessions:-1]]
    prev = [p for p in prev if p > 0]
    if not prev: return None
    return now_cum / (sum(prev) / len(prev))


def relative_strength(closes, bench_closes, n=None):
    """Return of the symbol minus the benchmark's over the last n bars (all bars when n is None), in percent."""
    k = min(len(closes), len(bench_closes))
    if k < 2: return None
    n = k - 1 if n is None else min(n, k - 1)
    r = closes[-1] / closes[-1 - n] - 1
    rb = bench_closes[-1] / bench_closes[-1 - n] - 1
    return 100 * (r - rb)
