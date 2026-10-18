# Round 4 — act at 15:50 (5-minute data, 2016–2026)

Signals are computed on a daily series whose close is the 15:50 price, so the trade is placed the same afternoon.

## Discovery 2016–2020 → chosen rule

| strategy | chosen delta / exit / min days | n | win | exp/trade | PF | t(week) |
|---|---|---|---|---|---|---|
| Pre-FOMC 15:50→13:55 | 0.7 / (0.75, 1.0, None) / 2 | 117 | 0.34 | -2.8% | 0.79 | -0.54 |
| Pre-FOMC 15:50→15:50 (holds through statement) | 0.7 / (None, None, None) / 2 | 117 | 0.39 | -1.8% | 0.87 | -0.24 |
| ETF dip @15:50 | 0.5 / (0.75, 1.0, None) / 2 | 147 | 0.56 | +19.9% | 1.61 | 2.91 |
| ETF bear-rally puts @15:50 | 0.7 / (0.5, 1.0, None) / 2 | 51 | 0.41 | -9.9% | 0.60 | -0.11 |
| VIX spike reversal @15:50 | 0.7 / (None, None, None) / 5 | 77 | 0.40 | -5.1% | 0.85 | -0.48 |

## Validation 2021 – 2026-04-15 (frozen rules)

| strategy | n | win | avg win | avg loss | exp/trade | PF | t(week) | ½ spreads | 2× spreads | maxDD* | median hours |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Pre-FOMC 15:50→13:55 | 126 | 0.47 | +41.2% | -28.4% | +4.2% | 1.25 | 0.62 | +5.7% | +1.1% | -9.4% | 22 |
| Pre-FOMC 15:50→15:50 (holds through statement) | 126 | 0.48 | +70.7% | -45.4% | +9.9% | 1.37 | 0.97 | +11.6% | +6.6% | -12.4% | 24 |
| ETF dip @15:50 | 187 | 0.54 | +79.4% | -71.3% | +10.1% | 1.27 | 2.36 | +11.9% | +6.6% | -19.2% | 48 |
| ETF bear-rally puts @15:50 | 54 | 0.52 | +44.9% | -56.9% | -4.1% | 0.80 | 1.03 | -2.7% | -6.7% | -10.3% | 91 |
| VIX spike reversal @15:50 | 77 | 0.44 | +66.9% | -52.6% | +0.2% | 1.08 | 0.28 | +1.7% | -3.9% | -16.8% | 144 |