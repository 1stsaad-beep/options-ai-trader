# Batch B4: Paper option orders through admission with explicit confirmation (2026-10-17)

Base: `work/positions-b3` @ `e37d93b600a41772b0536093cac39b36a8601b50`. Branch `work/paper-orders-b4`.
The broker host allowlist is unchanged (`paper-api.alpaca.markets`, `sim-api.tradestation.com` + `signin.tradestation.com`, the user's IBKR gateway).
The Live lock is unchanged.

## Flow

Ticket (OCC contract, buy-to-open or sell-to-close, quantity, limit, IBKR conid) -> **Review** (fresh balances, positions, quote and
journal, then admission) -> **Send…** -> **explicit confirmation dialog** -> `submit` fetches everything again and **re-runs admission**
(the review is valid for 60 s) -> INTENT is appended and read back -> exactly one send -> the outcome is appended.

## Admission (`mobile/lib/brokers/broker_order_admission.dart`), checked in order

Paper-only (`LiveTradingGate.requirePaper`, Paper-verified snapshot) -> account state ≤ 60 s old -> no unresolved order (INTENT/UNKNOWN) ->
OCC identity, quantity and limit bounds (IBKR conid) -> `paperExpiry` (buy needs ACTIVE; close allowed while CLOSE_ONLY) -> `paperSession`
(buy needs the entry window; close allowed until the session close) -> qualified quote with the same thresholds as `OptionQuote.valid` (≤ 30 s,
bid > 0, ask ≥ bid, spread ≤ 20%, displayed size ≥ quantity) -> limit within [bid, ask].
**Close:** owned long quantity minus pending closes ≥ quantity. Entry caps never block a close. Short option rows -> review required.
**Open:** same-underlying opposite-direction lock (holdings and non-terminal orders) -> cost (`qty × limit × 100 + qty × 70¢`, conservative-v2 fee)
≤ cash and buying power -> trade risk 5% of equity -> allocation 30% -> max 10 contracts -> max 4 positions -> open loss < 3% daily budget.
These are the same field names and defaults as `paperRiskReason`; pending orders reserve risk until reconciled.

## Quotes

Alpaca: the existing Direct OPRA session (`DirectAlpaca.quote`), because paper-api has no option quotes and the allowlist was not widened. Without it the order fails closed (`QUOTE_UNAVAILABLE`).
TradeStation: `GET /v3/marketdata/quotes/{symbol}` on SIM. There is no quote timestamp, so freshness uses the receipt time (`timeSource: RECEIVED`, recorded in the INTENT).
IBKR: `GET /iserver/marketdata/snapshot?conids=…&fields=84,86,88,85` with `_updated`.

## Journal (`broker_order_journal.dart`)

Append-only per-account event list in secure storage (`seq` checked, read back after each write, max 2000 events; when full, new orders are refused and nothing is dropped).
States: INTENT -> OPEN (ACK) | REJECTED (definitive 4xx/429) | NOT_PLACED (TLS / host refusal before send) | UNKNOWN (timeout, network, 5xx, malformed reply; blocks the account until B5 reconciles) |
CONFIRMATION_REQUIRED (an IBKR precautionary reply: not placed and never auto-confirmed). A corrupt journal is neither overwritten nor sent from.

## Files

New: `broker_options.dart` (OCC/TradeStation symbols, exact cents, quote qualification), `broker_order_admission.dart`, `broker_order_journal.dart`,
`broker_order_service.dart`, `broker_order_ticket.dart` (ticket, review and confirm UI with Arabic messages).
Changed: `broker_adapter.dart` (`optionQuote`, clock passthrough), adapters (quotes, IBKR position conid), `broker_models.dart` (`contractId`),
`broker_portfolio_screen.dart` ("أمر Paper" button, long-press on a position to close, order list), `test/broker_portfolio_test.dart` (fake adapter).
Tests: `test/broker_orders_test.dart`, 18 tests (symbols and cents, every admission gate, service for all three brokers via `MockClient`,
INTENT-before-send, UNKNOWN blocking, definitive reject, expired review, failed revalidation sends nothing, no Direct quote fails closed, corrupt journal, widget confirm/cancel).

## Results

`flutter analyze` clean. `flutter test` **1064 passed** (B3 had 1046, plus 18). Debug APK built (`apk-debug-sha256-size.txt`; local copy `/workspace/tools/apk/options-ai-trader-b4-debug.apk`).
Secret scan: 1229 files, 0 findings. No dependency changes. Evidence: `docs/evidence/paper-orders-b4-20261017/`.

## Limits

No real Paper order was sent. Same-day realized P/L is not available consistently across the three APIs, so the daily cap uses open losses only.
TradeStation quote freshness relies on receipt time. IBKR needs a user-supplied conid (no secdef lookup) and confirmation replies are not answered.
Orders are not automated; each one needs a manual review and confirmation. Order status and fills are matched in B5.
