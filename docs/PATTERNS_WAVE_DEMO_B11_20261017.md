# Batch B11 — wave/pattern consistency in Demo, plus more classic patterns (2026-10-17)

Branch: `work/patterns-b11` (stacked on B10). Research/Shadow only; no orders and no execution authority.

## Consistency
- Before: the Demo labs (Wave/Classic/Harmonic) used the original Demo convention: 4/2 pivots with plateaus, and their own harmonics with a 0.04 tolerance. Direct and the server use strict 3/1 pivots (`confirmed-geometry-v1` / `confirmed-wave-pivots-3-1-v1`).
- Now: the Demo labs default to **market rules 3/1**:
  - The wave journal uses `ChartWaveJournal(strictMarket: true)`.
  - Pivots come from `MarketGeometry.candlePivots` (identical to `confirmedPivots`, with a parity test on the same OHLC).
  - Harmonics use `MarketGeometry.harmonics` with tolerance 0.03.
  - Classics use `MarketGeometry.classicDrawings`.
- A «قواعد Demo القديمة 4/2» chip keeps the legacy convention available. Saved journals keep their own contract (v1/v2), so no history is rewritten or relabeled.
- The display fixtures (abc/bat…) were built for the 4/2 convention; their widget test now selects the legacy convention explicitly.

## New patterns (`mobile/lib/extended_patterns.dart`, `extended-classic-v1`)
- **Patterns detected:** triple top/bottom (neckline confirmed by a close beyond it), ascending/descending triangle, rectangle, and rising/falling wedge (least-squares slopes with three highs and three lows separated).
- **Inputs:** confirmed alternating pivots only. A test shows the pattern doesn't appear before its last pivot is confirmed.
- **Overlaps:** overlapping interpretations (e.g. rectangle and triple bottom) are both shown.
- **Server parity unchanged:** the canonical server set (`classicPatterns`) is untouched; the server fixture tests still pass.
- **Where they're drawn:** the Classic lab in Direct and Demo, with upper/lower boundaries or a neckline.

## Evidence
`docs/evidence/patterns-b11-20261017/`: analyze clean, **1105** tests (B10: 1099, +6 in `test/extended_patterns_test.dart`), golden tests unchanged, debug APK, secret scan 0, SHA256SUMS.

## OPEN
- The new patterns have no Python counterpart on the server (server is out of scope this phase), so they are phone-only.
- Thresholds (flatness 1.5%, peak equality 2%) are initial, uncalibrated values.
- Not covered: flags/pennants, cup and handle, channels; full ranking parity between Demo scenarios and the server.
