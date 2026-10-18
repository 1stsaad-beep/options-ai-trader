# research/ — strategy research harness (Python)

Deterministic backtesting harness used to design and validate engines before they
are ported to Dart (`trader_core`). Read `STRATEGY_RESEARCH.md` for the study.

```
oat_research/
  data.py           CSV loader (Yahoo/Stooq, adjusted), synthetic generator for validation only
  indicators.py     causal indicators + confirmed pivots/zigzag (same formulas as Dart)
  options_model.py  Black–Scholes option P&L with IV proxy, skew, spreads, commissions
  baseline.py       faithful port of the app's current six engines + composite score
  engines_v2.py     quality_gate (filters), RCB (compression breakout), TPB (trend pullback)
  backtest.py       event-driven daily portfolio sim (next-open entries, Call/Put lock)
  study.py          signal quality, walk-forward, stats
validate_harness.py null-model (no leak) + planted-edge (detection) checks
run_study.py        full study on a folder of real CSVs -> results/RESULTS.md
```

Requirements: Python ≥ 3.11, numpy, pandas.

```
python validate_harness.py
python run_study.py data/ --out results --split 2020
```
