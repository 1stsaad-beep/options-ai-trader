"""Round 4b: development directly on REAL option prices (Alpaca option bars, Feb 2024+).

The Black-Scholes proxy under-priced the options our signals buy (real premiums 13-79%
higher), so every candidate is now judged on real prints:
  dev  = 2024-02-05 -> 2025-06-30 : choose contract (delta / expiry) and exit per strategy
  test = 2025-07-01 -> 2026-10-16 : frozen choice, run once
python r4_real_dev.py -> results/r4/REAL_DEV.md, results/r4/real_dev.pkl
"""
from __future__ import annotations

import itertools
import json
from dataclasses import replace

import numpy as np
import pandas as pd

import r4_real_options as R
from oat_research import setups4 as S4
from oat_research import shortdated as SD
from r4_common import OUT, costs, fmt
from r4_final import RULES, build

DEV = (pd.Timestamp("2024-02-05"), pd.Timestamp("2025-06-30 23:59"))
TEST = (pd.Timestamp("2025-07-01"), pd.Timestamp("2026-10-16 23:59"))


def pre_fomc_sigs(B, exit_at="12:00"):
    fomc = S4.load_fomc()
    out = {}
    for s in ("SPY", "QQQ", "IWM"):
        sg = B["seg"][s]
        idx = sg.index
        day = idx.normalize()
        days = pd.DatetimeIndex(sorted(set(day)))
        pos = {d: i for i, d in enumerate(days)}
        pre = {days[pos[f] - 1] for f in fomc if f in pos and pos[f] >= 1}
        hm = idx.hour * 60 + idx.minute
        h, m = map(int, exit_at.split(":"))
        sig = day.isin(list(pre)) & (hm == 13 * 60 + 55)
        ex = day.isin(list(fomc)) & (hm == h * 60 + m)
        out[s] = S4.frame(sg, np.where(sig, 1, 0), reason=np.where(sig, "pre-FOMC", ""), min_days=2, xsched=ex)
    return out


def variants():
    V = []
    for delta, md, ex in itertools.product((0.7, 0.85), (2, 5), ((0.75, 1.0), (None, None))):
        V.append(("A Trend-dip @15:50", dict(delta=delta, min_days=md, target_atr=ex[0], stop_atr=ex[1])))
    for delta, md in itertools.product((0.5, 0.7, 0.85), (2, 5)):
        V.append(("B Wave-2/B exhaustion @15:50", dict(delta=delta, min_days=md)))
    for delta in (0.7, 0.85):
        V.append(("C ORB-5 in play", dict(delta=delta)))
        V.append(("D Noise-area momentum", dict(delta=delta)))
    for delta, ex_at in itertools.product((0.5, 0.7), ("12:00", "13:55")):
        V.append(("Pre-FOMC (ETFs)", dict(delta=delta, exit_at=ex_at)))
    return V


def make_cfg(name, kw):
    if name == "Pre-FOMC (ETFs)":
        return SD.SDConfig(name, SD.SDExit(target_atr=None, stop_atr=None, use_signal_levels=False), target_delta=kw["delta"],
                           min_days=2, budget=0.02, max_open=5)
    r = dict(RULES[name])
    r.update({k: v for k, v in kw.items() if k in r})
    if r["bars"] == "segments":
        ex = SD.SDExit(target_atr=r["target_atr"], stop_atr=r["stop_atr"], use_signal_levels=False)
        return SD.SDConfig(name, ex, target_delta=r["delta"], min_days=r["min_days"], budget=r["budget"], max_open=5)
    ex = SD.SDExit(target_atr=None, stop_atr=None, use_signal_levels=True, opt_stop=r["opt_stop"], cutoff_hours_before_expiry=0.0)
    return SD.SDConfig(name, ex, target_delta=r["delta"], min_days=r["min_days"], budget=r["budget"], max_open=5, bar_minutes=5,
                       daily_expiry_syms=("SPY", "QQQ"))


def trades_for(B, name, kw, period):
    if name == "Pre-FOMC (ETFs)":
        sigs = pre_fomc_sigs(B, kw["exit_at"])
        bars = {s: B["seg"][s] for s in sigs}
    else:
        sigs = B["sigs"][name]
        bars = {s: B["bars"][RULES[name]["bars"]][s] for s in sigs}
    tr, _ = SD.run(bars, sigs, make_cfg(name, kw), B["full"], B["ivs"], costs(B["full"]), *period)
    return tr


def stats(df):
    ok = df[df.status == "ok"]
    r = ok["real"]
    if len(r) < 3:
        return dict(n=len(r), exp=np.nan, vw=np.nan, win=np.nan, t=np.nan, model=np.nan)
    return dict(n=len(r), exp=r.mean(), vw=ok["real_vwap"].mean(), win=(r > 0).mean(), t=r.mean() / r.std(ddof=1) * np.sqrt(len(r)),
                model=ok["model"].mean())


def main():
    B = build()
    factor = {}
    for s in B["full"]:
        factor[s] = (R.stock_daily(s, "raw") / R.stock_daily(s, "all")).dropna()
    L = ["# Round 4b — development on real option prices", "",
         "Fill: 5-min option-bar VWAP ± half-spread (ETF 1.5%, stock 3%) + $0.65/contract/side.", "",
         "## Dev 2024-02 → 2025-06 (all variants)", "", "| strategy | variant | n | REAL exp | @VWAP | win | t | model exp |", "|---|---|---|---|---|---|---|---|"]
    res = {}
    for name, kw in variants():
        df = R.replay(trades_for(B, name, kw, DEV), factor)
        R.CACHE.write_text(json.dumps(R.cache))
        st = stats(df)
        res[(name, json.dumps(kw))] = st
        L.append(f"| {name} | {kw} | {st['n']} | {fmt(st['exp'], True)} | {fmt(st['vw'], True)} | {fmt(st['win'])} | {fmt(st['t'])} | {fmt(st['model'], True)} |")
        print(L[-1], flush=True)
    L += ["", "## Test 2025-07 → 2026-10 (best dev variant per strategy, n ≥ 20, frozen)", "",
          "| strategy | chosen | dev n | dev REAL exp | test n | **test REAL exp** | test @VWAP | test win | test t | test model exp |", "|---|---|---|---|---|---|---|---|---|---|"]
    chosen = {}
    for name in dict.fromkeys(n for n, _ in variants()):
        cands = [(k, v) for k, v in res.items() if k[0] == name and v["n"] >= 20 and np.isfinite(v["exp"])]
        if not cands:
            continue
        (nm, kws), st = max(cands, key=lambda kv: kv[1]["exp"])
        kw = json.loads(kws)
        chosen[name] = kw
        df = R.replay(trades_for(B, name, kw, TEST), factor)
        R.CACHE.write_text(json.dumps(R.cache))
        tt = stats(df)
        res[("TEST", name)] = tt
        L.append(f"| {name} | {kw} | {st['n']} | {fmt(st['exp'], True)} | {tt['n']} | **{fmt(tt['exp'], True)}** | {fmt(tt['vw'], True)} | "
                 f"{fmt(tt['win'])} | {fmt(tt['t'])} | {fmt(tt['model'], True)} |")
        print(L[-1], flush=True)
    (OUT / "REAL_DEV.md").write_text("\n".join(L), encoding="utf-8")
    (OUT / "REAL_DEV_CHOSEN.json").write_text(json.dumps(chosen, indent=2))
    pd.to_pickle(res, OUT / "real_dev.pkl")


if __name__ == "__main__":
    main()
