"""Round 9 — same signals, better instruments, REAL option prices (2024-02 -> 2026-10).

Signals (chosen because the UNDERLYING moved the right way in more than one period):
  short horizon : SQZ  squeeze-breakout daily @15:50          (round 6 rule)
                  TDL  trend-dip @15:50, LEADERS only          (round 4 rule + pre-declared leader filter)
                  FOMC pre-FOMC 15:50 -> 13:55 (SPY/QQQ/IWM)   (round 4 rule)
  long horizon  : S1   12-month momentum, month-end, hold 21 sessions        (round 1 rule)
                  S3   first close above the 52-week high, not extended (<3 ATR over SMA50),
                       2-ATR stop, exit after 20 sessions                      (round 2 rule)
Instruments for every trade (same entry/exit times):
  STOCK  the underlying itself (baseline, return on notional)
  CALL   weekly single call, delta 0.5 (the instrument used so far)
  SPREAD weekly call debit spread: long = the CALL contract, short = listed strike ~ +1 x ATR above
  LONG   third-Friday monthly expiry 45-90 days out, delta ~0.75
Universes: ORIGINAL 15 and NEW 30 (never used before round 7), reported separately.
Pre-registered acceptance (results/r9/PREREG.json, written before the run).
python r9_run.py
"""
import json
from pathlib import Path
import numpy as np, pandas as pd
import r4_real_options as R
import r7_lib as L7
from oat_research import indicators as ind, intraday4 as I4, options_model as om, setups4 as S4, shortdated as SD, strat6 as S6
from r4_common import costs, fmt
from r5_options import implied_vol

OUT = Path("results/r9"); OUT.mkdir(parents=True, exist_ok=True)
REAL, DEV_END = L7.REAL, L7.DEV_END
ETFS = {"SPY", "QQQ", "IWM"}
COMM = 0.0065   # $0.65 per contract per side, per share

PREREG = dict(
    written="before the first run of r9_run.py",
    signals=["SQZ", "TDL", "FOMC", "S1", "S3"], instruments=["STOCK", "CALL", "SPREAD", "LONG"],
    fills="5-min option-bar VWAP at entry/exit; each leg pays a half-spread (ETF 1.5%, stock 3%) + $0.65/contract/side",
    accept=("a signal x instrument pair is a Paper candidate only if REAL mean return > 0 on the ORIGINAL and on the NEW universe "
            "(FOMC: original only), pooled t > 1.0, > 0 in both 2024-02..2025-06 and 2025-07..2026-10, and still > 0 with 2x half-spreads"),
)


# ---------------------------------------------------------------- signals
def sig_tdl(U, spy_close):
    bars, sigs, bm = L7.sig_trend_dip(U)
    for s in U.syms:
        c = U.full[s]["close"]
        sp = spy_close.reindex(c.index).ffill()
        lead = (c > ind.sma(c, 200)) & (c / c.shift(126) > sp / sp.shift(126))
        lv = S6._prev_daily(lead, sigs[s])
        sigs[s].loc[~(lv == True), "dir"] = 0
    return bars, sigs


def sig_fomc(U):
    fomc = S4.load_fomc()
    out = {}
    for s in [x for x in U.syms if x in ETFS]:
        sg = U.seg[s]; idx = sg.index; day = idx.normalize()
        days = pd.DatetimeIndex(sorted(set(day))); pos = {d: i for i, d in enumerate(days)}
        pre = {days[pos[f] - 1] for f in fomc if f in pos and pos[f] >= 1}
        hm = idx.hour * 60 + idx.minute
        sig = day.isin(list(pre)) & (hm == 13 * 60 + 55)
        ex = day.isin(list(fomc)) & (hm == 12 * 60)
        out[s] = S4.frame(sg, np.where(sig, 1, 0), reason=np.where(sig, "pre-FOMC", ""), min_days=2, xsched=ex)
    return {s: U.seg[s] for s in out}, out


def month_end_flags(index, cal):
    cal = pd.DatetimeIndex(cal)
    nxt = pd.Series(cal[1:].append(cal[-1:] + pd.Timedelta(days=1)), index=cal)
    last = pd.Series(nxt.dt.month.to_numpy() != cal.month, index=cal)
    return last.reindex(index).fillna(False).to_numpy()


