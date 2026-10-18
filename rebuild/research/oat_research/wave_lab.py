"""Wave-2 / wave-B laboratory: collect every triggered setup with ~20 candidate
confirmation features, so each indicator/average can be measured on its own
(feature lift) before any of them becomes an entry rule.

Setup (same geometry as intraday.wave_divergence, divergence NOT required):
  zig-zag (pivots 3/2, swings >= 1.5 ATR) -> s0, s1, s2 ;
  leg1 >= 3 ATR ; correction 38.2%..88.6% ; s2 does not break s0 ;
  trigger within 10 bars: close beyond the last 3 bars' extreme and beyond EMA20.
Tag: W2->3 when leg1 broke the previous same-side swing (structure break), else B->C.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import indicators as ind
from .intraday import WDParams, _ZigZagATR


def _avwap(tp, vol, start, end):
    w = vol[start:end + 1]
    return float((tp[start:end + 1] * w).sum() / w.sum()) if w.sum() > 0 else np.nan


def candidates(df: pd.DataFrame, p: WDParams = WDParams(), spy: pd.DataFrame | None = None,
               htf_up: pd.Series | None = None) -> pd.DataFrame:
    """One row per triggered setup. `htf_up` (optional, aligned to df.index, causal):
    True when the higher timeframe trend is up."""
    n = len(df)
    o, h, l, c, v = (df[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
    tp = (h + l + c) / 3
    atr = ind.atr(df).to_numpy()
    rsi = ind.rsi(df["close"]).to_numpy()
    close = df["close"]
    macd_line = (ind.ema(close, 12) - ind.ema(close, 26))
    macd_sig = ind.ema(macd_line, 9)
    hist = (macd_line - macd_sig).to_numpy()
    macd_line, macd_sig = macd_line.to_numpy(), macd_sig.to_numpy()
    e20, e50 = ind.ema(close, 20).to_numpy(), ind.ema(close, 50).to_numpy()
    s200 = ind.sma(close, 200).to_numpy()
    adx = ind.adx(df).to_numpy()
    k = ind.stoch_k(df).to_numpy()
    mid = ind.sma(close, 20)
    sd = close.rolling(20).std(ddof=0)
    bb_lo, bb_hi = (mid - 2 * sd).to_numpy(), (mid + 2 * sd).to_numpy()
    vol20 = ind.sma(df["volume"], 20).to_numpy()
    clv = ind.close_location(df).to_numpy()
    ret63 = (close / close.shift(63) - 1).to_numpy()
    mret = (spy["close"].reindex(df.index).ffill() / spy["close"].reindex(df.index).ffill().shift(63) - 1).to_numpy() \
        if spy is not None else np.zeros(n)
    htf = htf_up.reindex(df.index).astype(float).to_numpy() if htf_up is not None else np.full(n, np.nan)
    piv = ind.pivots(df, p.left, p.right)
    zz = _ZigZagATR(atr, p.swing_atr)
    known, rows = [], []
    armed = None
    j = 0
    for t in range(n):
        new = False
        while j < len(piv) and piv[j][1] <= t:
            known.append(piv[j]); zz.add(piv[j]); new |= zz.changed; j += 1
        if new and len(zz.out) >= 3 and np.isfinite(atr[t]):
            s0, s1, s2 = zz.out[-3:]
            bull = not s2[3]
            leg1 = abs(s1[2] - s0[2])
            retr = abs(s1[2] - s2[2]) / leg1 if leg1 > 0 else 9
            ok = leg1 >= p.leg1_min_atr * atr[t] and p.retr_min <= retr <= p.retr_max
            ok &= (s2[2] > s0[2]) if bull else (s2[2] < s0[2])
            if ok:
                prev_same = [q for q in zz.out[:-3] if q[3] == s1[3]]
                bos = bool(prev_same) and ((s1[2] > prev_same[-1][2]) if bull else (s1[2] < prev_same[-1][2]))
                internal = [q for q in known if q[3] == s2[3] and s1[0] < q[0] < s2[0]]
                armed = dict(s0=s0, s1=s1, s2=s2, bull=bull, leg1=leg1, retr=retr, bos=bos, internal=internal,
                             until=t + p.arm_bars)
            else:
                armed = None
        if armed is None:
            continue
        d = 1 if armed["bull"] else -1
        s0, s1, s2 = armed["s0"], armed["s1"], armed["s2"]
        if t > armed["until"] or (d > 0 and l[t] < s2[2]) or (d < 0 and h[t] > s2[2]):
            armed = None
            continue
        if t < 3 or not np.isfinite(e20[t]):
            continue
        trig = (c[t] > h[t - 3:t].max() and c[t] > e20[t]) if d > 0 else (c[t] < l[t - 3:t].min() and c[t] < e20[t])
        if not trig:
            continue
        a = atr[t]
        stop = s2[2] - d * 0.25 * a
        tgt = s2[2] + d * p.target_leg * armed["leg1"]
        if (tgt - c[t]) * d <= 0 or (c[t] - stop) * d <= 0:
            armed = None
            continue
        i0, i1, i2 = s0[0], s1[0], s2[0]

        def div(osc):
            hid = reg = False
            if np.isfinite(osc[i2]) and np.isfinite(osc[i0]):
                hid = (osc[i2] < osc[i0]) if d > 0 else (osc[i2] > osc[i0])
            for q in armed["internal"]:
                if np.isfinite(osc[q[0]]) and np.isfinite(osc[i2]):
                    if d > 0 and s2[2] < q[2] and osc[i2] > osc[q[0]]:
                        reg = True
                    if d < 0 and s2[2] > q[2] and osc[i2] < osc[q[0]]:
                        reg = True
            return hid, reg

        rh, rr = div(rsi)
        mh, mr = div(hist)
        leg_bars, corr_bars = max(1, i1 - i0), max(1, i2 - i1)
        vol_leg = v[i0:i1 + 1].mean()
        vol_corr = v[i1:i2 + 1].mean()
        av = _avwap(tp, v, i0, t)
        rows.append(dict(
            t=t, date=df.index[t], dir=d, tag="W2" if armed["bos"] else "B", retr=armed["retr"],
            leg1_atr=armed["leg1"] / a, stop=stop, target=tgt,
            div_rsi_hidden=rh, div_rsi_regular=rr, div_macd_hidden=mh, div_macd_regular=mr,
            div_any=rh or rr or mh or mr, div_rsi=rh or rr, div_macd=mh or mr,
            golden=0.5 <= armed["retr"] <= 0.66,
            rsi_pivot=rsi[i2] if d > 0 else 100 - rsi[i2],            # low = oversold for bulls
            stoch_pivot=k[i2] if d > 0 else 100 - k[i2],
            bb_tag=bool(l[i2] <= bb_lo[i2]) if d > 0 else bool(h[i2] >= bb_hi[i2]),
            vol_dryup=vol_corr < 0.8 * vol_leg,
            time_ratio=corr_bars / leg_bars,
            trend200=bool((c[t] > s200[t]) if d > 0 else (c[t] < s200[t])) if np.isfinite(s200[t]) else False,
            above_ema50=bool((c[t] > e50[t]) if d > 0 else (c[t] < e50[t])),
            ema_stack=bool((e20[t] > e50[t]) if d > 0 else (e20[t] < e50[t])),
            ema50_slope=bool((e50[t] > e50[t - 10]) if d > 0 else (e50[t] < e50[t - 10])) if t >= 10 else False,
            adx=adx[t], adx_rising=bool(adx[t] > adx[t - 5]) if t >= 5 else False,
            macd_hist_rising=bool((hist[t] > hist[t - 1]) if d > 0 else (hist[t] < hist[t - 1])),
            macd_above_signal=bool((macd_line[t] > macd_sig[t]) if d > 0 else (macd_line[t] < macd_sig[t])),
            macd_zero_side=bool((macd_line[t] > 0) if d > 0 else (macd_line[t] < 0)),
            avwap_hold=bool((c[t] > av) if d > 0 else (c[t] < av)),
            trig_relvol=v[t] / vol20[t] if np.isfinite(vol20[t]) and vol20[t] > 0 else np.nan,
            trig_clv=clv[t] if d > 0 else 1 - clv[t],
            rs=bool((ret63[t] > mret[t]) if d > 0 else (ret63[t] < mret[t])) if np.isfinite(ret63[t]) else False,
            htf=np.nan if not np.isfinite(htf[t]) else float((htf[t] == 1.0) if d > 0 else (htf[t] == 0.0)),
            bars_to_trigger=t - s2[1],
        ))
        armed = None
    return pd.DataFrame(rows)


def add_outcomes(cand: pd.DataFrame, df: pd.DataFrame, horizon: int = 10) -> pd.DataFrame:
    """fwd10 (ATR units from next open, direction-adjusted) and hit (+2 ATR before -1 ATR)."""
    if cand.empty:
        return cand
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = ind.atr(df).to_numpy()
    fwd, hit = [], []
    for t, d in zip(cand.t, cand.dir):
        if t + horizon + 1 >= len(df):
            fwd.append(np.nan); hit.append(np.nan); continue
        e = o[t + 1]
        fwd.append(d * (c[t + 10 if t + 10 < len(df) else -1] - e) / a[t])
        fav = (h[t + 1:t + 1 + horizon] - e) / a[t] if d > 0 else (e - l[t + 1:t + 1 + horizon]) / a[t]
        adv = (e - l[t + 1:t + 1 + horizon]) / a[t] if d > 0 else (h[t + 1:t + 1 + horizon] - e) / a[t]
        r = 0
        for fv, av in zip(fav, adv):
            if av >= 1.0:
                break
            if fv >= 2.0:
                r = 1
                break
        hit.append(r)
    out = cand.copy()
    out["fwd10"], out["hit"] = fwd, hit
    return out


def to_signals(df: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    sig = pd.DataFrame({"dir": 0, "stop": np.nan, "target": np.nan, "reason": ""}, index=df.index)
    for r in rows.itertuples():
        sig.iloc[r.t, 0] = r.dir
        sig.iloc[r.t, 1] = r.stop
        sig.iloc[r.t, 2] = r.target
        sig.iloc[r.t, 3] = f"{r.tag} wave setup"
    return sig
