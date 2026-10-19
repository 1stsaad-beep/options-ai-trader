"""Round 12 step 4: test the PRE-REGISTERED combinations (results/r12/PREREG.json) out of sample.
Sets: A_hold (discovery symbols, 2024+), B_disc (holdout symbols, 2020-23), B_hold (holdout symbols, 2024+),
LARGE (40 large caps 2020+, never searched).  Trades: first signal per symbol per day, entry at the signal-bar close,
±5 % bracket to the close of the next session, 0.10 % round-trip cost."""
import json
from pathlib import Path
import numpy as np, pandas as pd
from r12_search import outcome

OUT = Path("results/r12"); COST = 0.001
OVERLAP = {"TSLA", "AMD", "NVDA"}


def sets(F):
    P = pd.read_pickle(OUT / f"panel_{F}.pkl"); L = pd.read_pickle(OUT / f"panel_large_{F}.pkl")
    L = L[~L.sym.isin(OVERLAP)]
    return {"A_disc (searched)": P[(P.grp == "A") & (P.t < "2024-01-01")], "A_hold": P[(P.grp == "A") & (P.t >= "2024-01-01")],
            "B_disc": P[(P.grp == "B") & (P.t < "2024-01-01")], "B_hold": P[(P.grp == "B") & (P.t >= "2024-01-01")], "LARGE": L}


def evaluate(S, combo, d):
    sg = 1 if d == "LONG" else -1
    m = np.logical_and.reduce([S[c].to_numpy() for c in combo])
    o = sg * outcome(S); hit = S.up_next if d == "LONG" else S.dn_next; miss = S.dn_next if d == "LONG" else S.up_next
    sel = S[m].assign(o=o[m])
    r = dict(n_bars=int(m.sum()), base_hit=hit.mean(), base_miss=miss.mean(), p_hit=hit[m].mean(), p_miss=miss[m].mean())
    tr = sel.assign(day=sel.t.dt.normalize()).groupby(["sym", "day"], observed=True).head(1)
    net = tr.o - COST
    day = net.groupby(tr.day).mean()
    r.update(trades=len(tr), days=len(day), win=(net > 0).mean(), E_trade=net.mean(),
             t_day=day.mean() / day.std(ddof=1) * np.sqrt(len(day)) if len(day) > 2 else np.nan,
             E_no_top5_days=net[~tr.day.isin(day.nlargest(5).index)].mean() if len(day) > 10 else np.nan,
             base_E=(o - COST).mean())
    yrs = tr.assign(net=net).groupby(tr.t.dt.year).net.agg(["mean", "size"])
    r["by_year"] = "; ".join(f"{y}: {m*100:+.2f}% ({n})" for y, (m, n) in yrs.iterrows())
    return r


def main():
    pre = json.load(open(OUT / "PREREG.json"))
    rows = []
    for c in pre["combos"]:
        for name, S in sets(c["frame"]).items():
            r = evaluate(S, c["features"], c["dir"]); r.update(id=c["id"], set=name); rows.append(r)
            print(c["id"], name, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k != "by_year"}, flush=True)
    R = pd.DataFrame(rows); R.to_csv(OUT / "TEST.csv", index=False)
    return R


if __name__ == "__main__":
    main()
