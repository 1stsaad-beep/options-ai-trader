# RC2 Build 14 phone findings — repair checkpoint

Baseline: `615576768612c1c7cbd008632b325be05c57c774`, branch `recovery/v1.0-20261011`.

The user supplied four Android screenshots and reported successful launch/safety, synthetic buy, owned manual close, rejection of unsupported reversal, restart persistence and clipboard export. These are user-reported physical-device observations; they are not new automated results.

## Inspection before modification

- The baseline Demo underlying series rises/falls monotonically within each 300-observation segment (12 cents of drift exceeds the sinusoidal increment). No Elliott or harmonic pattern in the pictured rising prefix is a legitimate possible result, not permission to invent labels.
- The pivot detector uses strict comparison on both sides. Continuous OHLC candles share the prior close/open, creating equal adjacent extrema. This can suppress valid turning points. Regression needed for a rightmost plateau pivot with a full confirmation delay.
- The painter contains only RSI; MACD is a text statistic, and divergence strings are not drawn. Confirmed rendering gaps.
- The canvas is at least nine pixels per observation and initially wider than the phone. Right-edge labels and recent candles can be outside the viewport. Support/resistance have no labels and there is no observation axis.
- Chart end is stored in State and is not advanced when the same mutable DemoEngine receives a tick. Replay needs a distinct pinned mode so fixing follow mode cannot leak future observations into a historical decision.
- Wave candidate absence is explained only below the large chart and replay controls. Empty states must be visible before the chart.

No runtime change or new acceptance result at this checkpoint. The intended preview uses a new application identifier so Build 14 and its private data remain installed. No storage schema change is planned.

## Pending

Controlled synthetic chart fixtures; causal pivot regression; RSI/MACD/divergence layers; primary/alternate and honest empty-state display; viewport controls; widget/golden/integration checks; isolated deterministic exit/reversal exercises; CI verification and a separately installable APK. No phone test of a new build has occurred.
