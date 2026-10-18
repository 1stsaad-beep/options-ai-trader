"""Shared loading / periods for round 4 (pre-registered in results/r4/PREREG.json)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from oat_research import data as D
from oat_research import engines_v2 as E
from oat_research import options_model as om
from oat_research import setups4 as S4
from oat_research import shortdated as SD

ETFS = ("SPY", "QQQ", "IWM")
VOLS = ("VIX", "VIX9D", "VIX1D", "VIX3M", "VXN")

# Periods (daily). Discovery = choose rules/params. Validation = confirm, no changes after.
# Holdout = last ~6 months, looked at ONCE at the very end.
DISC = (pd.Timestamp("1999-01-01"), pd.Timestamp("2012-12-31"))
VALID = (pd.Timestamp("2013-01-01"), pd.Timestamp("2026-04-15"))
HOLD = (pd.Timestamp("2026-04-16"), pd.Timestamp("2026-10-16 23:59"))
# Hourly (2023-11 -> 2026-10)
H_DISC = (pd.Timestamp("2023-11-17"), pd.Timestamp("2025-04-30 23:59"))
H_VALID = (pd.Timestamp("2025-05-01"), pd.Timestamp("2026-04-15 23:59"))

OUT = Path("results/r4")
OUT.mkdir(parents=True, exist_ok=True)


def load_daily():
    raw = D.load_folder("data/d1")
    vols = {k: raw.pop(k)["close"] for k in VOLS if k in raw}
    return raw, vols


def load_hourly():
    return D.load_folder("data/h1")


def contexts(data):
    spy = data["SPY"]
    return {s: E.Ctx(df, spy if s != "SPY" else None) for s, df in data.items()}


def costs(data, etf=0.03, stock=0.06, vrp=1.10, mult=1.0):
    """Weekly options: wider spreads than the 30-60 DTE contracts of rounds 1-3."""
    return {s: om.OptionCosts(spread_pct=(etf if s in ETFS else stock) * mult, min_half_spread=0.02 * mult, vrp=vrp)
            for s in data}


def prereg_write(obj):
    p = OUT / "PREREG.json"
    p.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def fmt(x, pct=False, p=2):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x * 100:+.1f}%" if pct else f"{x:.{p}f}"