def sig_s1(U, cal):
    out = {}
    for s in U.syms:
        a = U.asof[s]; c = a["close"]
        last = month_end_flags(a.index, cal)
        up = last & (c / c.shift(252) - 1 > 0).to_numpy() & (c > ind.sma(c, 200)).to_numpy()
        out[s] = I4.to_segments(S4.frame(a, np.where(up, 1, 0), reason=np.where(up, "S1 12m momentum", "")), U.seg[s])
    return {s: U.seg[s] for s in out}, out


def sig_s3(U):
    out = {}
    for s in U.syms:
        a = U.asof[s]; c, h = a["close"], a["high"]
        hh = h.rolling(252).max().shift(1)
        first = (c > hh) & ~((c.shift(1) > hh.shift(1)).rolling(20).max().fillna(0).astype(bool))
        atr = ind.atr(U.full[s]).shift(1).reindex(a.index)
        notext = (c - ind.sma(c, 50)) / atr < 3
        up = (first & notext).to_numpy()
        out[s] = I4.to_segments(S4.frame(a, np.where(up, 1, 0), reason=np.where(up, "S3 52-week high", "")), U.seg[s])
    return {s: U.seg[s] for s in out}, out


def schedule(U, bars, sigs, ex, md=2):
    tgt, stp, hold = ex
    c = SD.SDConfig("r9", SD.SDExit(target_atr=tgt, stop_atr=stp, use_signal_levels=False, max_hold_bars=hold),
                    target_delta=0.5, min_days=md, budget=0.0001, max_open=200, bar_minutes=0, iv_term=SD.calibrated_term)
    # timing only: a huge notional so that every signal gets a position (one per symbol still applies)
    tr, _ = SD.run(bars, sigs, c, U.full, U.ivs, costs(U.full), *REAL, initial=1e9)
    return tr


# ---------------------------------------------------------------- pricing helpers
def px(sym, t, before=False):
    """VWAP of the first traded 5-min bar at/after t (or last before t for closing exits); NaN if none."""
    b = R.option_bars([sym], t - pd.Timedelta(minutes=20), t + pd.Timedelta(minutes=20))
    if sym not in b:
        return np.nan
    return R.fill(b[sym], t, before=before)


def third_friday(y, m):
    d = pd.Timestamp(y, m, 15)
    while d.weekday() != 4:
        d += pd.Timedelta(days=1)
    return d


def long_expiry(entry):
    cands = []
    for k in range(1, 5):
        mth = (entry + pd.DateOffset(months=k))
        tf = third_friday(mth.year, mth.month)
        dd = (tf - entry.normalize()).days
        if 45 <= dd <= 90:
            cands.append((abs(dd - 60), tf))
    return min(cands)[1] if cands else None


def strikes_near(k, spot):
    out = []
    for inc in (1.0, 2.5, 5.0, 10.0, 0.5):
        v = round(k / inc) * inc
        if v > 0 and v not in out:
            out.append(v)
    return out


def ret(e_long, x_long, hs, e_short=None, x_short=None):
    if e_short is None:
        debit = e_long * (1 + hs) + COMM
        proceeds = x_long * (1 - hs) - COMM
    else:
        debit = e_long * (1 + hs) - e_short * (1 - hs) + 2 * COMM
        proceeds = x_long * (1 - hs) - x_short * (1 + hs) - 2 * COMM
    if debit <= 0:
        return np.nan
    return (proceeds - debit) / debit


