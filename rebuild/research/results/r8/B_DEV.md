# Strategy B — development (selection on discovery 2016–2020, underlying expectancy in ATR)

| variant | DISC trades | DISC underlying E[ATR] | VALID trades | VALID underlying E[ATR] |
|---|---|---|---|---|
| {'breadth_min': 7, 'drop': 0.5, 'vol_mult': 1.5} | 5 | +0.060 | 1 | +nan |
| {'breadth_min': 7, 'drop': 0.5, 'vol_mult': 1.2} | 6 | -0.013 | 3 | -0.114 |
| {'breadth_min': 7, 'drop': 0.3, 'vol_mult': 1.5} | 8 | -0.098 | 3 | -0.093 |
| {'breadth_min': 7, 'drop': 0.3, 'vol_mult': 1.2} | 11 | -0.015 | 10 | +0.050 |
| {'breadth_min': 5, 'drop': 0.5, 'vol_mult': 1.5} | 5 | +0.060 | 1 | +nan |
| {'breadth_min': 5, 'drop': 0.5, 'vol_mult': 1.2} | 6 | -0.013 | 3 | -0.114 |
| {'breadth_min': 5, 'drop': 0.3, 'vol_mult': 1.5} | 10 | -0.010 | 3 | -0.093 |
| {'breadth_min': 5, 'drop': 0.3, 'vol_mult': 1.2} | 14 | +0.035 | 10 | +0.050 |

**Chosen on discovery:** {'breadth_min': 5, 'drop': 0.3, 'vol_mult': 1.2}

## Judgement of the developed variant (backtested)

| test | n | win | avg win | avg loss | return/trade | PF | t | maxDD* |
|---|---|---|---|---|---|---|---|---|
| model discovery — without contract filters | 14 | 0.50 | +21.7% | -20.6% | **+0.6%** | 1.05 | 0.08 | -1.6% |
| model discovery — with contract filters | 0 | — | — | — | — | — | — | — |
| model validation — without contract filters | 10 | 0.50 | +19.5% | -16.9% | **+1.3%** | 1.16 | 0.18 | -0.9% |
| model validation — with contract filters | 2 | — | — | — | — | — | — | — |
| model holdout — without contract filters | 0 | — | — | — | — | — | — | — |
| model holdout — with contract filters | 0 | — | — | — | — | — | — | — |
| REAL development symbols — all matched | 0 | — | — | — | — | — | — | — |
| REAL development symbols — with report's contract filters | 0 | — | — | — | — | — | — | — |