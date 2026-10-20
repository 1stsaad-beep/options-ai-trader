# Round W2 — wave personality, end-of-5, Fibonacci time (pre-registered: PREREG_ROUND_W2.json)

## T4a — choose the scenario whose current wave best matches its indicator personality (user's table)
| tf | scenario 1 skill (hit vs drift-matched null) | personality-chosen skill | chosen - scenario 1 |
|---|---|---|---|
| 5-min | +0.7 % | -0.7 % | -2.3 % (t -0.6) |
| 1-hour | -0.6 % | -0.3 % | -0.9 % (t -0.1) |
| daily | +0.6 % | +0.2 % | -0.5 % (t -0.1) |
FAIL: personality does not pick the better scenario.

## T4b — keep decision points only when wave 2 / 4 has the expected personality
1-hour early-3: all +0.3 %, personality >= 0.75 -0.2 %, = 1.0 -0.5 %, low personality (<0.5) +0.9 %.
Daily early-3: all +1.6 %, >= 0.75 +1.5 %, = 1.0 +1.1 %, low +1.9 %. Early-5 similar. FAIL: no improvement (if anything the opposite).

## T3 — do swing durations relate by Fibonacci ratios (0.618 / 1 / 1.618 / 2.618, +-10 %) more than chance?
| tf | observed share | shuffled mean | shuffled 97.5 % | ratios |
|---|---|---|---|---|
| daily (2000+) | 22.7 % | 23.0 % | 23.6 % | 19,377 |
| 1-hour | 23.6 % | 23.4 % | 23.8 % | 38,516 |
FAIL (300 shuffles instead of the planned 1000 for compute; the observed value is at the shuffle mean, so more shuffles cannot change the verdict).
