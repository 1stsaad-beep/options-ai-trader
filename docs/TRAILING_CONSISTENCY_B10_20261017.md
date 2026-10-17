# Batch B10 — consistent trailing stop / protective exit across modes (2026-10-17)

Branch: `work/trailing-b10` (stacked on B9). Paper/Demo only; the Live lock is unchanged.

## Differences found before the change
| Mode | Order | Arming | Note |
|---|---|---|---|
| Market Paper (phone) | stop > take > trail | the peak must exceed the entry cost | raw bid or net liquidation (conservative-v2) |
| Demo (phone) | **trail > take > stop** (each condition overwrote the previous one) | the peak must exceed the cost | inconsistent with the others |
| Broker Paper (B4–B9) | no protective exit at all | — | — |
| Server `observed_paper.py` / `automation.py` | stop > take > trail | **no arming** (trailing works as a second stop from the entry peak) | server is out of scope for this phase; not modified, documented only |

## Unified rule (`mobile/lib/protective_exit.dart`, `oat-protective-exit-v1`)
- Exact integer comparisons on whole-position values in one valuation basis.
- STOP_LOSS when value×100 ≤ basis×(100−stop).
- TAKE_PROFIT when value×100 ≥ basis×(100+take).
- TRAILING_STOP when trail>0, the peak > basis (armed only after a gain), and value×100 ≤ peak×(100−trail).
- Priority: stop > take > trail. The peak includes the current observation, so a new high never triggers.

## Usage
- **Market Paper:** replaces the three checks with the same function in both the raw and costed paths. A test shows it matches the previous behaviour: 20,000 random cases for the raw path, excluding exact floating-point boundaries, where the integer version is more accurate; 5,000 cases against `PaperReturn` for the costed path.
- **Demo:** the same function. **Behaviour change:** when stop and trail both trigger, the reason is now «وقف خسارة» instead of «وقف متحرك». A test shows a real Demo path where both triggered. Older Demo records are not rewritten.
- **Broker Paper:** `BrokerProtectiveTracker`.
  - It derives basis = market value − unrealized P/L from the broker and tracks the peak per lot (contract/quantity/basis) in secure storage.
  - It is bounded at 500 lots; only the oldest closed lots are dropped beyond that.
  - The portfolio screen shows the policy (editable, default 20/40/15 like Market Paper, trail 0 = off) and a "⚠ اقتراح إغلاق" warning on the position.
  - **No automatic sending:** the close goes through the B4 ticket with review and confirmation.

## Evidence
`docs/evidence/trailing-b10-20261017/`: analyze clean, **1099** tests (B9: 1093, +6 in `test/protective_exit_test.dart`), debug APK, secret scan 0, SHA256SUMS. A B5 widget test was adjusted (ensureVisible) because the screen now has an extra row.

## OPEN
- Server trailing has no arming and stays different (the server is not being developed this phase; see B14).
- Broker Paper monitoring runs only while the screen is open (no background service or server).
- The broker market value is the broker's own mark, not necessarily the bid; partial-exit (partial) and time/expiry rules are not unified in this batch.
