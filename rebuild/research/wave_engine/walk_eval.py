"""Summaries of the walk-forward results: hit rate vs the random-walk expectation, expectancy in R, by forecaster,
timeframe, current wave, probability bucket, direction and year."""
import glob
import numpy as np
import pandas as pd


def load(tf=None):
    fs = sorted(glob.glob(f"results/wave/walk_{tf or '*'}_*.pkl"))
    return pd.concat([pd.read_pickle(f) for f in fs], ignore_index=True) if fs else pd.DataFrame()


def summ(d):
    r = d.r_out.dropna(); res = d.hit.notna()
    day = d.dropna(subset=["r_out"]).groupby(d.t.dt.normalize()).r_out.mean()
    return pd.Series(dict(n=len(d), resolved=res.mean(), hit=d.hit[res].mean(), p_rw=d.p_rw[res].mean(),
                          edge=(d.hit[res] - d.p_rw[res]).mean(), R=d.R.median(), exp_R=r.mean(),
                          t=day.mean() / day.std(ddof=1) * np.sqrt(len(day)) if len(day) > 2 else np.nan))


def report(D):
    out = {}
    out["by forecaster"] = D.groupby(["tf", "who"]).apply(summ)
    W = D[D.who == "wave1"].copy()
    out["wave1 by current wave"] = W.groupby(["tf", "cur"]).apply(summ).query("n >= 30")
    W["pbin"] = pd.cut(W.prob, [0, 0.15, 0.3, 0.5, 1.0])
    out["wave1 by probability"] = W.groupby(["tf", "pbin"], observed=True).apply(summ)
    out["wave1 by direction"] = W.groupby(["tf", "up"]).apply(summ)
    out["wave1 by year"] = W.groupby(["tf", W.t.dt.year]).apply(summ)
    return out


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    D = load()
    for k, v in report(D).items():
        print("\n##", k); print(v.round(3).to_string())
