# Contract evidence — batches57 onward

Continued from verified remote HEAD `f7f65c058075c55a6ffd7c2b3b203cba5a94c9fe` on `recovery/v1.0-20261011`. No repeat of batches1–56. Baseline1585 Python passed locally.

## Batch57: immutable source journal and constrained transport

Additive migration12 preserves every existing financial v1/v2 event and lot. The separate metadata journal stores bounded original contract/snapshot members, their receipt time, per-contract sequence/hash chain and exact account-version/event-hash bindings. SQL UPDATE/DELETE guards protect originals. Reads verify the complete chain and its head, normalize again, validate the original ledger binding and publish only account-bound data. A later observation for another account cannot hide a prior bound origin. A new capture cannot backdate a legacy lot.

Owner-authenticated `GET /api/observed-paper/accounts/{account}/contract-evidence` has no write, network, injection or permission-granting behavior. Values-only Greeks retain a null independent provider timestamp; current terms keep a null effective time. Missing, stale, delayed, adjusted and legacy-lot evidence remains ineligible. Raw provider bodies do not leave this API.

`AlpacaMetadataTransport` supports only fixed HTTPS GET routes: one exact OCC contract on `paper-api.alpaca.markets/v2/options/contracts/{symbol}`, or <=30 distinct symbols with explicit OPRA at `data.alpaca.markets/v1beta1/options/snapshots`. No account/order route, redirect, host override, implicit retry or SDK. Response bytes, duplicate keys, nonfinite constants and JSON parsing failures are bounded/rejected. Construction is offline; runtime opt-in/capture integration follows in the next batch. This transport was exercised only with offline sockets/mocks, never real credentials.

Official references checked2026-10-17:
- https://docs.alpaca.markets/us/reference/get-option-contract-symbol_or_id
- https://docs.alpaca.markets/us/reference/optionsnapshots

`updated_since` applies to quote/trade times. It does not prove Greek calculation time. A structural hash detects inconsistent evidence; it is not a provider signature or protection against a fully privileged database administrator.

## Verification

Batch57:33 new cases,92 targeted tests and1618 full Python tests passed, zero failures/skips (one existing Starlette warning). Migration11→12, active-WAL SQLite backup/restore, rollback on head-write failure, ownership loss, stale/future times, altered originals/head/binding/tail, read-only authenticated API and fixed-host transport were exercised. The first targeted run had one test comparing reports from a real clock; the fixture clock was then explicitly installed in the API test. No production guard changed to resolve that harness error.

Existing PostgreSQL acceptance adds3 cross-connection metadata checks and one actual backup/restore check. These are **pending source CI**, not claimed PostgreSQL successes here. Flutter/native is unchanged in57. Worker transport/capture and phone display follow; complete R09 and stage-one closure remain open.
