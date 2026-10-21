"""Data tools for the agent (spec §4) + decision recorder (§11: full decision snapshot per decision, replayable).
Every call goes through ToolBox.call(), which records name, arguments, result and time into the open recording."""
from __future__ import annotations
import datetime as dt
from . import indicators as I, nyse
from .models import occ_symbol

INDICATORS = ("rsi", "macd", "bollinger", "keltner", "atr", "adx", "sma20", "sma50", "sma200", "ema20", "ema50", "ema200",
              "vwap", "avwap", "volume_profile", "rvol", "rs_spy", "rs_qqq")


def _r(x, k=4):
    return None if x is None else round(float(x), k)


class Recorder:
    def __init__(self):
        self.calls = []

    def add(self, now, name, args, result):
        self.calls.append(dict(t=now.isoformat(), tool=name, args=args, result=result))


class ToolBox:
    def __init__(self, data, size_tools, events, clock, universe):
        self.data, self.size, self.events, self.clock = data, size_tools, events, clock
        self.universe = list(universe)
        self.recorder: Recorder | None = None

    # ------------------------------------------------------------------ dispatcher
    def call(self, name, args):
        fn = {"get_bars": self.get_bars, "get_indicators": self.get_indicators, "get_quote": self.get_quote,
              "get_chain": self.get_chain, "expected_range": self.expected_range, "check_target": self.check_target,
              "get_events": self.get_events, "tradable_today": self.tradable_today}.get(name)
        if fn is None: raise KeyError(f"unknown tool {name}")
        res = fn(**args)
        if self.recorder is not None: self.recorder.add(self.clock(), name, args, res)
        return res

    # ------------------------------------------------------------------ bars / indicators
    def get_bars(self, sym, tf, n=100, ext_hours=False):
        n = max(1, min(int(n), 1000))
        bars = self.data.bars(sym, tf, n, self.clock(), ext_hours=ext_hours)
        return dict(sym=sym, tf=tf, n=len(bars), ext_hours=ext_hours,
                    bars=[[b["t"].isoformat(), b["o"], b["h"], b["l"], b["c"], b["v"]] for b in bars])

    def get_indicators(self, sym, tf, names, n=300, anchor=None):
        now = self.clock()
        unknown = [x for x in names if x not in INDICATORS]
        if unknown: raise ValueError(f"unknown indicators {unknown}; allowed {list(INDICATORS)}")
        need = 860 if ("rvol" in names and tf in ("1m", "5m", "15m")) else n
        bars = self.data.bars(sym, tf, need, now)
        if not bars: return dict(sym=sym, tf=tf, error="no bars")
        h, l, c = [b["h"] for b in bars], [b["l"] for b in bars], [b["c"] for b in bars]
        last = lambda arr, k=3: [_r(v) for v in arr[-k:]]
        out = dict(sym=sym, tf=tf, bars=len(bars), last_bar=bars[-1]["t"].isoformat(), close=c[-1])
        for x in names:
            if x == "rsi": out[x] = last(I.rsi(c))
            elif x == "macd":
                line, sig, hist = I.macd(c); out[x] = dict(line=last(line), signal=last(sig), hist=last(hist))
            elif x == "bollinger":
                m, u, lo, w = I.bollinger(c); out[x] = dict(mid=_r(m[-1]), upper=_r(u[-1]), lower=_r(lo[-1]), width=last(w))
            elif x == "keltner":
                m, u, lo = I.keltner(h, l, c); out[x] = dict(mid=_r(m[-1]), upper=_r(u[-1]), lower=_r(lo[-1]))
            elif x == "atr": out[x] = last(I.atr(h, l, c))
            elif x == "adx":
                a, p, q = I.adx(h, l, c); out[x] = dict(adx=last(a), plus_di=last(p), minus_di=last(q))
            elif x.startswith("sma"): out[x] = _r(I.sma(c, int(x[3:]))[-1])
            elif x.startswith("ema"): out[x] = _r(I.ema(c, int(x[3:]))[-1])
            elif x == "vwap": out[x] = {k: _r(v) for k, v in (I.session_vwap(bars)[-1] or {}).items()}
            elif x == "avwap":
                if not anchor: out[x] = "anchor required (ISO time)"
                else: out[x] = _r(I.anchored_vwap(bars, dt.datetime.fromisoformat(anchor.replace("Z", "+00:00")))[-1])
            elif x == "volume_profile":
                vp = I.volume_profile(bars[-min(len(bars), n):]); out[x] = dict(poc=_r(vp["poc"]), vah=_r(vp["vah"]), val=_r(vp["val"]))
            elif x == "rvol": out[x] = _r(I.relative_volume(bars), 3)
            elif x in ("rs_spy", "rs_qqq"):
                b2 = self.data.bars("SPY" if x == "rs_spy" else "QQQ", tf, len(bars), now)
                k = min(len(bars), len(b2))
                out[x] = dict(last_20_bars_pct=_r(I.relative_strength(c[-k:], [b["c"] for b in b2[-k:]], 20), 3))
        return out

    # ------------------------------------------------------------------ quote
    def get_quote(self, sym):
        now = self.clock()
        s = self.data.snapshot(sym)
        age = None if s["last_ts"] is None else round((now - s["last_ts"]).total_seconds(), 1)
        return dict(sym=sym, last=s["last"], last_age_s=age, bid=s["bid"], ask=s["ask"], day_high=s["day_high"],
                    day_low=s["day_low"], day_vwap=s["day_vwap"], prev_close=s["prev_close"], now=now.isoformat())

    # ------------------------------------------------------------------ chain
    def get_chain(self, sym, expiries, width_pct=8.0):
        now = self.clock()
        q = self.data.snapshot(sym)
        px = q["last"]
        out = dict(sym=sym, underlying=px, underlying_age_s=None if q["last_ts"] is None else round((now - q["last_ts"]).total_seconds(), 1),
                   expiries=[])
        for e in expiries:
            exp = dt.date.fromisoformat(e) if isinstance(e, str) else e
            contracts = self.data.option_contracts(sym, exp)
            snaps = self.data.option_snapshots(sym, exp)
            rows = []
            for c in contracts:
                k = float(c["strike_price"])
                if px and abs(k / px - 1) * 100 > width_pct: continue
                occ = c["symbol"]
                s = snaps.get(occ) or {}
                lq, g = s.get("latestQuote") or {}, s.get("greeks") or {}
                qt = lq.get("t")
                rows.append(dict(occ=occ, type=c["type"], strike=k, bid=lq.get("bp"), ask=lq.get("ap"),
                                 quote_age_s=None if not qt else round((now - _parse(qt)).total_seconds(), 1),
                                 iv=s.get("impliedVolatility"), delta=g.get("delta"), gamma=g.get("gamma"), theta=g.get("theta"),
                                 oi=_int(c.get("open_interest")), volume=(s.get("dailyBar") or {}).get("v")))
            rows.sort(key=lambda r: (r["strike"], r["type"]))
            out["expiries"].append(dict(expiry=exp.isoformat(), contracts=rows, straddle=_straddle(rows, px)))
        return out

    # ------------------------------------------------------------------ size tools / events / universe
    def expected_range(self, sym):
        return self.size.expected_range(sym)

    def check_target(self, sym, price):
        return self.size.check_target(sym, float(price))

    def get_events(self, sym, days=5):
        return self.events.get(sym, nyse.wall(self.clock()).date(), int(days))

    def tradable_today(self):
        """Spec §2: a stock is tradable only if its real chain has an expiry today or on the next session."""
        now = self.clock()
        today = nyse.wall(now).date()
        tomorrow = nyse.next_trading_day(today)
        out = []
        for sym in self.universe:
            exps = [d.isoformat() for d in (today, tomorrow) if self.data.option_contracts(sym, d)]
            out.append(dict(sym=sym, tradable=bool(exps), expiries=exps))
        return dict(date=today.isoformat(), next_session=tomorrow.isoformat(), symbols=out)


def _parse(s):
    from .broker import _t
    return _t(s)


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _straddle(rows, px):
    """Nearest-to-price strike having both a call and a put with two-sided quotes: mid(call) + mid(put)."""
    if not px: return None
    by = {}
    for r in rows:
        if r["bid"] and r["ask"]: by.setdefault(r["strike"], {})[r["type"]] = (r["bid"] + r["ask"]) / 2
    both = [k for k, v in by.items() if "call" in v and "put" in v]
    if not both: return None
    k = min(both, key=lambda s: abs(s - px))
    move = by[k]["call"] + by[k]["put"]
    return dict(strike=k, implied_move=round(move, 4), implied_move_pct=round(100 * move / px, 3))


def save_decision(store, now, kind, recorder: Recorder, journal_id=None, model_id=None, prompt_version=None, extra=None):
    """Full decision snapshot (§11): every tool call with its exact result, plus model id and prompt version."""
    return store.snapshot_add(now, kind, dict(calls=recorder.calls, extra=extra or {}), journal_id=journal_id,
                              model_id=model_id, prompt_version=prompt_version)
