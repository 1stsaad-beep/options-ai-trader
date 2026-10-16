# Observed virtual runtime — batch25

This is an isolated server ledger and persistent worker, not a device-account import or a replacement for Demo. No deployment or real provider connection was performed. Accounts start stopped. `alpaca` new-entry admission remains `CONTRACT_ELIGIBILITY_UNVERIFIED`: the required qualified deliverable/Greek metadata adapter is not yet implemented. Fixture execution uses explicitly labeled standard 100-share assumptions. This batch does not close R09/R12 or declare production readiness.

## Implemented contract

`observed-paper-ledger-v1` records exact original commands, capture timestamps, qualified option quotes, original optional OHLCV, strategy version, conservative execution policy, reasons, fees and balance transitions. Independent accounts never write the synthetic `accounts/orders/fills` ledger. Partial entry cancels its unfilled remainder; partial owned closure retains its remaining intent across stop, restart and provider failure. No price fallback or external order transport exists.

The shared strategy and option-execution contracts govern fixture fills. Risk checks use the adverse actual fill cost, cash, allocation, contract/position limits and realized/open daily losses. Delivered stock blocks additional risk pending explicit review. Stops, take profit, trailing, partial profit, confirmed structural reversal, prior-session intraday exits, maximum holding and expiry protection do not require optional analysis. A partial-profit close upgrades to a full protective exit when needed. An opposite position cannot open in the same cycle as closure, and the next cycle must re-evaluate current data and risk. Augmentation, Greek/deliverable eligibility, scenario identity exits and full performance reporting remain follow-up work.

Manual paper settlement reuses the shared Call/Put/stock/worthless-expiry arithmetic. It requires a stopped account, explicit receipt and no unresolved close intent; cancellation of that intent is an explicit stopped-only control. Receipt IDs and request keys are unique per account. Effective receipts cannot precede the inventory's last movement. No broker settlement or writer assignment is inferred.

## Durability and ownership

Migration10 adds separate observed-paper accounts, immutable events, sealed segment indexes, lease and request-budget state. It preserves previous schemas and balances. Each transaction commits the financial state, original inputs, hash chain, request identity and segment index together. Sealed segments roll at256 events or4MiB; each event is bounded to1MiB. This is logical segmentation in the durable database, not separate physical archive files.

Full reconciliation streams event rows, including a named server-side PostgreSQL cursor, and recomputes original transitions, facts, state hashes and segment chains. A corrupt account is blocked for offline review. A verified in-process snapshot avoids replaying unchanged history; historical checkpoints and incremental cross-process replay remain work for very long histories. Financial recovery still depends on its original event inputs. Device optional-archive isolation is a separate unfinished requirement.

Worker ownership has a30-second lease and generation fence. Capture occurs outside the DB transaction; the owner, expiry and expected account version are checked again at mutation. API stop/configuration during capture discards that stale result. Duplicate request keys return the original receipt; changed input under the same key is rejected. Event pages have explicit cursors and a4MiB payload ceiling. Hashes detect corruption, not deliberate replacement by a DB administrator.

## Read-only data boundary and controls

Owner-authenticated endpoints are under `/api/observed-paper/accounts`: create, state, control, events and reconcile. Controls accept configuration, enable/stop, owned close/cancel and explicit settlement. HTTP callers cannot inject a cycle, price or worker lease. Current API ownership is a single personal bearer token, consistent with the existing server; it is not multi-tenant authorization. A dedicated mobile control/replay UI is not yet connected.

The optional process is `python -m app.observed_paper_worker`; `--once`, `--healthcheck` and stopped-only `--reset-auth-lock` are explicit operator controls. Without BOTH `OAT_OBSERVED_PAPER_APPROVAL=virtual_only_approved` and `OAT_ALPACA_DATA_APPROVAL=read_only_approved`, no credential file is read and no network provider is created. The default Basic adapter is unchanged. Explicit observed transport permits only fixed-host GET market-data routes and OPRA quotes; it cannot send a broker order. No redirect/proxy or indicative fallback. The durable request budget,401/403 latch and429/5xx backoff survive restarts. Optional bars yield the last available request slot to quote protection.

The source uses completed minute IEX bars with explicit partial coverage, and whole-cent OPRA quotes with original timestamps/display sizes. Partial pagination or malformed optional bars do not invent a source window. The engine requires fresh captures and quotes. Demand is bounded to10 underlying symbols/30 option contracts; larger simultaneous demand is blocked, not silently treated as complete. The Compose profile is opt-in, nonroot/read-only, with a dedicated explicit secret mount; do not share its credentials with another provider process without a common budget coordinator.

Official API references inspected2026-10-16: https://docs.alpaca.markets/us/reference/optionlatestquotes and https://docs.alpaca.markets/us/reference/stockbars . OPRA entitlement is external evidence still unavailable; no subscription was purchased.

## Acceptance status

New tests cover deterministic Call/Put fills, absent optional analysis, partial/repeated quotes, stop/restart, stale captures, generation fencing, concurrent connections, CAS cancellation, risk bounds, SQL immutability, atomic rollback, corrupted snapshots, segment rotation, delivery settlement, duplicate receipts, API injection denial, disabled CLI, read-only probes, request budgets and auth/backoff recovery. The same two-connection contract runs locally on SQLite and in CI on disposable PostgreSQL. Backup acceptance now restores pending observed closes and their exact original events/segments. Compose acceptance includes the disabled worker, restart and API-independent heartbeat.

Local full suite result and source-bound CI are recorded in the newest resume report. Pending CI must not be presented as a pass. No user phone, actual OPRA data, deployed Oracle service, final independent review or new APK is claimed.
