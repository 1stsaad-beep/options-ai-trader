"""Round 4: 'act at the close' on the long daily history (1999-2026).
Each session = two bars: [09:30, 15:59) and a closing print [15:59, 16:00) at the close.
A signal computed on the day bar fills at the closing print (proxy for the 15:50 order
validated on 5-minute data in r4_intraday*.py). Discovery 1999-2012, validation 2013 - 2026-04-15.
python r4_close.py -> results/r4/CLOSE.md, PREREG_CLOSE.json, close.pkl"""
import itertools, json
import numpy as np, pandas as pd
from oat_research import setups4 as S4, shortdated as SD
from r4_common import DISC, VALID, ETFS, OUT, contexts, costs, fmt, load_daily

def two_bar(df):
    a = df[["open", "high", "low", "close", "volume"]].copy()
    a.index = df.index + pd.Timedelta(hours=9, minutes=30)
    a["end"] = df.index + pd.Timedelta(hours=15, minutes=59)
    b = pd.DataFrame({"open": df["close"], "high": df["close"], "low": df["close"], "close": df["close"], "volume": 0}, index=df.index)
    b.index = df.index + pd.Timedelta(hours=15, minutes=59)
    b["end"] = df.index + pd.Timedelta(hours=16)
    out = pd.concat([a, b]).sort_index()
    out.index.name = "date"
    return out

def place(sig, bars):
    """daily frame -> on the day bar (09:30 start)."""
    s = sig.copy()
    s.index = sig.index + pd.Timedelta(hours=9, minutes=30)
    s = s.reindex(bars.index)
    s["dir"] = s["dir"].fillna(0).astype(int)
    s["reason"] = s["reason"].fillna("")
    for c in ("xsched", "xcond"):
        s[c] = s[c].fillna(False).astype(bool)
    return s

def pre_fomc_close(ctx, fomc, cal):
    """Buy at the close the day before the statement, sell at the close of statement day."""
    df = ctx.df
    pos = {d: i for i, d in enumerate(cal)}
    sig_days = {cal[pos[f] - 1] for f in fomc if f in pos and pos[f] >= 1}
    sig = df.index.isin(list(sig_days))
    ex = df.index.isin(list(fomc))
    return S4.frame(df, np.where(sig, 1, 0), reason=np.where(sig, "pre-FOMC close->close", ""), min_days=2, xsched=ex)

def cfg_for(delta, ex, md):
    tgt, stp, hold = ex
    return SD.SDConfig("close", SD.SDExit(target_atr=tgt, stop_atr=stp, use_signal_levels=False, max_hold_bars=hold),
                       target_delta=delta, min_days=md, budget=0.02, max_open=5)

GRID = list(itertools.product((0.5, 0.7), ((0.5, 1.0, None), (0.75, 1.0, None), (None, None, None)), (2, 5)))

def main():
    data, vols = load_daily()
    ctxs = contexts(data)
    cal = S4.trading_calendar(data["SPY"].index)
    vix = vols["VIX"]
    bars = {s: two_bar(df) for s, df in data.items()}
    ivs = SD.iv_table(data, vols)
    c1, c2, ch = costs(data), costs(data, mult=2.0), costs(data, mult=0.5)
    fomc = S4.load_fomc()
    stocks = [s for s in data if s not in ETFS]
    strat = {
        "ETF dip @close": {s: place(S4.etf_dip(ctxs[s], vix), bars[s]) for s in ETFS},
        "Trend dip stocks @close": {s: place(S4.etf_dip(ctxs[s], vix), bars[s]) for s in stocks},
        "Trend dip all 15 @close": {s: place(S4.etf_dip(ctxs[s], vix), bars[s]) for s in data},
        "Wave-2/B exhaustion @close": {s: place(S4.wave_exhaustion(ctxs[s], S4.weekly_trend(df)), bars[s]) for s, df in data.items()},
        "Control trend+RSI2 both sides @close": {s: place(S4.wave_exhaustion(ctxs[s], S4.weekly_trend(df), control=True), bars[s]) for s, df in data.items()},
        "Pre-FOMC close→close": {s: place(pre_fomc_close(ctxs[s], fomc, cal), bars[s]) for s in ETFS},
        "ETF bear-rally puts @close": {s: place(S4.etf_rip_put(ctxs[s]), bars[s]) for s in ETFS},
        "VIX spike reversal @close": {s: place(S4.vix_reversal(ctxs[s], vix), bars[s]) for s in ETFS},
    }
    L = ["# Round 4 — act at the close, long history (weekly options)", "",
         "| strategy | period | chosen delta / exit / min days | n | win | avg win | avg loss | exp/trade | PF | t(week) | ½ spr | 2× spr | maxDD* |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    prereg, store = {}, {}
    for name, sigs in strat.items():
        b = {s: bars[s] for s in sigs}
        best, scb, grid = None, -9e9, {}
        for g in GRID:
            sm = SD.summarize(*SD.run(b, sigs, cfg_for(*g), data, ivs, c1, *DISC))
            grid[g] = sm
            sc = sm.get("t_week", -9) if sm["n"] >= 60 else -9
            if sc > scb: best, scb = g, sc
        sm = grid[best]
        prereg[name] = dict(delta=best[0], exit=best[1], min_days=best[2])
        L.append(f"| {name} | disc 1999–2012 | {best[0]} / {best[1]} / {best[2]} | {sm['n']} | {fmt(sm.get('win'))} | {fmt(sm.get('avg_win'), True)} | "
                 f"{fmt(sm.get('avg_loss'), True)} | {fmt(sm.get('exp'), True)} | {fmt(sm.get('pf_cash'))} | {fmt(sm.get('t_week'))} | | | |")
        cfg = cfg_for(*best)
        tr, nav = SD.run(b, sigs, cfg, data, ivs, c1, *VALID)
        sv = SD.summarize(tr, nav)
        s2 = SD.summarize(*SD.run(b, sigs, cfg, data, ivs, c2, *VALID))
        sh = SD.summarize(*SD.run(b, sigs, cfg, data, ivs, ch, *VALID))
        L.append(f"| {name} | valid 2013–26 | | {sv['n']} | {fmt(sv.get('win'))} | {fmt(sv.get('avg_win'), True)} | {fmt(sv.get('avg_loss'), True)} | "
                 f"{fmt(sv.get('exp'), True)} | {fmt(sv.get('pf_cash'))} | {fmt(sv.get('t_week'))} | {fmt(sh.get('exp'), True)} | {fmt(s2.get('exp'), True)} | {fmt(sv.get('max_dd'), True)} |")
        store[name] = dict(grid=grid, valid=sv, trades=tr, nav=nav, chosen=best)
        print(L[-2], L[-1], sep="\n", flush=True)
    (OUT / "PREREG_CLOSE.json").write_text(json.dumps(dict(written="before validation", disc=DISC, valid=VALID, rules=prereg), indent=2, default=str))
    (OUT / "CLOSE.md").write_text("\n".join(L), encoding="utf-8")
    pd.to_pickle(store, OUT / "close.pkl")

if __name__ == "__main__":
    main()
