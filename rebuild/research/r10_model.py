"""Round 10 — the big-move rule over the full daily history 1999-2026 (45 symbols): stock and weekly calls
priced with the real-calibrated model, entry at the close, exit at the close two sessions later.
Results by year and by selloff episode (signals cluster in time, so the per-trade t-stat overstates the evidence).
python r10_model.py -> results/r10/MODEL_HISTORY.md"""
import numpy as np, pandas as pd
from oat_research import data as D, indicators as ind, setups4 as S4, shortdated as SD
from r4_common import costs, fmt, load_daily
from r4_close import two_bar, place
from r7_lib import ORIG, NEW

d1, vols = load_daily()
data = {s: (d1[s] if s in d1 else D.load_csv(f"data/d1x/{s}.csv")) for s in ORIG + NEW}
spy = d1["SPY"]["close"]
ivs = SD.iv_table(data, vols)
bars = {s: two_bar(df) for s, df in data.items()}
sigs = {}
for s, df in data.items():
    c = df["close"]; bbp = ind.rolling_percentile(ind.bb_width(c, 20), 126)
    sp = spy.reindex(df.index).ffill()
    m = (bbp > 0.8) & (c / c.shift(20) - 1 < -0.10) & (sp / sp.shift(5) - 1 < -0.03)
    f = S4.frame(df, np.where(m, 1, 0), reason=np.where(m, "big-move", ""))
    f["xsched"] = pd.Series(m.to_numpy(), index=df.index).shift(2, fill_value=False).to_numpy()
    sigs[s] = place(f, bars[s])
cfg = SD.SDConfig("bm", SD.SDExit(target_atr=None, stop_atr=None, use_signal_levels=False), target_delta=0.5, min_days=4,
                  budget=0.0001, max_open=500, iv_term=SD.calibrated_term)
tr, _ = SD.run(bars, sigs, cfg, data, ivs, costs(data), pd.Timestamp("1999-06-01"), pd.Timestamp("2026-10-16"), initial=1e9)
df = pd.DataFrame([dict(sym=t.symbol, entry=t.entry_time, stock=t.exit_spot / t.entry_spot - 1, call=t.net_ret,
                        orig=t.symbol in ORIG) for t in tr])
df["year"] = df.entry.dt.year
# episodes: consecutive signal days separated by > 10 calendar days
days = df.entry.dt.normalize().sort_values().unique()
ep, k, last = {}, 0, None
for d in days:
    if last is None or (d - last).days > 10:
        k += 1
    ep[d] = k; last = d
df["episode"] = df.entry.dt.normalize().map(ep)
L = ["# Big-move rule over 1999–2026 (daily, 45 symbols) — stock and model-priced weekly calls (backtested)", "",
     f"Trades: {len(df)}; distinct selloff episodes: {df.episode.nunique()}.", "",
     "| group | trades | stock mean | stock win | call (model) mean | call win |", "|---|---|---|---|---|---|"]
def r(name, x):
    L.append(f"| {name} | {len(x)} | {x.stock.mean()*100:+.2f}% | {(x.stock>0).mean()*100:.0f}% | {x.call.mean()*100:+.1f}% | {(x.call>0).mean()*100:.0f}% |")
r("all", df); r("original 15", df[df.orig]); r("new 30", df[~df.orig])
for y, g in df.groupby("year"):
    r(f"year {y}", g)
e = df.groupby("episode").agg(start=("entry", "min"), n=("stock", "size"), stock=("stock", "mean"), call=("call", "mean"))
L += ["", "## By episode (equal weight per episode)", "",
      f"Episodes with positive mean stock return: {(e.stock > 0).mean()*100:.0f}% ; with positive mean call return: {(e.call > 0).mean()*100:.0f}% ; "
      f"mean of episode means: stock {e.stock.mean()*100:+.2f}%, call {e.call.mean()*100:+.1f}%; "
      f"t over episodes (stock) {e.stock.mean()/e.stock.std(ddof=1)*np.sqrt(len(e)):.2f}, (call) {e.call.mean()/e.call.std(ddof=1)*np.sqrt(len(e)):.2f}", "",
      "| episode start | trades | stock mean | call mean |", "|---|---|---|---|"]
for _, x in e.sort_values("start").iterrows():
    L.append(f"| {x.start:%Y-%m-%d} | {int(x.n)} | {x.stock*100:+.2f}% | {x.call*100:+.1f}% |")
open("results/r10/MODEL_HISTORY.md", "w").write("\n".join(L)); print("\n".join(L[:45]))
