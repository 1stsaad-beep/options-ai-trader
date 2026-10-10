# V1.0 architecture and execution risk review

Review date: 2026-10-10. Baseline: `ccd1d2c181de3968e9042ce7c1435571c1f3301a` (V0.5). This is the pre-change source review; later V1 implementation and test reports must identify which findings were resolved. It is not a claim that new tests were executed or that broker behavior was validated.

## Scope and evidence

Reviewed the exact baseline `backend/app/service.py`, `automation.py`, `repository.py`, `migrations.py`, `adapters.py`, `main.py`, `worker.py`, `engines.py`, `backtest.py`, the V0.5 review/security/test reports, architecture document, and existing execution, automation, database and adversarial test names. The reports record 203 Python and 65 Flutter tests plus PostgreSQL/Android/unsigned iOS CI; these are historical V0.5 results, not V1 results. No broker, external analysis project, credential or paid provider was accessed for this review.

## Preserve these boundaries

- Preserve the modular monolith, integer-cent order ledger, additive migrations and current public service boundary. Extend the existing project instead of replacing its execution implementation.
- Every order, position, idempotency lookup and mutation must carry an explicit account ID. A shared feed or connection does not share ownership or risk authorization.
- `Repository.transaction()` serializes writers with SQLite `BEGIN IMMEDIATE` or PostgreSQL transaction advisory lock `82741639`; keep this conservative global lock while changing cross-account risk. The Python RLock alone is insufficient across processes.
- `TradingService` remains the single authority for manual, automatic, reversal and scaling admission. Quantitative engines return proposals. Narrative AI can explain a stored result but cannot supply a command or configuration override.
- Preserve exact account-bound request fingerprints, unique `(account_id, request_key)`, globally unique fill IDs, cumulative fill replay and owned-close reservations. A retry returning an existing receipt is safe even while state is unknown; it must never create a new submission.
- Keep trusted-state, snapshot age, catalog, market freshness, mode, stop and ledger checks. A trust score cannot replace any hard gate.
- Keep local Flutter Demo physically independent from `TraderApi`, backend credentials and broker classes. Synthetic data must remain explicitly labeled. Backend worker operation must remain independent of an open phone.
- `IBKRAdapter` and `GenericAnalysisAdapter` remain disabled and contain no external I/O. Passing a configuration flag is not authorization to connect.

## Prioritized findings before implementation

| Priority | Finding in baseline | Required V1 behavior |
|---|---|---|
| P0 | `_submit()` allows manual/API BUY of the opposite right while a same-symbol position or entry is active. `automation._cycle()` only has a local symbol exclusion. | One account/symbol direction gate in service admission and pre-fill validation. Opposing owned inventory or unresolved entry reservation blocks a new direction, across expiries and strikes. Worker/UI checks alone are insufficient. |
| P0 | `max_contracts` checks individual order quantity, not cumulative owned and pending BUY quantities. Multiple legal-sized orders can exceed an intended account cap. | Define separate account aggregate contract, per-order contract, position count and maximum contract premium limits. Count remaining pending quantity exactly once. Recheck before each fill/addition. |
| P0 | No persisted reversal or scaling lifecycle exists. Ordinary order keys alone do not express a complete reversal dependency. | Durable intents with unique account/symbol/generation keys; all phase transitions and side effects share the risk transaction. Unknown or incomplete close state cannot progress to opposite entry. |
| P0 before higher risk settings | Backend allocation/trade/daily limits are hard capped at 30/2/3%; global cap is hard-coded 30/3. Execution risk considers premium without commissions and realized P&L only. | Separate configurable allocation, maximum premium at risk and daily loss policies. Include fees and pending reservations. Add explicit zero-allocation behavior and higher-risk acknowledgement before raising caps. Never let a raised UI percentage bypass balance or direction checks. |
| P1 | Backend has initial capital plus realized P&L but no broker cash, buying power, fresh mark-to-market or daily start-of-day equity authority. Open losses do not hit the daily backend gate. | Retain explicit synthetic semantics. For this Mock release use validated marks and a documented conservative loss policy; missing marks block new entries. Real Net Liquidation/Buying Power remains an unverified adapter requirement. |
| P1 | Audit and shadow rows are append-only by convention and are not complete order decision snapshots. An accepted order audit stores only an ID. | Add immutable, versioned decision snapshots recorded atomically at decision time, linked to orders and intent phases. Record original inputs, rule results and rejection reasons; never reconstruct historical causes with AI. |
| P1 | `stop()` cancels every active order, including owned closing orders. Automatic exits can be recreated later, but an existing safe close intent is lost. | Cancel remaining BUY intents/reservations, block new entries, and preserve or deliberately reschedule owned-close intent under a stated emergency policy. Never liquidate unowned quantity. |
| P1 | Generic global `expire()` does not require fresh account state in the same way as account-specific expiry; it validates ledger only. | Make expiry mutation trust policy consistent and test global and account-scoped paths. A synthetic write-off is not a broker settlement or exercise action. |
| P1 | Worker is independent of Flutter, but fixture observations expire at 60 seconds and account snapshots at 120 seconds; unknown accounts require explicit reconciliation. | Report continuous operation honestly. An explicit synthetic fixture provider can publish fresh mock observations; it must never silently repair disconnected account truth. Add worker heartbeat/stale-state visibility and restart tests. |
| P2 | One bearer token administers all personal accounts. It is not a multi-user authorization model. | Keep the personal-owner deployment scope explicit. Do not claim tenant isolation or grant separate users access without an ownership/authentication design. |
| P2 | PostgreSQL serializes all risk operations globally and reconstructs ledgers repeatedly. | Retain correctness first; measure scale before optimizing. Future row locks must include linked groups in deterministic order and protect global exposure atomically. |

