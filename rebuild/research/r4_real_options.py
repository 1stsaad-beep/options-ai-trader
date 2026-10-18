"""Round 4: replay the model trades on REAL traded option prices (Alpaca/OPRA-derived
option bars exist from Feb 2024). For every simulated trade since 2024-02-05:
  * convert the (split/dividend-adjusted) underlying to the raw price of that day,
  * build the real OCC contract with the same expiry and the listed strike nearest to the
    model's strike (tries $1 / $2.5 / $5 / $10 grids),
  * fill at the 5-minute bar VWAP of the entry / exit bar (first traded bar within 15 min),
    then charge a half-spread on both sides (ETF 1.5%, stock 3% of price) + $0.65/contract.
Same trades, same timestamps: only the option price source changes.

python r4_real_options.py -> results/r4/REAL_OPTIONS.md, results/r4/real_options.pkl
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

from fetch_alpaca import keys
from r4_common import ETFS, OUT, fmt
from r4_final import RULES, build, run

START = pd.Timestamp("2024-02-05")
END = pd.Timestamp("2026-10-16 23:59")
KID, SEC = keys()
CACHE = OUT / "opt_cache.json"
cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}


def get(url):
    if url in cache:
        return cache[url]
    req = urllib.request.Request(url, headers={"APCA-API-KEY-ID": KID, "APCA-API-SECRET-KEY": SEC})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.load(r)
            break
        except Exception:
            time.sleep(2 + 5 * attempt)
    else:
        d = {}
    time.sleep(0.31)
    cache[url] = d
    return d


def stock_daily(sym, adj):
    q = dict(timeframe="1Day", start="2024-01-01T00:00:00Z", end="2026-10-17T00:00:00Z", limit=10000, adjustment=adj, feed="sip")
    d = get(f"https://data.alpaca.markets/v2/stocks/{sym}/bars?" + urllib.parse.urlencode(q))
    s = pd.Series({pd.Timestamp(b["t"]).tz_convert("America/New_York").normalize().tz_localize(None): b["c"] for b in d.get("bars") or []})
    return s


def occ(sym, expiry, is_call, k):
    return f"{sym}{expiry:%y%m%d}{'C' if is_call else 'P'}{int(round(k * 1000)):08d}"


def option_bars(symbols, t0, t1):
    q = dict(symbols=",".join(symbols), timeframe="5Min", start=t0.tz_localize("America/New_York").tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
             end=t1.tz_localize("America/New_York").tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"), limit=10000)
    out, token = {}, None
    while True:
        qq = dict(q, **({"page_token": token} if token else {}))
        d = get("https://data.alpaca.markets/v1beta1/options/bars?" + urllib.parse.urlencode(qq))
        for s, bars in (d.get("bars") or {}).items():
            out.setdefault(s, []).extend(bars)
        token = d.get("next_page_token")
        if not token:
            break
    res = {}
    for s, bars in out.items():
        df = pd.DataFrame(bars)
        df.index = pd.to_datetime(df["t"]).dt.tz_convert("America/New_York").dt.tz_localize(None)
        res[s] = df
    return res


def fill(df, t, before=False):
    """VWAP of the first bar starting at/after t (within 15 min); for exits at the close use
    the last bar starting before t."""
    if before:
        sub = df[(df.index < t) & (df.index >= t - pd.Timedelta(minutes=15))]
        return float(sub["vw"].iloc[-1]) if len(sub) else np.nan
    sub = df[(df.index >= t) & (df.index < t + pd.Timedelta(minutes=15))]
    return float(sub["vw"].iloc[0]) if len(sub) else np.nan


def replay(tr, factor):
    rows = []
    for t in tr:
        f = factor[t.symbol]
        day = t.entry_time.normalize()
        fx = f.reindex([day]).iloc[0] if day in f.index else np.nan
        if not np.isfinite(fx):
            continue
        raw_spot = t.entry_spot * fx
        k_model = t.strike / (max(1.0, 100.0 / t.entry_spot))  # undo the engine's price scaling
        k_raw = k_model * fx
        cands = []
        for inc in (1.0, 2.5, 5.0, 10.0, 0.5):
            k = round(k_raw / inc) * inc
            if k > 0 and k not in cands:
                cands.append(k)
        exp_days = [t.expiry.normalize(), t.expiry.normalize() - pd.Timedelta(days=1)]  # holiday Fridays -> Thursday
        got = None
        for ed in exp_days:
            syms = [occ(t.symbol, ed, t.direction > 0, k) for k in cands]
            bars = option_bars(syms, t.entry_time - pd.Timedelta(minutes=5), t.exit_time + pd.Timedelta(minutes=5))
            best = None
            for k, s in zip(cands, syms):
                if s in bars:
                    e = fill(bars[s], t.entry_time)
                    if np.isfinite(e):
                        if best is None or abs(k - k_raw) < abs(best[0] - k_raw):
                            best = (k, s, e, bars[s])
            if best:
                got = best
                break
        if not got:
            rows.append(dict(sym=t.symbol, entry=t.entry_time, model=t.net_ret, real=np.nan, status="no contract/trade"))
            continue
        k, s, e, b = got
        at_close = t.exit_time.hour == 16 and t.exit_time.minute == 0
        x = fill(b, t.exit_time, before=at_close)
        if not np.isfinite(x):
            later = b[b.index >= t.exit_time]
            x = float(later["vw"].iloc[0]) if len(later) else np.nan
        if not np.isfinite(x) and t.exit_time >= t.expiry - pd.Timedelta(minutes=1):
            x = max(0.0, (t.exit_spot * fx - k) * (1 if t.direction > 0 else -1))
        if not np.isfinite(x):
            rows.append(dict(sym=t.symbol, entry=t.entry_time, model=t.net_ret, real=np.nan, status="no exit print"))
            continue
        hs = 0.015 if t.symbol in ETFS else 0.03
        buy, sell = e * (1 + hs), x * (1 - hs)
        real = (100 * sell - 0.65 - (100 * buy + 0.65)) / (100 * buy + 0.65)
        real_mid = (100 * x - 100 * e - 1.3) / (100 * e + 0.65)
        rows.append(dict(sym=t.symbol, entry=t.entry_time, exit=t.exit_time, contract=s, k_raw=k_raw, k=k, model=t.net_ret,
                         real=real, real_vwap=real_mid, model_px=t.entry_px / max(1.0, 100.0 / t.entry_spot) * fx, real_px=e,
                         raw_spot=raw_spot, is_call=t.direction > 0, days_left=(t.expiry - t.entry_time).total_seconds() / 86400,
                         real_exit_px=x, hours=t.hours_held, status="ok"))
    return pd.DataFrame(rows)


def main():
    B = build()
    factor = {}
    for s in B["sigs"]["A Trend-dip @15:50"]:
        raw, adj = stock_daily(s, "raw"), stock_daily(s, "all")
        factor[s] = (raw / adj).dropna()
    L = ["# Round 4 — model trades replayed on real option prices (2024-02-05 → 2026-10-16)", "",
         "Fill = 5-minute option-bar VWAP at the entry / exit time, plus a half-spread (ETF 1.5%, stock 3%) and $0.65/contract each side.",
         "`model` = the same trades priced by the Black-Scholes proxy used everywhere else in round 4.", "",
         "| strategy | trades | matched | model exp/trade | REAL exp/trade | REAL @ VWAP (no spread) | REAL win | REAL PF | REAL t | corr(model, real) | model entry px / real |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    store = {}
    for name in RULES:
        tr, _ = run(B, name, (pd.Timestamp("2021-01-01"), END))
        tr = [t for t in tr if t.entry_time >= START]
        df = replay(tr, factor)
        CACHE.write_text(json.dumps(cache))
        ok = df[df.status == "ok"]
        r = ok["real"]
        pnl_pos, pnl_neg = r[r > 0].sum(), -r[r < 0].sum()
        tt = r.mean() / r.std(ddof=1) * np.sqrt(len(r)) if len(r) > 2 else np.nan
        L.append(f"| {name} | {len(tr)} | {len(ok)} | {fmt(ok['model'].mean(), True)} | **{fmt(r.mean(), True)}** | {fmt(ok['real_vwap'].mean(), True)} | "
                 f"{fmt((r > 0).mean())} | {fmt(pnl_pos / pnl_neg if pnl_neg else np.nan)} | {fmt(tt)} | {fmt(ok['model'].corr(r))} | "
                 f"{fmt((ok['model_px'] / ok['real_px']).median())} |")
        store[name] = df
        print(L[-1], flush=True)
    L += ["", "PF here = sum of winning returns / sum of losing returns (equal premium per trade). t = i.i.d. t-statistic."]
    (OUT / "REAL_OPTIONS.md").write_text("\n".join(L), encoding="utf-8")
    pd.to_pickle(store, OUT / "real_options.pkl")


if __name__ == "__main__":
    main()
