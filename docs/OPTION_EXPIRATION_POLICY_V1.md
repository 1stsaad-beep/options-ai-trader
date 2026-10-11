# Optional US close-only expiration protection

Verified 2026-10-11. Policy `us-close-only-expiry-v1` is an offline simulation
guard for accounts using `us_equity_options_2026_2027`. It is not contract
qualification, exercise, assignment, delivery, settlement, or a broker receipt.

## Behavior

The fixture catalog still names Friday expiries. For these nominal dates, the
guard derives the last modeled regular session on or before that date from the
existing 2026–2027 calendar. A holiday Friday therefore uses Thursday; the
nominal contract identifier is retained. This is not proof that a real contract
with that identifier exists. New York dates and IANA DST determine the cutoff,
including the published 13:00 early closes. Product-specific late closes and
unscheduled interruptions remain unsupported.

| State | New exposure | Owned closing intent | New simulated close fill |
| --- | --- | --- | --- |
| Before final session date | Existing independent gates | Existing ownership gates | Existing session/ownership gates |
| Final session date, before close | Blocked, including pending BUY remainder | Permitted | Only while session is open and all other gates pass |
| At or after confirmed cutoff | Blocked | No new executable close | Blocked |
| Calendar unavailable | Blocked | Preserved for independent protection | Blocked |

After cutoff, the owned quantity, original cost basis, position policy and
direction lock remain. Pending orders for that contract expire. There is no
fabricated sell fill, premium writeoff, shares, cash settlement or flat state.
A deduplicated `MOCK_EXPIRY_REVIEW_REQUIRED` audit event records the unresolved
exposure. Unknown calendar data can also require review without asserting that
expiration actually occurred. `status.expiration_reviews` exposes the cause.

Reconciliation verifies the internal ledger; it cannot establish the economic
outcome of expiration. Fresh synthetic marks cannot make this valuation
complete: unrealized P&L and net liquidation stay unavailable. The independent
open-loss guard blocks additional risk even if an expiry worker tick was
missed. This also blocks shared/global new-risk admission when its valuation
depends on the unresolved account. Valid owned closes of other contracts remain
possible; accounts and their ledgers are not merged.

Partial close receipts preserve the remaining quantity, allocated basis and
fees. Existing order/fill receipts remain idempotently retrievable after cutoff
and restart. A reversal cannot infer flatness from an expired contract or open
the opposite direction. Switching session policy is refused while positions,
active orders, or active lifecycle intents remain, preventing a switch to the
legacy writeoff policy from bypassing the unresolved exposure.

Automation uses days to the modeled last session for expiration protection.
Independent protective reasons still survive optional analysis failure. It
does not manufacture a price or executable close after the cutoff. Decisions
save the applicable expiration facts with the existing session facts.

The default `synthetic_24x7` policy is deliberately unchanged: its historical
same-day prohibition and explicit premium-loss writeoff remain artificial.
The local mobile Demo still uses that policy; this backend-only change does not
change build 13 or establish parity with the phone engine.

## Verification

- Isolated saved source `3a72226143944dd8985f14d82cc14afc45acbb8f`: **22 failures**
  on the new integration regressions; current source: **22 passes**.
- Pure cutoff/calendar policy: **46 passes**, including DST, holidays, early
  closes, unsupported years and unavailable calendar data.
- Combined targeted execution suite: **214 passes** before the final two
  integration cases were added. Full local Python gate: **850 passes**, no
  failures/errors/skips. One existing Starlette deprecation warning.
- Real local HTTP/worker/process-restart smoke passed. Evidence is in
  `docs/evidence/expiry-20261011/`.
- PostgreSQL acceptance script now has 22 checks, including two-connection
  concurrent review deduplication. A SQLite dry run is explicitly labeled and
  is not evidence of PostgreSQL execution; cloud acceptance is recorded
  separately after publication.

An initial compatibility test expected the existing market-session rejection
message for an unsupported year. Restoring that diagnostic ordering fixed the
assertion without weakening either gate. No failed attempt is counted as a pass.

## Official source review and unimplemented risks

Reviewed public documentation on 2026-10-11:

- [OCC equity option specifications](https://www.theocc.com/clearance-and-settlement/clearing/equity-options-product-specifications):
  standard equity contracts generally represent 100 shares, with adjusted
  exceptions; American exercise and physical delivery create obligations that
  premium-only arithmetic does not model.
- [OIC weekly options FAQ](https://www.optionseducation.org/referencelibrary/faq/weekly-options):
  holiday-Friday weekly expiry moves earlier. Actual listed contract terms,
  not a synthetic nominal Friday, must determine any broker implementation.
- [OIC exercise FAQ](https://www.optionseducation.org/referencelibrary/faq/options-exercise):
  exercise processing and account instructions matter; a modeled close is not
  an exercise instruction or settlement event.
- [IBKR exercise and delivery actions](https://www.interactivebrokers.com/en/trading/delivery-exercise-actions.php):
  broker deadlines and risk actions are product/account dependent. Published
  exercise-request deadlines are not used here as trading-session cutoffs.

The application supports long options only. Exercise/delivery/funding risk for
long positions and assignment risk associated with short options are distinct;
neither real lifecycle is implemented. No automatic exercise threshold,
broker liquidation, assignment, dividend rule, adjusted multiplier, stock
delivery, settlement reconciliation, or manual review-resolution API is
claimed. Retained unresolved exposure intentionally requires future explicit,
auditable resolution; users must not edit the ledger or downgrade policy to
erase it. IBKR transport remains disabled and was never contacted.

## Cloud acceptance after publication

At source `381eec3cf2ed1454764d75ab51683dcf3634e453`, run
[38126076027](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38126076027)
passed: 850 Python, 22 real PostgreSQL V1 checks, 10 backup/restore and 12 Compose
checks. Security run
[38126076071](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38126076071)
also passed. Raw downloaded evidence is versioned with the local results.