def price_trades(U, tr, rows_call):
    """rows_call: L7.replay_path output for the weekly CALL (same trades, same order where matched)."""
    by_t = {(r["t"].symbol, r["t"].entry_time): r for r in rows_call}
    out = []
    for t in tr:
        f = U.factor[t.symbol]; day = t.entry_time.normalize()
        if day not in f.index:
            continue
        fx = float(f.loc[day]); spot = t.entry_spot * fx
        hs = 0.015 if t.symbol in ETFS else 0.03
        at_close = t.exit_time.hour == 16 and t.exit_time.minute == 0
        rec = dict(sym=t.symbol, entry=t.entry_time, exit=t.exit_time, stock=t.direction * (t.exit_spot / t.entry_spot - 1),
                   call=np.nan, spread=np.nan, long=np.nan, call_2x=np.nan, spread_2x=np.nan, long_2x=np.nan)
        # weekly CALL + SPREAD
        r = by_t.get((t.symbol, t.entry_time))
        if r is not None and r["ok"]:
            rec["call"], rec["call_2x"] = ret(r["e"], r["x"], hs), ret(r["e"], r["x"], 2 * hs)
            a = ind.atr(U.full[t.symbol]).shift(1); a.index = a.index.normalize()
            atr_raw = float(a.get(day, np.nan)) * fx
            exp = r["contract"][len(t.symbol):len(t.symbol) + 6]
            ed = pd.Timestamp("20" + exp[:2] + "-" + exp[2:4] + "-" + exp[4:6])
            for k2 in strikes_near(r["k"] + atr_raw, spot):
                if k2 <= r["k"]:
                    continue
                s2 = R.occ(t.symbol, ed, True, k2)
                e2 = px(s2, t.entry_time)
                if not np.isfinite(e2):
                    continue
                x2 = px(s2, t.exit_time, before=at_close)
                if not np.isfinite(x2) and t.exit_time >= t.expiry - pd.Timedelta(minutes=1):
                    x2 = max(0.0, t.exit_spot * fx - k2)
                if np.isfinite(x2):
                    rec["spread"], rec["spread_2x"] = ret(r["e"], r["x"], hs, e2, x2), ret(r["e"], r["x"], 2 * hs, e2, x2)
                    rec["width_atr"] = (k2 - r["k"]) / atr_raw
                break
        # LONG-dated, delta ~0.75
        le = long_expiry(t.entry_time)
        if le is not None:
            iv = float(U.ivs[t.symbol].shift(1).reindex([day], method="ffill").iloc[0]) if day in U.ivs[t.symbol].index else np.nan
            if not np.isfinite(iv):
                sr = U.ivs[t.symbol]; sr2 = sr[sr.index < day]; iv = float(sr2.iloc[-1]) if len(sr2) else np.nan
            if np.isfinite(iv):
                iv *= 1.13
                dl = (le + pd.Timedelta(hours=16) - t.entry_time).total_seconds() / 86400
                c_ = om.OptionCosts()
                kstar = om.choose_strike(True, spot, dl, iv, 0.75, c_)
                for k in sorted(strikes_near(kstar, spot), key=lambda v: abs(v - kstar)):
                    s3 = R.occ(t.symbol, le, True, k)
                    e3 = px(s3, t.entry_time)
                    if not np.isfinite(e3):
                        continue
                    x3 = px(s3, t.exit_time, before=at_close)
                    if np.isfinite(x3):
                        rec["long"], rec["long_2x"] = ret(e3, x3, hs), ret(e3, x3, 2 * hs)
                        rec["long_k"] = k
                    break
        out.append(rec)
    R.CACHE.write_text(json.dumps(R.cache))
    return pd.DataFrame(out)


def st(x):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 3:
        return dict(n=len(x))
    w, l = x[x > 0], x[x <= 0]
    return dict(n=len(x), win=(x > 0).mean(), exp=x.mean(), pf=w.sum() / -l.sum() if l.sum() < 0 else np.inf,
                t=x.mean() / x.std(ddof=1) * np.sqrt(len(x)))


def cell(s):
    return "—" if s["n"] < 3 else f"{fmt(s['exp'], True)} (n {s['n']}, t {s['t']:.2f}, win {s['win']*100:.0f}%)"