## Reversal contract

Use a persisted state machine such as `REQUESTED -> CANCEL_OLD_ENTRIES -> CLOSE_OWNED -> WAIT_FLAT -> RECONCILE -> REVALIDATE -> OPEN_OPPOSITE -> COMPLETE`, with `BLOCKED`, `EXPIRED` and `CANCELLED` terminal/paused outcomes. The names may differ; the conditions must not.

1. Capture the confirmed quantitative reversal proposal, observation time, expiry, old direction, target direction, rule version and required exit condition. A divergence annotation alone is not admission.
2. Deduplicate intent by account, symbol and proposal/generation. Repeated UI calls, worker cycles and lost replies return the same intent and receipts.
3. Cancel old BUY remainders. In Mock, the durable cancellation is authoritative. A future broker would require acknowledged cancel states; local cancellation cannot imply external cancellation.
4. Reserve at most owned quantity for `SELL_TO_CLOSE`. Do not duplicate reservations when a close already exists; use its cumulative fills. Persist partial progress across restarts.
5. Remain blocked until every old position is flat, every old-direction entry is terminal, all owned close receipts are settled, and ledger/account state is fresh and reconciled. Never use a timer or a local optimistic acknowledgement as proof of flatness.
6. Recompute the target signal from currently available completed data. Recheck its expiry, activation/invalidation levels, contract quality, fees, account/global risk, stop state and strategy settings.
7. Submit at most one target entry with a deterministic intent-linked key. If its reply is lost, reconcile by key; never mint a new key to force another submission.
8. If interrupted after the old close, remaining flat is a valid safe outcome. No requirement to reopen may override a gate.

Changing account mode, risk limits, watchlist, strategy or emergency state mid-reversal must be respected at the next phase. A preexisting intent does not grandfather an unsafe entry. Retrying an identical old receipt is permitted for visibility without advancing execution.

## Scaling contract

Scaling is an addition to an existing same-direction long position, never averaging a loss by default. Persist the parent position generation, addition count, last confirmed addition time, rule and intent key. Admission requires a fresh profitable mark according to the explicit strategy rule, valid signal, same-direction ownership, cooldown, enabled account setting and remaining addition budget. Count both completed and unresolved additions so a lost response cannot release the budget.

Recompute total owned premium, fee-inclusive pending cost, available simulated cash, contract count, account allocation, daily loss and linked/global limits before reserving and before each fill. Fixed or decreasing quantity must remain positive integer contracts; a rounded zero means no addition. Opposite/reversal/close intent takes precedence. Keep future Live scaling disabled regardless of Demo configuration.

