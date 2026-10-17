# Contract evidence — batches57 onward

Current acceptance:57/58/59 all passed their existing source CI gates.59 has1629 Python,997 visible Flutter,61 JVM,23 chart/6 Golden, PostgreSQL22/6/10/5/28/4/21 and20 Compose. Original source-bound ZIPs were verified by GitHub SHA256 and CRC. The initial pending statements below are historical; they do not indicate an outstanding57–59 gate. Server capture and its phone report are wired; Direct standalone metadata and complete adjusted/historical qualification remain open.

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

## Batch58: optional capture after protective processing

The opt-in observed worker now wires metadata through the same durable rate budget, authentication latch, backoff and lease fence as OPRA quote capture. `OAT_OPTION_METADATA_APPROVAL=read_only_approved` is additionally required; both existing worker/data approvals remain necessary. Compose passes the new setting through with an empty disabled default. No deployed setting was changed.

One optional metadata request runs only after every selected account's financial cycle. It alternates contract terms and Greek snapshots with a persisted cursor reserved atomically before HTTP. Failures and uncertain replies stay charged, no implicit retries occur, and one remaining budget slot is kept for subsequent quotes. An optional error cannot retroactively veto an already-committed protective cycle; it yields a fixed diagnostic. A partial/unrequested snapshot or clock regression never becomes evidence. This is bounded capture, not a promise of complete per-tick coverage or continuous actual-market operation. Metadata never changes v1/v2 admission.

10 new tests;77 affected and1628 full Python passed locally with no failures/skips. Batch58 source CI pending. Batch57 source971d7f820ac6a222acff6de9eb7b5881036fb85d accepted in backend39019672153 and security39019672164; original ZIP SHA256/CRC verified. Raw results confirm1618 Python, PostgreSQL22/6/10/5/28/4/21 and20 Compose. Metadata/UI still grants no Greek timestamp or settlement permission. Phone presentation follows separately.

## Batch59: phone report with independent validation

The server account screen now opens a GET-only contract evidence view with a visible retry/error footer. Dart verifies account/version/hash, the exact hashed report payload (including exponent-form Greek numbers), original account bindings, OCC identity, terms hash, exact decimal multiplier/deliverables, receipt age, adjusted/delayed conditions and Greek numeric domains. It independently reconstructs the complete locked qualification result. Missing, tampered or stale account replies never display qualified values; no API response can grant entry or settlement. The receipt time and unavailable Greek calculation time are separately labeled. A newer account version requires refreshing the parent account state; retry does not write.

Eight fixtures are generated from actual isolated SQL journals and are explicitly synthetic.27 new Dart/parser/widget cases cover all eight plus forged authority/source/binding/delivery/time and360px RTL light/dark GET-only retry. One Python fixture reproduction case and44 affected Python cases passed locally. Flutter acceptance remains pending the existing source CI; no local Flutter success or APK build is claimed.

## Batch65: provider network deadline implemented

The shared provider lifecycle now limits DNS wait and total connection/header/body time, pins public literal IPs with original-host TLS, and rejects late results without multiplying pending DNS lookups. General reads retain8 seconds; metadata retains4 seconds as total budgets.30 new tests and1695 full Python tests pass locally; source CI is pending. See `PROVIDER_DEADLINES_20261017.md`. Direct standalone metadata, full adjusted/historical qualification and qualified Greek timing remain separate open work.
