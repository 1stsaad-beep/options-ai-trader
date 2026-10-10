# V0.4 independent safety review

This review covers local synthetic trading only. It is not a certification for real money, external broker connectivity, or production deployment.

## Scope and controls

- Existing durable order IDs, payload fingerprints, fill IDs, account-scoped inventory and risk admission remain in place.
- Reserved automatic entry/exit request-key prefixes cannot be submitted through ordinary service/API calls. This fixes an independently identified path where a manually supplied prefix could make an accepted manual order appear to belong to automation. Internal automatic requests require the bound transaction context.
- Malformed account configuration or creation-audit JSON is treated as an untrusted ledger, preventing fills and persisting the account lock instead of silently retaining trusted state.
- Duplicate HTTP delivery or a lost response may retrieve a durable receipt. It must never create a second order or repeat a fill.
- Paper/mock validation now applies to new SELL_TO_CLOSE fills as well as BUY fills. An already accepted closing order cannot continue filling after changing to analysis or shadow mode. This was a gap found in the V0.3 service review.
- Opening orders retain per-account, linked-account and global exposure/loss checks. Closing orders cannot reserve or sell inventory owned by another account, and concurrent reservations cannot exceed owned quantity.
- A cycle holds one transaction and the repository risk lock. Its quote snapshots must be unique, fresh, have exact positive cent prices, match the contract and satisfy the spread limit. Automatic entries are limited to one per account/symbol/day.
- Unknown or stale account state requires explicit reconciliation. A process restart preserves receipts and inventory but invalidates account trust until reconciled.
- Live and external broker connections remain disabled. Generic Analysis Adapter has no enabled network execution path. AI text is explanatory and has no order or risk authority.

## Actual independent test evidence

The command `python -m pytest -q backend/tests/test_adversarial_v04.py` completed with **36 passed, 0 failed, 0 skipped** on 2026-10-10 (0.20 seconds for the recorded run). These are a subset of the complete backend suite, not additional tests to add to its total. JUnit evidence is saved as `docs/evidence/v04-independent-security-tests.xml`.

Covered scenarios:

- Paper-to-shadow/analysis changes invalidate all new fills, including owned closes.
- Concurrent duplicate order requests and fill deliveries apply exactly once.
- Concurrent close reservations cannot exceed inventory; cross-account fill-ID collisions do not transfer inventory.
- Close receipt replay after disconnection does not repeat P&L; process restart preserves partial receipts and requires explicit reconciliation.
- Concurrent automatic cycles, including two separate SQLite repository connections, create one entry and apply one fill for the same quote observation.
- Automatic execution requires explicit per-account opt-in; disabling it pauses pending automatic fills.
- Stale/future/ambiguous option quotes, quote feed exceptions and market outages cannot fill pending entries.
- Disconnects, stale account snapshots and inconsistent position costs block automatic execution. Automation does not restore an unknown account to trusted state.
- Stop-loss cancels the remaining unfilled entry before closing only owned quantity. Replayed observations do not repeat exits.
- Partial take-profit exits can cancel/reprice the remaining owned quantity after prices change, without overselling.
- Emergency stop blocks entries while allowing trusted owned exits with valid quotes.
- Account-scoped expiry does not settle another account, refuses unknown state, and applies a write-off once without fabricating an exchange sale.
- Invalid configuration, Live/IBKR mode attempts, boolean integer coercions, and out-of-range limits do not modify safe defaults.
- User-supplied reserved automatic key prefixes are rejected, and malformed durable config/audit JSON cannot advance a pending fill and marks the account untrusted.

All fills use synthetic fixtures. No test used a real account, real option quote, broker credential or external order connection.

## Remaining limits

- A synthetic durable ledger is not a real broker reconciliation protocol. No external order transport, exchange acknowledgement, credentials, market data entitlements or account connectivity has been exercised.
- Automatic exit rules require a valid account state and usable option quote. They cannot promise an exit during outages, stale data, zero bids or excessive spreads. An accepted limit sell may remain unfilled, and a reconnect requires operator reconciliation.
- Account snapshots remain subject to a freshness timeout and market observations require explicit synthetic refresh; an unattended indefinitely running demonstration requires these deliberate lifecycle operations.
- Expiry settlement is a conservative synthetic premium write-off. It does not model exercise, assignment, underlying delivery or actual settlement value.
- Loss controls use realized P&L and committed option premium. This is not a complete mark-to-market portfolio risk model.
- Local database corruption detection checks internal consistency and recorded provenance; it is not tamper-proof storage against an attacker able to rewrite the entire database.
- The API bearer token protects the personal local service, not separate users or tenants. Production internet exposure is outside this review.
- Security dependency audit results from V0.3 are historical unless a fresh audit is expressly documented in the V0.4 test report.
