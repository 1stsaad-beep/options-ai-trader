"""Round 10 — the best big-move combination found on DISCOVERY, tested as a trade.
Rule (top-1 by discovery lift for 'UP >= 5 % in 2 days', chosen before any trade test):
   Bollinger width percentile (126 d) > 80 %  AND  20-day return < -10 %  AND  SPY 5-day return < -3 %
   -> buy at 15:50 (daily 'as-of 15:50' series), exit at 15:50 two sessions later.
Instruments: STOCK, weekly CALL (delta 0.5, >= 2 days), weekly call DEBIT SPREAD (+1 ATR), LONG call 45-90 d delta 0.75.
Universes: ORIGINAL 15 and NEW 30, REAL option prints 2024-02 -> 2026-10.  Also the stock-only result 2016-2026.
python r10_options.py -> results/r10/OPTIONS.md"""
import json
import numpy as np, pandas as pd
import r4_real_options as R
import r7_lib as L7
import r9_run as R9
from oat_research import indicators as ind, intraday4 as I4, setups4 as S4, shortdated as SD
from r4_common import costs, fmt

OUT = R9.OUT.parent / "r10"


def sig_bigmove(U, spy_asof):
    out = {}
    for s in U.syms:
        a = U.asof[s]; c = a["close"]
        bbp = ind.rolling_percentile(ind.bb_width(c, 20), 126)
        sp = spy_asof["close"].reindex(a.index).ffill()
        m = (bbp > 0.8) & (c / c.shift(20) - 1 < -0.10) & (sp / sp.shift(5) - 1 < -0.03)
        f = S4.frame(a, np.where(m, 1, 0), reason=np.where(m, "big-move setup", ""))
        # exit two sessions later at 15:50 (scheduled)
        f["xsched"] = pd.Series(m.to_numpy(), index=a.index).shift(2, fill_value=False).to_numpy()
        out[s] = I4.to_segments(f, U.seg[s])
    return {s: U.seg[s] for s in out}, out


def main():
    R.CACHE = OUT / "opt_cache_r10.json"      # separate cache file while round 9 runs (merged afterwards)
    spy_asof = L7.Universe("orig").asof["SPY"]
    L = ["# Big-move combination as a trade (backtested)", "",
         "Rule: BB-width percentile > 80 % AND 20-day return < −10 % AND SPY 5-day return < −3 % → buy at 15:50, exit 15:50 two sessions later.", ""]
    store = {}
    for uname in ("orig", "new"):
        U = L7.Universe(uname)
        bars, sigs = sig_bigmove(U, spy_asof)
        # stock-only over the full 5-minute history (2016+ orig, 2023+ new)
        c = SD.SDConfig("bm", SD.SDExit(target_atr=None, stop_atr=None, use_signal_levels=False), target_delta=0.5, min_days=4,
                        budget=0.0001, max_open=200, iv_term=SD.calibrated_term)
        tr_all, _ = SD.run(bars, sigs, c, U.full, U.ivs, costs(U.full), initial=1e9)
        stk = np.array([t.exit_spot / t.entry_spot - 1 for t in tr_all])
        L.append(f"- **{uname}: stock only, all 5-minute history** — {len(stk)} trades, mean {stk.mean()*100:+.2f} %, "
                 f"median {np.median(stk)*100:+.2f} %, win {(stk>0).mean()*100:.0f} %, t {stk.mean()/stk.std(ddof=1)*np.sqrt(len(stk)):.2f}")
        tr = [t for t in tr_all if L7.REAL[0] <= t.entry_time <= L7.REAL[1]]
        rows = L7.replay_path(tr, U.factor)
        df = R9.price_trades(U, tr, rows)
        store[uname] = df
        pd.to_pickle(store, OUT / "options.pkl")
        print(uname, len(df), flush=True)
    L += ["", "| universe | period | STOCK | CALL (weekly) | SPREAD (weekly) | LONG (45–90 d, Δ0.75) |", "|---|---|---|---|---|---|"]
    for uname, df in store.items():
        for pn, m in (("2024-02→2026-10", df.entry > pd.Timestamp("2000-01-01")), ("2024-02→2025-06", df.entry <= L7.DEV_END), ("2025-07→2026-10", df.entry > L7.DEV_END)):
            d = df[m]
            L.append(f"| {uname} | {pn} | {R9.cell(R9.st(d.stock))} | {R9.cell(R9.st(d.call))} | {R9.cell(R9.st(d.spread))} | {R9.cell(R9.st(d.long))} |")
        L.append(f"| {uname} | 2× half-spread | | {R9.cell(R9.st(df.call_2x))} | {R9.cell(R9.st(df.spread_2x))} | {R9.cell(R9.st(df.long_2x))} |")
        L.append(f"| {uname} | entries by month | {', '.join(f'{k}: {v}' for k, v in df.entry.dt.to_period('M').value_counts().sort_index().items())} | | | |")
    (OUT / "OPTIONS.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
