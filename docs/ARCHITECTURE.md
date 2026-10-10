# Modular monolith — V0.4 mock automation architecture

This is an independent application. One personal owner bearer token administers multiple isolated mock trading accounts. It is not a multi-user SaaS authorization system.

## Modules

| Boundary | Implementation | Authority |
| --- | --- | --- |
| Presentation | Flutter RTL, FastAPI strict request models | Explicit account ID in every mutation |
| Analysis | Pure quantitative engines, optional narrative callback | Candidate signals only |
| Market | Synthetic OHLCV fixtures, mock catalogue | No real quotes or entitlements |
| Risk/execution | TradingService + transaction repository | Atomic admission, reservations, partial fills |
| Persistence | SQLite test/demo, psycopg PostgreSQL configuration | Durable orders, fills, positions, daily P&L, audits, shadow |
| Supervisor | Persistent account/global stop and fixed global limits | Cannot be overridden by AI or client |
| Worker | Independent process, periodic synthetic scans and opt-in automatic Mock cycles | Same quantitative, ownership and risk gates as manual Mock operations |
| External adapters | IBKR and Generic Analysis Adapter disabled boundaries | All methods fail without network operations |

All operations run under database transactions. SQLite uses BEGIN IMMEDIATE; PostgreSQL uses a fixed transaction advisory lock to serialize account/global risk decisions. This conservative global serialization favors correctness over throughput. PostgreSQL runtime/concurrency is unverified in this environment. Versioned additive migrations preserve V0.2/V0.3 ledgers. V0.4 adds backward-compatible configuration defaults without changing durable table layout.

Financial execution amounts are integer USD cents, standard multiplier100. Account-specific identity is part of order idempotency and position keys. Sell-to-close admission reserves held contracts; partial fills consume that reservation. No naked or multi-leg submissions exist. Market fixtures may be shared, but execution records never use an implicit selected account.

## Invariants

- Paper/mock only; no live adapter, no credentials collection, no real account connection.
- Configured modes that request live fail at startup; account configurations reject nonmock brokers.
- Fresh account snapshots require age in [0,120] seconds; reopening the repository locks account state.
- Reconciliation replays sequenced fills and expiry events and validates positions, total realized and daily P&L; detected mismatches lock the account and audit failure. It never resends an order.
- Idempotency keys uniquely identify an exact account-bound payload. Changed payloads reject. Fill IDs also reject changed payloads.
- Buy maximum premium risk <=2%, account allocation <=30%, daily realized loss limit <=3%, global exposure <=30% and global daily loss <=3%. Settings may tighten these limits.
- Risk denominator is initial mock equity plus realized P&L; no mark-to-market/net liquidation feed exists. Pending buy costs and held cost basis count toward exposure. Commission is modeled in backtesting, not in the mock execution ledger.
- Hard stop cancels pending remainders and blocks new BUY orders. Trusted owned closing sells remain allowed; the stop never resets automatically. Opt-in automation may manage owned positions using fresh quotes after a stop.
- Expiry writes off premium conservatively and cancels pending contracts on the UTC synthetic expiry day. No exercise, assignment or intrinsic settlement is simulated.
- Watchlists begin inactive. Activating only succeeds for explicit mock fixture symbols. This is not proof of real broker qualification or market permissions.
- A language model may supply untrusted explanatory text only; no output is interpreted as an order or risk configuration.

## Process independence

API and worker may run in separate processes against one database. The worker continues when Flutter closes. Default worker mode records opportunities and missed reasons. `--execute-mock` enables automatic cycles for explicitly opted-in paper/mock accounts. The authenticated per-account automation/run route runs the same cycle. Config, analysis, option selection, reconciliation, risk, fills and exits share the database transaction lock.

## Intentional limits

No real US exchange calendar, session boundaries, DST treatment, overnight management, real-time portfolio stops, broker fills, options chain connection, external AI provider, secret manager, TLS termination, operator re-enable policy, HA or immutable audit signing. Audit is append-only by application convention; a database administrator can alter it. A fail-closed reconciliation detects selected ledger inconsistencies, not arbitrary malicious database alteration.

See ENGINES.md for deterministic signal and historical simulator methodology. See AUTOMATION_V04.md for entry/exit policies, REVIEW_V04_AR.md for scope, and TEST_REPORT_V04_AR.md for executed evidence.
