"""Causal indicators on daily OHLCV DataFrames (value at t uses data <= t).
Formulas match trader_core/lib/src/analysis/indicators.dart."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = wilder(d.clip(lower=0), n)
    dn = wilder((-d).clip(lower=0), n)
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(dn != 0, 100.0)


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift()
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return wilder(true_range(df), n)


def macd_hist(close: pd.Series, f: int = 12, s: int = 26, sig: int = 9) -> pd.Series:
    line = ema(close, f) - ema(close, s)
    return line - ema(line, sig)


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["high"].diff()
    dn = -df["low"].diff()
    pdm = up.where((up > dn) & (up > 0), 0.0)
    mdm = dn.where((dn > up) & (dn > 0), 0.0)
    tr = wilder(true_range(df), n)
    pdi = 100 * wilder(pdm, n) / tr
    mdi = 100 * wilder(mdm, n) / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return wilder(dx.fillna(0), n)


def stoch_k(df: pd.DataFrame, n: int = 14, smooth: int = 3) -> pd.Series:
    hh = df["high"].rolling(n).max()
    ll = df["low"].rolling(n).min()
    raw = 100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)
    return raw.rolling(smooth).mean()


def realized_vol(close: pd.Series, n: int, bars_per_year: float = 252) -> pd.Series:
    return np.log(close).diff().rolling(n, min_periods=n).std() * np.sqrt(bars_per_year)


def bars_per_day(df: pd.DataFrame) -> int:
    """1 for daily data, ~7 for hourly, ~78 for 5-minute, ~390 for 1-minute."""
    counts = pd.Series(df.index.normalize()).value_counts()
    return max(1, int(round(counts.median())))


def rolling_percentile(s: pd.Series, n: int) -> pd.Series:
    """Percentile rank (0..1) of today's value within the trailing n values (inclusive)."""
    return s.rolling(n, min_periods=n).apply(lambda w: (w[:-1] < w[-1]).mean(), raw=True)


def bb_width(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.Series:
    m = sma(close, n)
    sd = close.rolling(n).std(ddof=0)
    return 2 * k * sd / m


def close_location(df: pd.DataFrame) -> pd.Series:
    """0 = closed at the low, 1 = closed at the high."""
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    return ((df["close"] - df["low"]) / rng).fillna(0.5)


def obv(df: pd.DataFrame) -> pd.Series:
    return (np.sign(df["close"].diff()).fillna(0) * df["volume"]).cumsum()


def pivots(df: pd.DataFrame, left: int = 3, right: int = 2):
    """Confirmed strict fractal pivots: list of (index, confirmed_index, price, is_high).
    A pivot at i is usable only from bar i+right (causal)."""
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    out = []
    for i in range(left, len(df) - right):
        win_h = np.r_[h[i - left:i], h[i + 1:i + right + 1]]
        win_l = np.r_[l[i - left:i], l[i + 1:i + right + 1]]
        is_h = (h[i] > win_h).all()
        is_l = (l[i] < win_l).all()
        if is_h == is_l:
            continue
        out.append((i, i + right, h[i] if is_h else l[i], bool(is_h)))
    return out


def zigzag(piv, min_move: float = 0.0):
    """Alternating swings (same algorithm as alternatingSwings in Dart)."""
    out = []
    for p in piv:
        if not out:
            out.append(p)
            continue
        last = out[-1]
        if last[3] == p[3]:
            if (p[2] > last[2]) if p[3] else (p[2] < last[2]):
                out[-1] = p
            continue
        if min_move > 0 and abs(p[2] - last[2]) / last[2] < min_move:
            continue
        out.append(p)
    return out
