"""Round 10 — what precedes a big 2-day move?  (user idea, studied as a conditional-probability problem)

Event (for Calls): close(t+2)/close(t) - 1 >= +5 %   [and a volatility-scaled version: >= +2 x ATR14(t)]
Event (for Puts) : <= -5 %                            [<= -2 x ATR14(t)]
Features: indicator state at the close of day t (causal). For each feature / combination we measure
LIFT = P(event | feature) / P(event) and the mean 2-day return, on
  DISCOVERY  original 15 symbols, 1999-2015      (search happens ONLY here)
  VALIDATION original 15 symbols, 2016-2026
  NEW        30 symbols never used before, 1999-2026 (pure out-of-sample)
python r10_bigmove.py -> results/r10/*.md, results/r10/panel.pkl
"""
import itertools, json
from pathlib import Path
import numpy as np, pandas as pd
from oat_research import data as D, elliott_mtf as EW, indicators as ind
from r4_common import load_daily
from r7_lib import ORIG, NEW

OUT = Path("results/r10"); OUT.mkdir(parents=True, exist_ok=True)
DISC_END = pd.Timestamp("2015-12-31")


def features(df, spy, vix):
    c, o, h, l, v = df["close"], df["open"], df["high"], df["low"], df["volume"]
    a = ind.atr(df)
    e = {n: ind.ema(c, n) for n in (9, 20, 50)}
    s = {n: ind.sma(c, n) for n in (20, 50, 100, 200)}
    m_line = ind.ema(c, 12) - ind.ema(c, 26); m_sig = ind.ema(m_line, 9); hist = m_line - m_sig
    r14, r2 = ind.rsi(c, 14), ind.rsi(c, 2)
    adx = ind.adx(df)
    k = ind.stoch_k(df)
    bbw = ind.bb_width(c, 20); bbp = ind.rolling_percentile(bbw, 126)
    mid = s[20]; sd = c.rolling(20).std(ddof=0)
    vr = v / ind.sma(v, 20).shift(1)
    clv = (c - l) / (h - l).replace(0, np.nan)
    hh252 = h.rolling(252).max(); ll252 = l.rolling(252).min()
    ret = lambda n: c / c.shift(n) - 1
    sp = spy["close"].reindex(df.index).ffill()
    vx = vix.reindex(df.index).ffill()
    obv = ind.obv(df)
    atrp = a / c
    rng_pct = ind.rolling_percentile(atrp, 252)
    nr7 = (h - l) == (h - l).rolling(7).min()
    inside = (h < h.shift(1)) & (l > l.shift(1))
    w = EW.label_series(df, k_atr=2.0)
    F = {
        # MACD
        "MACD hist > 0": hist > 0, "MACD hist rising": hist > hist.shift(1), "MACD line > 0": m_line > 0,
        "MACD bull cross (3d)": ((m_line > m_sig) & (m_line.shift(1) <= m_sig.shift(1))).rolling(3).max().astype(bool),
        "MACD hist < 0 & rising": (hist < 0) & (hist > hist.shift(1)),
        # moving averages
        "close > SMA20": c > s[20], "close > SMA50": c > s[50], "close > SMA200": c > s[200],
        "SMA50 > SMA200": s[50] > s[200], "EMA9 > EMA20 > EMA50": (e[9] > e[20]) & (e[20] > e[50]),
        "SMA50 rising": s[50] > s[50].shift(10), "SMA200 rising": s[200] > s[200].shift(20),
        "close crossed above SMA50 (3d)": ((c > s[50]) & (c.shift(1) <= s[50].shift(1))).rolling(3).max().astype(bool),
        "close < SMA200": c < s[200], "close > 1.5 ATR above SMA20": (c - s[20]) / a > 1.5, "close < SMA20 - 1.5 ATR": (s[20] - c) / a > 1.5,
        # oscillators
        "RSI14 > 70": r14 > 70, "RSI14 50-70": (r14 > 50) & (r14 <= 70), "RSI14 < 30": r14 < 30, "RSI2 < 10": r2 < 10, "RSI2 > 90": r2 > 90,
        "Stoch %K < 20": k < 20, "Stoch %K > 80": k > 80,
        # trend strength / volatility
        "ADX > 25": adx > 25, "ADX < 15": adx < 15, "BB squeeze (width pct < 20%)": bbp < 0.2, "BB width pct > 80%": bbp > 0.8,
        "close > upper BB": c > mid + 2 * sd, "close < lower BB": c < mid - 2 * sd,
        "ATR% top 20% of year": rng_pct > 0.8, "ATR% bottom 20% of year": rng_pct < 0.2, "NR7": nr7, "inside day": inside,
        # volume / candle
        "volume > 2x avg": vr > 2, "volume > 1.5x avg": vr > 1.5, "volume < 0.7x avg": vr < 0.7,
        "close in top 20% of range": clv > 0.8, "close in bottom 20% of range": clv < 0.2,
        "up day > 2 ATR%": (c / c.shift(1) - 1) > 2 * atrp.shift(1), "down day > 2 ATR%": (c / c.shift(1) - 1) < -2 * atrp.shift(1),
        "OBV at 20-day high": obv >= obv.rolling(20).max(),
        # price location / momentum
        "within 3% of 52w high": c >= 0.97 * hh252, "new 52w high": c >= hh252, "within 10% of 52w low": c <= 1.10 * ll252,
        "5d return > +5%": ret(5) > 0.05, "5d return < -5%": ret(5) < -0.05, "20d return > +10%": ret(20) > 0.10, "20d return < -10%": ret(20) < -0.10,
        "60d return > SPY 60d": ret(60) > (sp / sp.shift(60) - 1),
        # market
        "SPY > SMA200": sp > ind.sma(sp, 200), "SPY 5d return < -3%": (sp / sp.shift(5) - 1) < -0.03, "VIX > 25": vx > 25, "VIX < 15": vx < 15,
        "VIX up > 15% today": vx / vx.shift(1) - 1 > 0.15,
        # Elliott (daily count)
        "Elliott: up count, wave 3": (w.wdir == 1) & (w.wave == "3"), "Elliott: up count, wave 5": (w.wdir == 1) & (w.wave == "5"),
        "Elliott: up count, wave 2": (w.wdir == 1) & (w.wave == "2"), "Elliott: up count, wave 4": (w.wdir == 1) & (w.wave == "4"),
        "Elliott: up count, wave C": (w.wdir == 1) & (w.wave == "C"), "Elliott: down count, wave 3": (w.wdir == -1) & (w.wave == "3"),
        "Elliott: down count, wave 5": (w.wdir == -1) & (w.wave == "5"), "Elliott: down count, wave 2/4/B": (w.wdir == -1) & w.wave.isin(["2", "4", "B"]),
        # calendar
        "Monday": pd.Series(df.index.weekday == 0, index=df.index), "Friday": pd.Series(df.index.weekday == 4, index=df.index),
    }
    X = pd.DataFrame({k_: v_.fillna(False).astype(bool) for k_, v_ in F.items()}, index=df.index)
    fwd = c.shift(-2) / c - 1
    X["_fwd2"] = fwd
    X["_atrp"] = atrp
    # 'earnings-like' marker for the move itself: a gap >= 1.5 ATR on >= 2.5x volume on day t+1 or t+2
    gap = (o / c.shift(1) - 1).abs() / atrp.shift(1)
    ev = (gap >= 1.5) & (vr >= 2.5)
    X["_earnlike"] = (ev.shift(-1) | ev.shift(-2)).fillna(False)
    return X


