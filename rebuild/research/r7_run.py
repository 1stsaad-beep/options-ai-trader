"""Round 7 — independent test + development of the report's best candidates.

Step 1 (develop, ORIGINAL 15 symbols, real prices, DEV 2024-02 -> 2025-06 only): exit / contract /
        confluence variants; the best variant per strategy (n >= 20) is frozen.
Step 2 (judge): frozen base rule and developed rule on (a) ORIGINAL test 2025-07 -> 2026-10 and
        (b) 30 NEW symbols never used before, full 2024-02 -> 2026-10 (pure out-of-sample).
Audit: entries delayed by one bar (should weaken, not flip, if there is no look-ahead).
python r7_run.py dev | judge
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
import r7_lib as L7

OUT = Path("results/r7"); OUT.mkdir(parents=True, exist_ok=True)

EXIT_VARIANTS = {"base": {}, "TP+50%": dict(tp=0.5), "TP+100%": dict(tp=1.0), "SL-50%": dict(sl=0.5),
                 "TP+50% SL-50%": dict(tp=0.5, sl=0.5), "TP+100% SL-50%": dict(tp=1.0, sl=0.5)}
RUN_VARIANTS = {   # name -> (sig_kw, overrides)
    "MTF-RSI Call": [("expiry >= 5 days", {}, dict(md=5)), ("delta 0.6", {}, dict(delta=0.6)),
                     ("+ daily close > SMA200", dict(regime=True), {}), ("hold 3 sessions", {}, dict(ex=(0.75, 1.0, 78)))],
    "Squeeze-Breakout Call (daily @15:50)": [("expiry >= 5 days", {}, dict(md=5)), ("delta 0.6", {}, dict(delta=0.6)),
                                             ("volume 1.2x", dict(vol_mult=1.2), {}), ("target 1.5 ATR / stop 0.75", {}, dict(ex=(1.5, 0.75, 30)))],
    "Trend-Dip Call @15:50": [("expiry >= 5 days", {}, dict(md=5)), ("delta 0.6", {}, dict(delta=0.6)),
                              ("target 1.0 ATR", {}, dict(ex=(1.0, 1.0, None)))],
}


def per(df, lo, hi):
    return df[(df.entry > lo) & (df.entry <= hi)] if len(df) else df


def dev():
    U = L7.Universe("orig")
    lines = ["# Round 7 — development on the ORIGINAL 15 symbols, real option prices, DEV 2024-02 → 2025-06", "", *L7.HDR]
    chosen, cache = {}, {}
    for name in L7.CANDIDATES:
        lines += [f"| **{name}** | | | | | | | | |"]
        best = None
        runs = [("base rule", {}, {})] + RUN_VARIANTS[name]
        for rname, skw, ov in runs:
            rows = L7.replay_path(L7.trades(U, name, skw, **ov), U.factor)
            cache[(name, rname)] = rows
            exits = EXIT_VARIANTS if rname == "base rule" else {"base": {}}
            for ename, ekw in exits.items():
                df = L7.realize(rows, **ekw)
                d = per(df, pd.Timestamp("2000-01-01"), L7.DEV_END)
                st = L7.stats(d)
                label = f"{rname} · {ename}" if rname == "base rule" else rname
                lines.append(L7.row(f"dev — {label}", st))
                if st["n"] >= 20 and (best is None or st["exp"] > best[0]):
                    best = (st["exp"], rname, skw, ov, ekw, label)
                print(lines[-1], flush=True)
        chosen[name] = dict(run=best[1], sig_kw=best[2], overrides=best[3], exits=best[4], label=best[5], dev_exp=best[0])
        lines.append("")
    (OUT / "DEV.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT / "CHOSEN.json").write_text(json.dumps(chosen, indent=2, default=str))


def judge():
    chosen = json.loads((OUT / "CHOSEN.json").read_text())
    lines = ["# Round 7 — judgement (rules frozen before this run)", "",
             "**Base** = rule exactly as in the report. **Developed** = variant chosen on DEV (original 15, 2024-02 → 2025-06).", ""]
    store = {}
    for uname in ("orig", "new"):
        U = L7.Universe(uname)
        lines += [f"## {'ORIGINAL 15 symbols — test period 2025-07 → 2026-10' if uname == 'orig' else f'NEW {len(U.syms)} symbols (never used) — full 2024-02 → 2026-10'}", "", *L7.HDR]
        for name, ch in chosen.items():
            for label, skw, ov, ekw in (("base", {}, {}, {}), (f"developed ({ch['label']})", ch["sig_kw"], ch["overrides"], ch["exits"])):
                rows = L7.replay_path(L7.trades(U, name, skw, **ov), U.factor)
                df = L7.realize(rows, **ekw)
                if uname == "orig":
                    df = per(df, L7.DEV_END, pd.Timestamp("2030-01-01"))
                store[(uname, name, label)] = df
                lines.append(L7.row(f"{name} — {label}", L7.stats(df)))
                if uname == "new":
                    lines.append(L7.row("   ↳ 2× half-spread", L7.stats(L7.realize(rows, hs_mult=2.0, **ekw))))
                    lines.append(L7.row("   ↳ at VWAP (no spread)", L7.stats(L7.realize(rows, mid=True, **ekw))))
                    top = df["ret"].nlargest(5).index if len(df) else []
                    lines.append(L7.row("   ↳ without 5 best", L7.stats(df.drop(top))))
                    for lo, hi, nm in ((pd.Timestamp("2000-01-01"), L7.DEV_END, "2024-02→2025-06"), (L7.DEV_END, pd.Timestamp("2030-01-01"), "2025-07→2026-10")):
                        lines.append(L7.row(f"   ↳ {nm}", L7.stats(per(df, lo, hi))))
                print(lines[-1], flush=True)
            if uname == "new":
                # audit: delay the entry by one bar
                fn, base = L7.CANDIDATES[name]
                bars, sigs, bm = fn(U)
                sigs = {s: f.assign(dir=f["dir"].shift(1).fillna(0).astype(int)) for s, f in sigs.items()}
                p = dict(base)
                tr, _ = L7.SD.run(bars, sigs, L7.cfg(name, bm, p["delta"], p["md"], p["ex"]), U.full, U.ivs, L7.costs(U.full), *L7.REAL)
                lines.append(L7.row("   ↳ AUDIT: base with entry delayed one bar", L7.stats(L7.realize(L7.replay_path(tr, U.factor)))))
        lines.append("")
        (OUT / "JUDGE.md").write_text("\n".join(lines), encoding="utf-8")
    pd.to_pickle(store, OUT / "judge.pkl")


if __name__ == "__main__":
    {"dev": dev, "judge": judge}[sys.argv[1]]()
