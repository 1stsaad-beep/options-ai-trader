"""Round 12 step 2: build the feature/label panel for the volatile universe on 15 / 30 / 60-minute bars.
Symbols alternate into group A (discovery) and B (holdout).  Output: results/r12/panel_<F>.pkl"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
from oat_research import data as D
from r4_common import load_daily
import r12_features as FE
from fetch_volatile import VOL

OUT = Path("results/r12"); OUT.mkdir(parents=True, exist_ok=True)


def groups():
    syms = [s for s in VOL if Path(f"data/m5v/{s}.csv").exists()]
    return {s: ("A" if i % 2 == 0 else "B") for i, s in enumerate(syms)}


def build(F: int):
    _, vols = load_daily(); spy = D.load_csv("data/m5a/SPY.csv"); G = groups(); parts = []
    for s, g in G.items():
        m5 = D.load_csv(f"data/m5v/{s}.csv")
        b, X = FE.features(m5, spy, F, vols["VIX"])
        Y = FE.labels(b, (390 // F + 1) * 2)
        P = pd.concat([X, Y], axis=1); P["sym"] = s; P["grp"] = g; P["t"] = b.index
        P = P.iloc[200:]                                   # warm-up
        P = P[P["valid_next"]]
        parts.append(P.reset_index(drop=True))
        print(F, s, g, len(P), flush=True)
    P = pd.concat(parts, ignore_index=True)
    P["sym"] = P["sym"].astype("category"); P["grp"] = P["grp"].astype("category")
    P.to_pickle(OUT / f"panel_{F}.pkl")
    return P


if __name__ == "__main__":
    for F in map(int, sys.argv[1:] or ["15", "30", "60"]):
        build(F)


def build_large(F: int):
    """extra out-of-sample check: the 45 large caps used in earlier rounds (m5a 2016+, m5x 2023+)."""
    import r7_lib as L7
    _, vols = load_daily(); spy = D.load_csv("data/m5a/SPY.csv"); parts = []
    files = {s: f"data/m5a/{s}.csv" for s in L7.ORIG if s not in ("SPY", "QQQ", "IWM")}
    files.update({s: f"data/m5x/{s}.csv" for s in L7.NEW if Path(f"data/m5x/{s}.csv").exists()})
    for s, fp in files.items():
        m5 = D.load_csv(fp).loc["2020-01-01":]
        b, X = FE.features(m5, spy, F, vols["VIX"]); Y = FE.labels(b, (390 // F + 1) * 2)
        P = pd.concat([X, Y], axis=1); P["sym"] = s; P["grp"] = "L"; P["t"] = b.index
        P = P.iloc[200:]; P = P[P["valid_next"]]; parts.append(P.reset_index(drop=True))
    P = pd.concat(parts, ignore_index=True); P["sym"] = P["sym"].astype("category"); P["grp"] = P["grp"].astype("category")
    P.to_pickle(OUT / f"panel_large_{F}.pkl"); print("large", F, len(P), flush=True)
