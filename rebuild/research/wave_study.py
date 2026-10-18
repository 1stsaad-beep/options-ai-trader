"""Wave-2 / wave-B confirmation study.

1. Collect all wave setups (no divergence required) on daily (2013-2026) and
   hourly (2 years) data for 15 symbols, with ~25 candidate confirmations.
2. Feature lift: for each confirmation, mean fwd10 (ATR) and hit-rate with vs.
   without it, separately in period A (selection) and B (test).
3. Build the confirmed wave strategy from features chosen on A ONLY (consistent,
   positive lift), plus a confluence score; test on B: underlying and options.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from oat_research import data as D, wave_lab as W, indicators as ind, backtest as bt, study as S, options_model as om
from oat_research.intraday import WDParams

ETFS = {"SPY", "QQQ", "IWM"}
FEATURES = {  # name -> (column, predicate)
    "div RSI (any)": ("div_rsi", lambda x: x == True),
    "div RSI hidden": ("div_rsi_hidden", lambda x: x == True),
    "div RSI regular": ("div_rsi_regular", lambda x: x == True),
    "div MACD (any)": ("div_macd", lambda x: x == True),
    "div MACD hidden": ("div_macd_hidden", lambda x: x == True),
    "div MACD regular": ("div_macd_regular", lambda x: x == True),
    "div any": ("div_any", lambda x: x == True),
    "W2->3 (structure break)": ("tag", lambda x: x == "W2"),
    "B->C": ("tag", lambda x: x == "B"),
    "golden zone 50-66%": ("golden", lambda x: x == True),
    "shallow retr <50%": ("retr", lambda x: x < 0.5),
    "deep retr >66%": ("retr", lambda x: x > 0.66),
    "RSI at pivot <40 (bull) / >60": ("rsi_pivot", lambda x: x < 40),
    "Stoch at pivot <20 / >80": ("stoch_pivot", lambda x: x < 20),
    "Bollinger band tag at pivot": ("bb_tag", lambda x: x == True),
    "volume dry-up in correction": ("vol_dryup", lambda x: x == True),
    "correction time >= 0.618 leg": ("time_ratio", lambda x: x >= 0.618),
    "trend: beyond SMA200": ("trend200", lambda x: x == True),
    "beyond EMA50": ("above_ema50", lambda x: x == True),
    "EMA20/50 stacked": ("ema_stack", lambda x: x == True),
    "EMA50 sloping with trade": ("ema50_slope", lambda x: x == True),
    "ADX >= 20": ("adx", lambda x: x >= 20),
    "ADX rising": ("adx_rising", lambda x: x == True),
    "MACD hist turning": ("macd_hist_rising", lambda x: x == True),
    "MACD above signal": ("macd_above_signal", lambda x: x == True),
    "MACD line zero side": ("macd_zero_side", lambda x: x == True),
    "holds anchored VWAP(wave start)": ("avwap_hold", lambda x: x == True),
    "trigger volume >= 1.2x": ("trig_relvol", lambda x: x >= 1.2),
    "trigger close strong (CLV>=0.7)": ("trig_clv", lambda x: x >= 0.7),
    "relative strength vs SPY": ("rs", lambda x: x == True),
    "higher timeframe agrees": ("htf", lambda x: x == 1.0),
    "leg1 >= 5 ATR": ("leg1_atr", lambda x: x >= 5),
}


def collect(tf):
    data = {s: df for s, df in D.load_folder(f"data/{tf}").items() if s != "VIX"}
    spy = data["SPY"]
    d1 = {s: df for s, df in D.load_folder("data/d1").items() if s != "VIX"}
    rows = []
    for s, df in data.items():
        htf = None
        if tf == "h1":  # daily close above daily SMA50, known from the previous session
            dd = d1[s]
            up = (dd["close"] > ind.sma(dd["close"], 50)).astype(float).where(ind.sma(dd["close"], 50).notna())
            up = up.shift(1)
            htf = pd.Series(up.reindex(df.index.normalize()).to_numpy(), index=df.index)
        elif tf == "d1":  # weekly: close above 20-week (100-day) average, previous week
            up = (df["close"] > ind.sma(df["close"], 100)).astype(float).where(ind.sma(df["close"], 100).notna())
            htf = up.resample("W-FRI").last().shift(1).reindex(df.index, method="ffill")
        cand = W.candidates(df, WDParams(), spy if s != "SPY" else None, htf)
        cand = W.add_outcomes(cand, df)
        cand["sym"] = s
        rows.append(cand)
    return data, pd.concat(rows, ignore_index=True).dropna(subset=["fwd10"])


def lift_table(c, split):
    A, B = c[c.date < split], c[c.date >= split]
    out = []
    for name, (col, pred) in FEATURES.items():
        r = {"feature": name}
        for lab, part in (("A", A), ("B", B)):
            col_v = part[col]
            mask = col_v.map(lambda x: bool(pred(x)) if pd.notna(x) else False)
            yes, no = part[mask], part[~mask]
            r[f"{lab}_n"] = len(yes)
            r[f"{lab}_fwd_yes"] = yes.fwd10.mean() if len(yes) else np.nan
            r[f"{lab}_fwd_no"] = no.fwd10.mean() if len(no) else np.nan
            r[f"{lab}_hit_yes"] = yes.hit.mean() if len(yes) else np.nan
            r[f"{lab}_lift"] = r[f"{lab}_fwd_yes"] - r[f"{lab}_fwd_no"]
        out.append(r)
    return pd.DataFrame(out).sort_values("A_lift", ascending=False)


def mask_for(c, names):
    m = pd.Series(True, index=c.index)
    for nm in names:
        col, pred = FEATURES[nm]
        m &= c[col].map(lambda x: bool(pred(x)) if pd.notna(x) else False)
    return m


def score(c, names):
    s = pd.Series(0, index=c.index)
    for nm in names:
        s += mask_for(c, [nm]).astype(int)
    return s


if __name__ == "__main__":
    lines = ["# Wave-2 / Wave-B confirmation study", ""]
    cfgs = {
        "d1": (pd.Timestamp(2020, 1, 1), bt.StrategyConfig("wave_d1", bt.ExitRules(option_stop=None, option_target=1.0, trail_arm=0.5,
                                                                                     trail_drop=0.3, time_stop_days=10, min_dte_exit=7),
                                                         dte=45, target_delta=0.65), (0.02, 0.04)),
        "h1": (None, bt.StrategyConfig("wave_h1", bt.ExitRules(option_stop=None, option_target=0.8, trail_arm=0.4, trail_drop=0.25,
                                                               time_stop_days=14, min_dte_exit=3), dte=21, target_delta=0.65), (0.03, 0.05)),
    }
    for tf, (split, cfg, spreads) in cfgs.items():
        data, c = collect(tf)
        if split is None:
            split = c.date.min() + (c.date.max() - c.date.min()) / 2
        A, B = c[c.date < split], c[c.date >= split]
        lines += [f"## {tf}: {len(c)} setups ({(c.dir > 0).sum()} bullish / {(c.dir < 0).sum()} bearish), split {split:%Y-%m-%d}", "",
                  f"All setups: fwd10 A {A.fwd10.mean():+.3f} / B {B.fwd10.mean():+.3f} ATR; hit A {A.hit.mean():.2f} / B {B.hit.mean():.2f}", "",
                  "| confirmation | A n | A fwd with / without | A lift | B n | B fwd with / without | B lift | hit with (A/B) |",
                  "|---|---|---|---|---|---|---|---|"]
        lt = lift_table(c, split)
        for r in lt.itertuples():
            lines.append(f"| {r.feature} | {r.A_n} | {r.A_fwd_yes:+.2f} / {r.A_fwd_no:+.2f} | **{r.A_lift:+.2f}** | {r.B_n} | "
                         f"{r.B_fwd_yes:+.2f} / {r.B_fwd_no:+.2f} | {r.B_lift:+.2f} | {r.A_hit_yes:.2f} / {r.B_hit_yes:.2f} |")
        # --- selection on A only: features with A lift >= 0.10 ATR and >= 15% of setups
        chosen = [r.feature for r in lt.itertuples() if r.A_lift >= 0.10 and r.A_n >= 0.15 * len(A)
                  and r.feature not in ("B->C",)]
        chosen = chosen[:8]
        sA, sB = score(A, chosen), score(B, chosen)
        best_k, best_v = 0, -9
        for k in range(1, len(chosen) + 1):
            sub = A[sA >= k]
            if len(sub) >= max(30, 0.05 * len(A)) and sub.fwd10.mean() > best_v:
                best_k, best_v = k, sub.fwd10.mean()
        lines += ["", f"**Chosen on A** (lift ≥ 0.10 ATR, ≥15% coverage): {', '.join(chosen) or 'none'}",
                  f"Confluence score threshold chosen on A: score ≥ {best_k}", "",
                  "| set | A n | A fwd10 | A hit | B n | B fwd10 | B hit |", "|---|---|---|---|---|---|---|"]
        for lab, mA, mB in (("all setups", A.index == A.index, B.index == B.index),
                            ("divergence any", mask_for(A, ["div any"]), mask_for(B, ["div any"])),
                            (f"confluence ≥ {best_k}", sA >= best_k, sB >= best_k),
                            (f"confluence ≥ {best_k} + divergence", (sA >= best_k) & mask_for(A, ["div any"]),
                             (sB >= best_k) & mask_for(B, ["div any"]))):
            a, b = A[mA], B[mB]
            lines.append(f"| {lab} | {len(a)} | {a.fwd10.mean():+.3f} | {a.hit.mean():.2f} | {len(b)} | {b.fwd10.mean():+.3f} | {b.hit.mean():.2f} |")
        # --- options backtest of the confluence strategy
        base = om.OptionCosts(spread_pct=spreads[1]); ov = {s: om.OptionCosts(spread_pct=spreads[0]) for s in data if s in ETFS}
        full_score = score(c, chosen)
        lines += ["", "| options backtest | trades | win | avg win | avg loss | exp/trade | PF | t | A exp | B exp |", "|---|---|---|---|---|---|---|---|---|---|"]
        for lab, msk in (("all setups", full_score >= 0), ("divergence any", mask_for(c, ["div any"])),
                         (f"confluence ≥ {best_k}", full_score >= best_k),
                         (f"confluence ≥ {best_k} + divergence", (full_score >= best_k) & mask_for(c, ["div any"]))):
            sel = c[msk]
            sigs = {s: W.to_signals(df, sel[sel.sym == s]) for s, df in data.items()}
            tr, _ = bt.run(data, sigs, cfg, base, cost_overrides=ov)
            st = S.trade_stats(tr)
            a = S.trade_stats([t for t in tr if t.entry_date < split]); b = S.trade_stats([t for t in tr if t.entry_date >= split])
            lines.append(f"| {lab} | {st['trades']} | {st.get('win_rate', 0):.2f} | {st.get('avg_win', 0):+.1%} | {st.get('avg_loss', 0):+.1%} | "
                         f"{st.get('expectancy', 0):+.1%} | {st.get('profit_factor', 0):.2f} | {st.get('t_stat', 0):+.2f} | "
                         f"{a.get('expectancy', 0):+.1%} | {b.get('expectancy', 0):+.1%} |")
        lines.append("")
        c.to_pickle(f"results/wave_{tf}.pkl")
        print(tf, "done", flush=True)
    Path("results/wave").mkdir(parents=True, exist_ok=True)
    Path("results/wave/RESULTS_WAVE.md").write_text("\n".join(lines), encoding="utf-8")
    print("wrote results/wave/RESULTS_WAVE.md")