def main():
    (OUT / "PREREG.json").write_text(json.dumps(PREREG, indent=2))
    spy_close = L7.Universe("orig").full["SPY"]["close"]
    cal = S4.trading_calendar(spy_close.index)
    plan = {
        "SQZ": dict(make=lambda U: L7.sig_squeeze_daily(U)[:2], ex=(1.0, 0.5, 30)),
        "TDL": dict(make=lambda U: sig_tdl(U, spy_close), ex=(0.75, 1.0, None)),
        "FOMC": dict(make=sig_fomc, ex=(None, None, None)),
        "S1": dict(make=lambda U: sig_s1(U, cal), ex=(None, None, 105)),
        "S3": dict(make=sig_s3, ex=(None, 2.0, 100)),
    }
    store = {}
    L = ["# Round 9 — same signals, four instruments, REAL option prices 2024-02 → 2026-10 (backtested)", "",
         "Return per trade: STOCK on notional; CALL/LONG on premium; SPREAD on net debit. Each leg pays a half-spread (ETF 1.5 %, stock 3 %) + $0.65/contract/side.", ""]
    for uname in ("orig", "new"):
        U = L7.Universe(uname)
        for sname, p in plan.items():
            if sname == "FOMC" and uname == "new":
                continue
            bars, sigs = p["make"](U)
            if not sigs:
                continue
            md = 60 if sname in ("S1", "S3") else 2      # long-horizon schedules must not be cut by a weekly expiry
            tr = schedule(U, {s: bars[s] for s in sigs}, sigs, p["ex"], md)
            rows = L7.replay_path(tr, U.factor) if sname in ("SQZ", "TDL", "FOMC") else []
            df = price_trades(U, tr, rows)
            store[(uname, sname)] = df
            print(uname, sname, len(df), flush=True)
            pd.to_pickle(store, OUT / "store.pkl")
    # ---------------- tables
    for sname in plan:
        L += [f"## {sname}", "", "| universe | period | STOCK | CALL (weekly) | SPREAD (weekly) | LONG (45–90 d, Δ0.75) |", "|---|---|---|---|---|---|"]
        for uname in ("orig", "new"):
            df = store.get((uname, sname))
            if df is None or df.empty:
                continue
            for pn, m in (("all", df.entry > pd.Timestamp("2000-01-01")), ("2024-02→2025-06", df.entry <= DEV_END), ("2025-07→2026-10", df.entry > DEV_END)):
                d = df[m]
                L.append(f"| {uname} | {pn} | {cell(st(d.stock))} | {cell(st(d.call))} | {cell(st(d.spread))} | {cell(st(d.long))} |")
            L.append(f"| {uname} | 2× half-spread | | {cell(st(df.call_2x))} | {cell(st(df.spread_2x))} | {cell(st(df.long_2x))} |")
        L.append("")
    # ---------------- acceptance
    L += ["## Pre-registered acceptance check", "", "| signal | instrument | orig > 0 | new > 0 | pooled t > 1 | both halves > 0 | 2× spreads > 0 | **verdict** |", "|---|---|---|---|---|---|---|---|"]
    for sname in plan:
        for ins in ("call", "spread", "long"):
            o = store.get(("orig", sname)); n = store.get(("new", sname))
            if o is None:
                continue
            pool = pd.concat([x for x in (o, n) if x is not None])
            so, sn, sp = st(o[ins]), (st(n[ins]) if n is not None else dict(n=0)), st(pool[ins])
            h1, h2 = st(pool[pool.entry <= DEV_END][ins]), st(pool[pool.entry > DEV_END][ins])
            s2 = st(pool[ins + "_2x"])
            need_new = sname != "FOMC"
            c1 = so["n"] >= 3 and so["exp"] > 0
            c2 = (not need_new) or (sn["n"] >= 3 and sn["exp"] > 0)
            c3 = sp["n"] >= 3 and sp["t"] > 1
            c4 = h1["n"] >= 3 and h2["n"] >= 3 and h1["exp"] > 0 and h2["exp"] > 0
            c5 = s2["n"] >= 3 and s2["exp"] > 0
            ok = all((c1, c2, c3, c4, c5))
            yn = lambda b: "✅" if b else "❌"
            L.append(f"| {sname} | {ins.upper()} | {yn(c1)} | {yn(c2) if need_new else 'n/a'} | {yn(c3)} | {yn(c4)} | {yn(c5)} | **{'Paper candidate' if ok else 'reject'}** |")
    (OUT / "RESULTS.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