def build_panel():
    d1, vols = load_daily()
    spy, vix = d1["SPY"], vols["VIX"]
    rows = []
    for s in ORIG + NEW:
        df = d1[s] if s in d1 else D.load_csv(f"data/d1x/{s}.csv")
        X = features(df, spy, vix)
        X["_sym"], X["_set"] = s, ("orig" if s in ORIG else "new")
        X = X.iloc[252:-2]                                        # one-year warm-up for every symbol; last 2 days have no outcome
        X = X[X.index >= pd.Timestamp("1999-01-01")]
        rows.append(X.dropna(subset=["_fwd2", "_atrp"]))
        print(s, len(X), flush=True)
    P = pd.concat(rows)
    P.to_pickle(OUT / "panel.pkl")
    return P


def part(P, name):
    if name == "DISC":
        return P[(P._set == "orig") & (P.index <= DISC_END)]
    if name == "VALID":
        return P[(P._set == "orig") & (P.index > DISC_END)]
    return P[P._set == "new"]


def main():
    P = build_panel()
    feats = [c for c in P.columns if not c.startswith("_")]
    res = {}
    L = ["# What precedes a big 2-day move? (backtested, daily data)", ""]
    for side, sign in (("UP", 1), ("DOWN", -1)):
        for kind in ("5%", "2ATR"):
            ev = (sign * P._fwd2 >= 0.05) if kind == "5%" else (sign * P._fwd2 >= 2 * P._atrp)
            P["_ev"] = ev
            L += [f"## {side} ≥ {kind} in 2 days", ""]
            base = {n: part(P, n)._ev.mean() for n in ("DISC", "VALID", "NEW")}
            el = P[P._ev]._earnlike.mean()
            L.append(f"Base rate: discovery {base['DISC']*100:.2f} %, validation {base['VALID']*100:.2f} %, new symbols {base['NEW']*100:.2f} %. "
                     f"Share of these moves that came with an earnings-like gap (≥1.5 ATR on ≥2.5× volume): {el*100:.0f} %.")
            L += ["", "**Single indicators — lift = P(event | indicator) / P(event)** (sorted by discovery lift; indicators true on ≥ 1 % of days)", "",
                  "| indicator | days (disc.) | lift DISC | lift VALID | lift NEW | mean 2d return DISC / VALID / NEW |", "|---|---|---|---|---|---|"]
            single = []
            for f in feats:
                vals = {}
                for n in ("DISC", "VALID", "NEW"):
                    X = part(P, n); m = X[f]
                    vals[n] = (X[m]._ev.mean() / base[n] if m.sum() else np.nan, int(m.sum()), sign * X[m]._fwd2.mean() if m.sum() else np.nan)
                if vals["DISC"][1] < 0.01 * len(part(P, "DISC")):
                    continue
                single.append((vals["DISC"][0], f, vals))
            for lift, f, vals in sorted(single, reverse=True, key=lambda x: (np.nan_to_num(x[0], nan=-1))):
                L.append(f"| {f} | {vals['DISC'][1]} | **{vals['DISC'][0]:.2f}** | {vals['VALID'][0]:.2f} | {vals['NEW'][0]:.2f} | "
                         f"{vals['DISC'][2]*100:+.2f}% / {vals['VALID'][2]*100:+.2f}% / {vals['NEW'][2]*100:+.2f}% |")
            # combinations (searched on discovery only): pairs and triples of indicators with discovery lift > 1.1
            Xd = part(P, "DISC")
            cand = [f for l_, f, v in single if np.isfinite(l_) and l_ > 1.1]
            Md = {f: Xd[f].to_numpy() for f in cand}
            evd = Xd._ev.to_numpy(); nmin = max(200, int(0.003 * len(Xd)))
            h1 = (Xd.index <= pd.Timestamp("2007-12-31"))
            combos = []
            for r_ in (2, 3):
                for cmb in itertools.combinations(cand, r_):
                    m = np.logical_and.reduce([Md[f] for f in cmb])
                    n_ = m.sum()
                    if n_ < nmin:
                        continue
                    lift = evd[m].mean() / base["DISC"]
                    # stability inside discovery: both halves must show lift > 1.2
                    l1 = evd[m & h1].mean() / evd[h1].mean() if (m & h1).sum() > 30 else 0
                    l2 = evd[m & ~h1].mean() / evd[~h1].mean() if (m & ~h1).sum() > 30 else 0
                    if l1 > 1.2 and l2 > 1.2:
                        combos.append((lift, cmb, int(n_)))
            combos.sort(reverse=True)
            top = combos[:10]
            L += ["", f"**Best combinations found on DISCOVERY (stable in both halves 1999–2007 / 2008–2015), then checked out of sample** — {len(combos)} stable combos found", "",
                  "| combination | days DISC | lift DISC | lift VALID | lift NEW | P(event) VALID / NEW | mean 2d return DISC / VALID / NEW |", "|---|---|---|---|---|---|---|"]
            out = []
            for lift, cmb, n_ in top:
                vv = {}
                for n in ("DISC", "VALID", "NEW"):
                    X = part(P, n); m = np.logical_and.reduce([X[f].to_numpy() for f in cmb])
                    vv[n] = (X._ev.to_numpy()[m].mean() / base[n] if m.sum() else np.nan, X._ev.to_numpy()[m].mean() if m.sum() else np.nan,
                             sign * X._fwd2.to_numpy()[m].mean() if m.sum() else np.nan, int(m.sum()))
                L.append(f"| {' + '.join(cmb)} | {n_} | **{lift:.2f}** | {vv['VALID'][0]:.2f} | {vv['NEW'][0]:.2f} | "
                         f"{vv['VALID'][1]*100:.1f}% / {vv['NEW'][1]*100:.1f}% | {vv['DISC'][2]*100:+.2f}% / {vv['VALID'][2]*100:+.2f}% / {vv['NEW'][2]*100:+.2f}% |")
                out.append(dict(combo=cmb, disc_lift=lift, valid=vv["VALID"], new=vv["NEW"]))
            res[(side, kind)] = out
            L.append("")
    (OUT / "BIGMOVE.md").write_text("\n".join(L), encoding="utf-8")
    json.dump({f"{k[0]} {k[1]}": v for k, v in res.items()}, open(OUT / "combos.json", "w"), indent=1, default=str)
    print("\n".join(L[:60]))


if __name__ == "__main__":
    main()
