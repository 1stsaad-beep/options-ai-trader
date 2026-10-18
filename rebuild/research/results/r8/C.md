# Strategy C — literal test (backtested)

Signals 2016–2026 (all symbols): 1

## 1. Underlying (model trades, before option filters)

| period | trades | underlying move/trade (dir.) | hit target | hit stop | time exit |
|---|---|---|---|---|---|
| discovery 2016–20 | 0 | — | — | — | — |
| validation 2021–26/04 | 1 | — | — | — | — |
| holdout 26/04–26/10 | 0 | — | — | — | — |

## 2. Calibrated model, weekly options 3–6 DTE, report's filters (model IV/RV ≤ 1.30, premium cap)

| test | n | win | avg win | avg loss | return/trade | PF | t | maxDD* |
|---|---|---|---|---|---|---|---|---|
| model — discovery | 0 | — | — | — | — | — | — | — |
| model — validation | 0 | — | — | — | — | — | — | — |
| model — holdout | 0 | — | — | — | — | — | — | — |
| model — discovery+validation, no contract filters | 1 | — | — | — | — | — | — | — |
| model validation — 2× costs | 0 | — | — | — | — | — | — | — |

## 3. REAL option prices 2024-02 → 2026-10 (0 trades before filters; 0 matched to a traded contract; 0 pass the report's contract filters)

| test | n | win | avg win | avg loss | return/trade | PF | t | maxDD* |
|---|---|---|---|---|---|---|---|---|
| REAL — all matched (no contract filters) | 0 | — | — | — | — | — | — | — |
| REAL — with the report's filters (THE RULE) | 0 | — | — | — | — | — | — | — |

Rejected by the contract filters: 