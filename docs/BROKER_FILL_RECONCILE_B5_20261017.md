# Batch B5 — reconciling broker order status and fills with the internal ledger (2026-10-17)

Branch: `work/fill-reconcile-b5` (stacked on B4 `09aa746`). Paper only; the Live lock is unchanged; the server allowlist is unchanged (read-only queries only).

## What was added
- `BrokerAdapter.orderStatus(...)` -> normalized `BrokerOrderLookup` for all three brokers:
  - Alpaca: `GET /v2/orders/{id}` or `GET /v2/orders:by_client_order_id`. A 404 on the client id is a "definitive not found". The returned client id is checked against ours (`ORDER_IDENTITY_MISMATCH`).
  - IBKR: `GET /iserver/account/orders`, matched by `order_ref`/`orderId`. Absence is never evidence of not being placed (the list is limited/session-dependent).
  - TradeStation SIM: `GET /v3/brokerage/accounts/{id}/orders`, by `OrderID`, or a single unlinked candidate matching symbol/side/quantity/limit; ambiguity = unresolved.
- `lib/brokers/broker_reconcile.dart` (`BrokerReconciler`):
  - Queries only non-terminal orders (INTENT/UNKNOWN/OPEN/PARTIALLY_FILLED).
  - **Appends** new `STATUS`/`FILL`/`RESOLVED` events through the append-only journal; earlier events are never modified or deleted (test: the original events stay byte-identical).
  - FILL carries the fill delta, the cumulative quantity, the broker average price and the raw status.
  - `NOT_PLACED` is set automatically only on Alpaca's definitive not-found **and** an intent age of at least 60 s.
  - Inconsistent data (fill decreasing or above the ordered quantity, identity mismatch) is reported and **not applied**.
  - Cross-check: positions below the journal's net fills -> `POSITION_BELOW_JOURNAL(held<net)`, reported only. Outside holdings are not flagged.
  - Manual resolution `USER_RESOLVED_NOT_PLACED`: only for unresolved orders, behind a confirmation dialog, recorded with its basis and a short note.
- UI: a «مطابقة الأوامر» button on the portfolio screen with a summary (checked/updated/fills/unresolved/discrepancies), plus a «حسم يدوي» button on unresolved orders.

## Evidence
`docs/evidence/fill-reconcile-b5-20261017/`: analyze clean, **1073** tests passed (B4: 1064, +9 in `test/broker_reconcile_test.dart`), debug APK built (sha256 in `apk-debug-sha256-size.txt`), secret scan 0 findings, SHA256SUMS.

## Not proven / still OPEN
- No real Paper connection; all broker responses are mocks based on the public documentation.
- Partial-fill price per execution (average only), commissions actually charged, and fills after a broker-side cancel are not checked against executions endpoints.
- A pending (open/partial) entry still reserves its full cost in admission and the position is counted too (conservative double counting, documented).
- No automatic periodic reconciliation (no background server, by design); reconciliation is manual from the screen.
- B6 (IBKR connectivity) and B7 (TradeStation OAuth) are deferred pending user decisions.
