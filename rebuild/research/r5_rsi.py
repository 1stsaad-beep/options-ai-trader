"""Round 5 — MTF RSI: underlying edge of every variant (discovery 2016-2020, validation 2021-2026).
Outcomes are direction-adjusted (positive = the option's direction was right), in daily ATR.
python r5_rsi.py -> results/r5/RSI_UNDERLYING.md, results/r5/rsi_und.pkl"""
import itertools
from pathlib import Path
import numpy as np, pandas as pd
from oat_research import mtf, indicators as ind, setups4 as S4
from r5_common import DISC, VALID, HDR, SYMS, line, load, outcomes, summary

OUT = Path("results/r5"); OUT.mkdir(parents=True, exist_ok=True)


def baseline(df5, ob, os_, n, ltf=15):
    lo = S4.resample(df5, ltf); h1 = S4.resample(df5, 60)
    rh = mtf.align(ind.rsi(h1["close"], n), mtf.bar_end(h1, 60), mtf.bar_end(lo, ltf)).to_numpy()
    d = np.where(rh > ob, -1, np.where(rh < os_, 1, 0))
    d[np.arange(len(d)) % 4 != 0] = 0          # every 4th bar (1 per hour) to keep it light
    return lo, S4.frame(lo, d)


def main():
    m5, full, vols = load()
    L = ["# MTF RSI — underlying outcomes (daily ATR units, entry next 15-min bar open)", "", *HDR]
    store = {}
    variants = [(n, th, tr, 15) for n, th, tr in itertools.product((14, 9), ((70, 30), (75, 25), (80, 20)), ("reentry", "fail", "div"))]
    variants += [(14, (70, 30), tr, 5) for tr in ("reentry", "fail", "div")]
    for n, (ob, os_), trig, ltf in [(14, (70, 30), "BASE", 15), (14, (80, 20), "BASE", 15)] + variants:
        rows = {"puts": {"DISC": [], "VALID": []}, "calls": {"DISC": [], "VALID": []}}
        for s in SYMS:
            if trig == "BASE":
                lo, sig = baseline(m5[s], ob, os_, n)
            else:
                lo = S4.resample(m5[s], ltf)
                sig = mtf.mtf_rsi(m5[s], n=n, ob=ob, os_=os_, trigger=trig, ltf=ltf)
            bpd = 390 // ltf
            for pn, per in (("DISC", DISC), ("VALID", VALID)):
                w = outcomes(lo, sig, full[s], bpd, per)
                if not w.empty:
                    w["sym"] = s
                    rows["puts"][pn].append(w[w.dir < 0]); rows["calls"][pn].append(w[w.dir > 0])
        name = f"{'BASELINE hourly RSI extreme' if trig == 'BASE' else trig} RSI{n} {ob}/{os_} {ltf}m"
        for side in ("puts", "calls"):
            for pn in ("DISC", "VALID"):
                w = pd.concat(rows[side][pn]) if rows[side][pn] else pd.DataFrame()
                store[(name, side, pn)] = w
                L.append(line(f"{name} — {side}", pn, summary(w)))
        print(name, flush=True)
    (OUT / "RSI_UNDERLYING.md").write_text("\n".join(L), encoding="utf-8")
    pd.to_pickle(store, OUT / "rsi_und.pkl")
    print("\n".join(L))


if __name__ == "__main__":
    main()
