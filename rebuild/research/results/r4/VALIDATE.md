# Weekly-option engine — harness validation (synthetic data, 10 series × 3000 days)

| data | signal | n | exp/trade | t(week) | underlying move 3d (ATR) |
|---|---|---|---|---|---|
| null (no edge) | planted rule | 683 | +1.9% | -0.37 | +0.11 |
| null (no edge) | random 3% | 749 | -2.9% | -0.60 | +nan |
| planted edge | planted rule | 1006 | +42.0% | 10.80 | +0.60 |
| planted edge | random 3% | 524 | -1.6% | 0.45 | +nan |