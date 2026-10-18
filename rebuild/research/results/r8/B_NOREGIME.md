# Strategy B without the bear-market regime (backtested)

| test | n | win | avg win | avg loss | return/trade | PF | t | maxDD* |
|---|---|---|---|---|---|---|---|---|
| **{'regime': False}** — signals 90 | | | | | | | | |
| model discovery — no contract filters | 47 | 0.47 | +26.4% | -20.4% | **+1.5%** | 1.14 | 0.38 | -3.7% |
| ↳ underlying move/trade +0.144% (n 47) | | | | | | | | |
| model validation — no contract filters | 30 | 0.27 | +18.5% | -20.2% | **-9.8%** | 0.33 | -2.67 | -6.5% |
| ↳ underlying move/trade -0.197% (n 30) | | | | | | | | |
| model holdout — no contract filters | 1 | — | — | — | — | — | — | — |
| ↳ underlying move/trade -0.104% (n 1) | | | | | | | | |
| REAL 2024-26 — all matched | 11 | 0.36 | +15.4% | -23.5% | **-9.4%** | 0.37 | -1.42 | -2.3% |
| REAL 2024-26 — with report's contract filters | 4 | 0.50 | +5.6% | -21.5% | **-8.0%** | 0.26 | -1.00 | -0.4% |
| **{'regime': False, 'breadth_min': 5, 'drop': 0.3, 'vol_mult': 1.2}** — signals 310 | | | | | | | | |
| model discovery — no contract filters | 136 | 0.41 | +23.8% | -18.6% | **-1.1%** | 0.90 | -0.53 | -9.7% |
| ↳ underlying move/trade +0.088% (n 136) | | | | | | | | |
| model validation — no contract filters | 129 | 0.36 | +15.4% | -17.5% | **-5.8%** | 0.49 | -3.44 | -13.4% |
| ↳ underlying move/trade -0.095% (n 129) | | | | | | | | |
| model holdout — no contract filters | 9 | 0.56 | +26.2% | -12.4% | **+9.0%** | 2.63 | 1.24 | -0.5% |
| ↳ underlying move/trade +0.285% (n 9) | | | | | | | | |
| REAL 2024-26 — all matched | 65 | 0.34 | +28.4% | -23.5% | **-5.9%** | 0.62 | -1.61 | -10.7% |
| REAL 2024-26 — with report's contract filters | 14 | 0.50 | +24.8% | -26.5% | **-0.8%** | 0.94 | -0.10 | -1.2% |