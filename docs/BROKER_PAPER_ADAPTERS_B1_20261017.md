# Batch B1 — Paper broker adapters, multi-account, secure key entry (2026-10-17)

Base: `recovery/v1.0-20261011` @ `50966b5988096d1a753d8dc9722ef3e59e8a02e0` (verified with `git ls-remote`).
Local branch `work/broker-paper-b1`; **not pushed**. Direction comes from the user's approved design (Flutter, Android only;
Alpaca + IBKR + TradeStation with several accounts each; simple API-key entry with secure storage; Paper first; Live disabled
unless explicitly approved). This supersedes, for broker Paper connectivity only, the earlier boundary "no connected IBKR Paper /
external broker orders". Live stays locked. Accepted batches 1–70 and their records are untouched.

## Implemented (mobile only; no server component)

| File | Purpose |
|---|---|
| `mobile/lib/brokers/live_gate.dart` | `LiveTradingGate`: approval flag `OAT_LIVE_TRADING_APPROVED` is a compile-time define defaulting to `false`; `liveImplemented=false`, so `requirePaper()` rejects Live even if the flag is set. |
| `mobile/lib/brokers/broker_models.dart` | Broker kinds, per-broker field specs (secret vs non-secret), `BrokerAccount` (metadata only, refuses secret fields), redacted `BrokerCredentials`, normalized snapshot/position/order types, limit-only `PaperOrderRequest` validation. |
| `mobile/lib/brokers/broker_http.dart` | Bounded HTTPS transport: per-adapter host allowlist, HTTPS only, no userinfo, no redirects (credentials never forwarded), 15 s deadline, 2 MiB cap, bounded JSON, error codes HTTP_401/403/404/422/429, TIMEOUT, TLS_ERROR, NETWORK_ERROR, INVALID_DATA. Decimals kept as exact strings. |
| `mobile/lib/brokers/alpaca_paper.dart` | Alpaca Trading API on `paper-api.alpaca.markets` only: `/v2/account`, `/v2/positions`, limit `/v2/orders`. Keys entered in settings connect directly. |
| `mobile/lib/brokers/ibkr_paper.dart` | IBKR Client Portal Web API through a user-specified HTTPS gateway with a logged-in Paper session: `/iserver/auth/status`, `/portfolio/accounts`, `/portfolio/{id}/summary`, positions, limit orders by conid. Only `DU…` Paper account ids; the id must be in the gateway's account list; every call/order is bound to it; IBKR confirmation prompts are returned as `NEEDS_CONFIRMATION`, never auto-confirmed. |
| `mobile/lib/brokers/tradestation_sim.dart` | TradeStation v3 on `sim-api.tradestation.com` only. OAuth refresh-token exchange at `signin.tradestation.com/oauth/token`, 20-min access tokens cached, rotated refresh tokens persisted through a callback. Authorize-URL helper (`offline_access`). Accounts/balances/positions and limit `orderexecution/orders`. |
| `mobile/lib/brokers/broker_adapter.dart` | `BrokerAdapter` contract and `createPaperAdapter()` (Live and archived accounts refused before any I/O). |
| `mobile/lib/brokers/broker_store.dart` | `BrokerAccountRegistry` over `flutter_secure_storage` 11.2.0 (Android Keystore-wrapped AES-GCM, `resetOnError:false`, namespace `oat_brokers_v1`). Metadata index and secrets in separate entries; every write read back before success; up to 20 active accounts per broker; archive keeps the record; "forget keys" removes only that account's secret entry. Keystore/corruption errors are surfaced and nothing is wiped. |
| `mobile/lib/brokers/broker_accounts_screen.dart` | Arabic RTL settings screen: add account (broker, label, masked secret fields), list per broker, connection test with visible outcome, archive/forget keys. Live switch shown disabled. Opened from a new AppBar button in `main.dart`. |
| `mobile/pubspec.yaml` / `pubspec.lock` | Adds pinned `flutter_secure_storage: 11.2.0` (minSdk 24 Android plugin). |
| `mobile/test/broker_*_test.dart` | 29 new tests with `MockClient` (no network): Live lock, hosts/headers/redirect/timeout/malformed bodies, error mapping without credential leakage, IBKR DU/auth/membership/no auto-confirm, TradeStation refresh + rotation + SIM-only + account binding, registry multi-account/secret separation/readback/corruption/archive, widget flow. |

Paper order submission exists at adapter level only and is **not wired to the UI or automation** in this batch.

## Results on this box (Flutter 3.47.7 / Dart 3.13.5, same as CI pin)

- Baseline `50966b5`: `flutter analyze` no issues; `flutter test` **1011 passed**, 0 failed.
- B1: `flutter analyze` no issues; `flutter test` **1040 passed** (1011 + 29), 0 failed.
- `scripts/security_scan.py` (tracked tree incl. staged B1 files): 1187 files, 0 findings. `scripts/dart_dependency_audit.py`: 67 packages, no known advisories.
- Not run here: Android Gradle/APK build, JVM/native tests, emulator, Python/PostgreSQL (no Android SDK/JDK on the box; backend untouched).
- Logs and SHA-256: `docs/evidence/broker-b1-20261017/`. Test runs also write `classic-preview-*.png` into `mobile/`; these generated previews were not committed.

## Limits / open

- No real broker connection was made (no user keys used by the agent); behaviour against live Paper endpoints is unobserved.
- IBKR CP Gateway normally runs on localhost with a self-signed certificate; TLS validation is not bypassed, so a gateway needs a trusted certificate or a later on-device gateway/OAuth strategy. Cleartext is still refused.
- TradeStation in-app OAuth redirect (deep link + PKCE) is not implemented; the user pastes a refresh token.
- Existing Direct Alpaca market-data vault (`AlpacaVault.kt`, single key pair) is unchanged and separate from broker accounts; consolidation is later work.
- Android build of the new plugin not verified locally; `android-keystore`/`direct-alpaca` CI not run (nothing pushed).
