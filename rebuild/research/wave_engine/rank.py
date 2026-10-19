"""Learned ranking (pairwise logistic trained on synthetic charts with known counts; target = correct CURRENT wave).
score -> log-probability within the candidate set, so a chain's score is the sum of log-probabilities."""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path
import numpy as np
from .train_rank import featurize

MODEL = Path(__file__).resolve().parents[1] / "results/wave/rank_model.json"


@lru_cache(maxsize=1)
def _model():
    if not MODEL.exists(): return None
    m = json.load(open(MODEL)); m["w"] = np.array(m["w"]); m["mu"] = np.array(m["mu"]); m["sd"] = np.array(m["sd"])
    m["ix"] = {c: i for i, c in enumerate(m["cols"])}
    return m


def learned_logp(scen):
    m = _model()
    if m is None or not scen: return scen
    X = np.zeros((len(scen), len(m["cols"])))
    for r, z in enumerate(scen):
        for k, v in featurize(z).items():
            i = m["ix"].get(k)
            if i is not None: X[r, i] = v
    s = ((X - m["mu"]) / m["sd"]) @ m["w"]
    s = s - (s.max() + np.log(np.exp(s - s.max()).sum()))
    for z, v in zip(scen, s):
        z.raw_score = z.score; z.score = float(v)
    scen.sort(key=lambda z: -z.score)
    return scen
