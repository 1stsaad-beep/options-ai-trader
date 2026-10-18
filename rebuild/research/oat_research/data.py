"""Daily OHLCV loading and validation.

Accepts Yahoo Finance CSV (Date,Open,High,Low,Close,Adj Close,Volume) and Stooq CSV
(Date,Open,High,Low,Close,Volume). When "Adj Close" exists, OHLC are scaled by
Adj/Close so splits and dividends do not create fake gaps (signals and option
moneyness then use adjusted prices consistently).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED = ["open", "high", "low", "close", "volume"]


def load_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    date_col = next(c for c in df.columns if c in ("date", "datetime", "timestamp", "data"))
    df[date_col] = pd.to_datetime(df[date_col], utc=False).dt.tz_localize(None)
    df = df.rename(columns={date_col: "date"}).set_index("date").sort_index()
    for c in REQUIRED + ["adj_close"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=REQUIRED)
    if "adj_close" in df.columns and df["adj_close"].notna().all():
        f = df["adj_close"] / df["close"]
        for c in ("open", "high", "low", "close"):
            df[c] = df[c] * f
    df = df[REQUIRED]
    return validate(df, str(path))


def validate(df: pd.DataFrame, name: str = "") -> pd.DataFrame:
    bad = (df["high"] < df[["open", "close", "low"]].max(axis=1) - 1e-9) | (
        df["low"] > df[["open", "close", "high"]].min(axis=1) + 1e-9) | (df["low"] <= 0)
    if bad.any():
        # Repair tiny vendor inconsistencies instead of dropping days.
        df = df.copy()
        df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
        df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    if df.index.duplicated().any():
        df = df[~df.index.duplicated(keep="last")]
    if len(df) < 300:
        raise ValueError(f"{name}: need >= 300 daily bars, got {len(df)}")
    return df


def load_folder(folder: str | Path) -> dict[str, pd.DataFrame]:
    out = {}
    for p in sorted(Path(folder).glob("*.csv")):
        sym = p.stem.upper().replace("^", "").split("_")[0].split(".")[0]
        try:
            out[sym] = load_csv(p)
        except Exception as e:  # noqa: BLE001 - report and continue
            print(f"skip {p.name}: {e}")
    return out


# ---------------------------------------------------------------------------
# Synthetic data — ONLY for validating the harness (null / planted-edge tests).
# Never use results on this data as evidence of profitability.
# ---------------------------------------------------------------------------

def synthetic(n: int = 3000, seed: int = 0, start_price: float = 100.0, planted_edge: float = 0.0,
              base_vol: float = 0.25) -> pd.DataFrame:
    """GARCH-like volatility clustering + fat tails, no predictable drift unless
    ``planted_edge`` > 0, in which case a compression->breakout continuation drift
    is injected (used to prove the harness can detect a real edge)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2012-01-03", periods=n)
    h = (base_vol / np.sqrt(252)) ** 2
    omega, alpha, beta = h * 0.05, 0.08, 0.87
    close = np.empty(n)
    opn, high, low, vol = (np.empty(n) for _ in range(4))
    prev = start_price
    var = h
    rets = []
    boost = 0
    for i in range(n):
        z = rng.standard_t(5) / np.sqrt(5 / 3)
        r = np.sqrt(var) * z
        if planted_edge and i > 60:
            # Planted rule (known only from data <= i-1): yesterday closed at a
            # 20-day closing high after low short-term realised vol -> add drift
            # for the next 5 days.
            past = np.array(rets[-60:])
            if past[-10:].std() < 0.75 * past.std() and close[i - 1] >= close[i - 20:i].max() - 1e-12:
                boost = 5
            if boost > 0:
                r += planted_edge
                boost -= 1
        rets.append(r)
        gap = np.sqrt(var) * rng.normal(0, 0.3)
        o = prev * np.exp(gap)
        c = prev * np.exp(r)
        wick = np.sqrt(var) * np.abs(rng.normal(0, 0.6, 2))
        opn[i], close[i] = o, c
        high[i] = max(o, c) * (1 + wick[0])
        low[i] = min(o, c) * (1 - wick[1])
        vol[i] = 1e6 * np.exp(rng.normal(0, 0.3)) * (1 + 3 * abs(r) / np.sqrt(var))
        var = omega + alpha * r * r + beta * var
        prev = c
    return pd.DataFrame({"open": opn, "high": high, "low": low, "close": close, "volume": vol}, index=dates)
