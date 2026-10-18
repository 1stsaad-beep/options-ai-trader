# Wave-2/B exhaustion on intraday bars (daily trend as higher timeframe)

| bars | variant | period | chosen | n | win | exp/trade | PF | t(week) | 2× spr |
|---|---|---|---|---|---|---|---|---|---|
| 60m | wave | disc | (0.7, (0.75, 1.0, None), 2) | 287 | 0.48 | +2.2% | 1.05 | 0.12 | |
| 60m | wave | valid | | 312 | 0.43 | -2.5% | 0.94 | -0.26 | -6.9% |
| 60m | control (no wave) | disc | (0.5, (None, None, 14), 2) | 2338 | 0.35 | -3.2% | 0.84 | -0.84 | |
| 60m | control (no wave) | valid | | 2692 | 0.35 | +0.6% | 0.99 | 0.11 | -3.2% |
| 15m | wave | disc | (0.5, (None, None, 56), 2) | 650 | 0.33 | +0.7% | 0.95 | 0.45 | |
| 15m | wave | valid | | 630 | 0.34 | -5.5% | 0.89 | -2.18 | -9.1% |
| 15m | control (no wave) | disc | (0.5, (None, None, 56), 2) | 2648 | 0.34 | -2.0% | 0.88 | -0.61 | |
| 15m | control (no wave) | valid | | 2799 | 0.36 | -0.1% | 0.97 | -0.43 | -2.2% |