## Decision memory and replay

An additive snapshot schema should contain immutable ID, account ID, source/mode, strategy/rule version, decision timestamp, latest available observation timestamp, input digest, indicator/scenario facts, activation/invalidation/expiry, selected contract and quote, risk/config snapshot, action/rejection, and causally related intent/order IDs. Execution events add actual price, fee, quantity, cumulative quantity and explicit reason without editing the original snapshot.

Snapshot update/delete guards protect accidental application mutation, not a malicious database administrator. Hashes are useful integrity evidence but are not a digital signature or independent audit authority. Replay reads stored observations and events. Later narrative comments must be separate and labeled as retrospective. They cannot replace entry/exit reasons recorded at the time.

For Elliott/harmonic/divergence pivots distinguish `pivot_time` from `confirmed_at`; only confirmed knowledge at or before the decision cutoff can affect historical decisions. Appending later bars may create a new scenario version or invalidation event, but must not rewrite an earlier emitted snapshot. Replay must use prefix data and no future labels, even when a chart displays the original location of a subsequently confirmed pivot.

## Risk and data contracts

- Allocation 0% means no new exposure; 100% does not imply unlimited leverage, contracts or risk. Per-trade risk and daily loss remain independent values.
- Do not net a positive unrealized gain against a loss merely to reopen a closed daily gate under a conservative policy. Publish the exact simulated day boundary and denominator.
- Increasing approved caps needs a durable acknowledgement tied to the exact effective configuration. Booleans, NaN, negative percentages, unknown fields and malformed saved state fail closed.
- Existing closing ownership must remain manageable after entry limits are lowered; an entry max-contract cap should not silently strand owned inventory. Split a close if a separate execution size cap applies.
- A stale/missing quote cannot justify an invented execution price. Existing limit close intent may remain pending during data loss; automated quote-based close fills require fresh trusted data. A stop is a trigger rule, not a guaranteed fill price.
- Contract identity must include source, instrument/currency/exchange, unique contract identity when supplied, multiplier, right, strike and expiry. Synthetic fixture validation cannot be presented as IBKR qualification.
- Broker integration requires independent order intent, dispatch attempt, uncertain acknowledgement, broker order identity, execution receipts and reconciliation states. Do not reuse the single-store Mock acknowledgement model as proof of real execution correctness.

## Required regression gates

| Area | Evidence to run |
|---|---|
| Direction | Manual/API/automatic opposing entries; different strike/expiry; pending and partial old entry; same symbol in another account allowed; simultaneous Call/Put attempts across DB connections. |
| Reversal | Full close followed by reconciliation and new signal; stale/cancelled signal remains flat; partial close, close failure, disconnect, lost response at each phase, repeated cycles and restart. |
| Scaling | Disabled default, profitable-only, addition cap, cooldown, decreasing quantity, pending-addition risk reservation, lost reply, same-tick duplicate, risk reduction and emergency precedence. |
| Risk | Zero/100 allocation, acknowledged elevated settings, cumulative contract cap, fee-inclusive cash/exposure, unrealized loss, linked state unknown, independent accounts and concurrent group admissions. |
| Decisions | Snapshot cannot be edited/deleted through app; order references exact snapshot; rejected opportunity recorded; future observations cannot change previous snapshot digest or intent payload. |
| Exits | Stop/profit/trailing/partial profit/time/swing/expiry triggers; fresh later execution observation; missing data waits; cumulative sell quantity never exceeds ownership. |
| Recovery | Additive migrations on saved V0.5 ledger, restart distrust preserved, replay receipts unchanged, backup/restore into isolated DB, PostgreSQL multi-connection races. |
| UI and isolation | Four or more independent local accounts, offline Demo network-denial test, settings persist, charts/replay prefix cutoff, no mode or data transfer into broker/backend. |

No test in this review was newly executed. V1 release evidence must report actual commands, commit, pass/fail/skip counts, platform, build/signature state and unrun checks. Historical V0.5 success is not V1 validation or financial readiness.
