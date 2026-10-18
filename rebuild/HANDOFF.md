# HANDOFF — Options AI Trader v2 (rebuild/hybrid-engines-20261018)

> اقرأ هذا الملف أولًا. Read this first. Written for the next developer/bot.

## 0. Status in one paragraph

A clean v2 was built in `rebuild/` on branch `rebuild/hybrid-engines-20261018`,
branched from `recovery/v1.0-20261011` @ `50966b5`. The old v1 code (`backend/`,
`mobile/`, `docs/`, history) is **untouched** and still available for reference.
v2 = a pure-Dart core package (`rebuild/trader_core`) + a Flutter RTL app
(`rebuild/app`). **IMPORTANT: none of this code has been compiled or run yet** —
the authoring session had no Dart/Flutter SDK and no package-registry access.
The first job of the next session is to run the toolchain and fix whatever the
compiler/tests report (see §5). Fixture values used by the tests were checked
with a Python port of the same algorithms, so test expectations are believed
correct; syntax/type errors are the main risk.

## 1. Why a rebuild

v1 (70 batches) drifted into server operations (alert receivers, health
probes) while the core requirements stayed unmet: no broker order adapters
(IBKR permanently disabled, no TradeStation, Alpaca data-only), one global
API key instead of per-account keys, no iOS key storage, and the decision logic
and opposite lock implemented three separate times (server / phone / demo).
v2 keeps the good ideas (causal confirmed pivots, XABCD geometry, strict lock,
journal-with-reason) and reorganises them around one engine and one adapter
interface.

## 2. Layout

```
rebuild/
  HANDOFF.md            ← this file
  docs/ENGINES.md       ← every engine's rules, thresholds, scoring, lock
  trader_core/          ← pure Dart (no Flutter) — runs on phone or a server
    lib/src/models.dart                 money in cents, OCC symbols, orders, positions
    lib/src/options_math.dart           Black–Scholes (simulator pricing, delta fallback)
    lib/src/brokers/
      broker_adapter.dart               BrokerAdapter + MarketDataSource interfaces,
                                        credential field specs, HttpTransport port
      live_guard.dart                   the ONLY live gate (compile flag + approval)
      broker_registry.dart              BrokerKind → adapter factory
      synthetic_market.dart             deterministic offline market (simulator)
      simulator_broker.dart             internal paper broker (fake money)
      alpaca_adapter.dart               Alpaca paper/live REST (reference adapter)
      tradestation_adapter.dart         TradeStation v3 SIM/live (unverified)
      ibkr_adapter.dart                 IBKR Client Portal gateway (unverified)
      json_util.dart                    defensive JSON parsing for adapters
    lib/src/analysis/                   indicators, pivots, 6 engines, Analyzer
    lib/src/trading/
      account.dart                      AccountSettings (all risk knobs) + AccountProfile
      account_state.dart                per-account persistent engine memory
      direction_lock.dart               Call/Put opposite-direction lock
      risk.dart                         sizing, contract selection, limit prices
      decision_engine.dart              exit / scale-in / entry rules
      trading_engine.dart               per-account cycle orchestration
      journal.dart                      decision journal, trades, performance, USD format
    test/                               unit + integration tests (simulator-driven)
  app/                                  Flutter app (Arabic RTL)
    lib/main.dart
    lib/services/                       secure keys, HTTP, JSON persistence, AppController
    lib/screens/                        accounts, add account, detail (overview/journal/
                                        performance), settings, live mode
    test/app_smoke_test.dart
.github/workflows/rebuild.yaml          CI for rebuild/ only (core tests, app tests,
                                        debug APK artifact, optional unsigned iOS)
```

Platform folders (`app/android`, `app/ios`) are **generated**, not committed:
`cd rebuild/app && flutter create --platforms=android,ios --org com.optionsaitrader --project-name options_ai_trader_app . && rm -f test/widget_test.dart`
(CI does exactly this). Commit them once you need native changes (see §6).

## 3. Requirement → implementation map

| Requirement | Where | State |
|---|---|---|
| Flutter Android+iOS, Arabic RTL | `app/lib/main.dart` (locale ar + RTL builder) | written, not compiled |
| Multi-broker, Adapter Pattern | `BrokerAdapter`, `BrokerRegistry.standard()` | done (4 adapters) |
| Alpaca | `alpaca_adapter.dart` | written from docs; unit-tested with fake HTTP |
| IBKR | `ibkr_adapter.dart` (Client Portal gateway, DU-account guard) | written, unverified |
| TradeStation | `tradestation_adapter.dart` (OAuth refresh, SIM base URL) | written, unverified |
| Multiple independent accounts per broker | `AccountProfile` + `AccountState` per id; one adapter instance per account; files `state_<id>.json` | done |
| Simple + secure local keys | `BrokerCredentialSpec` drives the form; `SecretStore` (Keychain / Keystore-backed) keyed by account id; never in JSON | done |
| Full Paper with fake money | `SimulatorBroker` (offline) and each broker's own paper endpoint | done |
| Live locked unless explicit approval | `LiveTradingGuard` (compile flag `OAT_ENABLE_LIVE`, default false) + typed `LiveApproval`; `LiveModeScreen` readiness list | locked |
| Calls/Puts only | `OptionRight` has only call/put; adapters ignore stocks/short options | done |
| Only user-chosen symbols per account | `AccountProfile.watchlist`; entries loop only over it | done |
| Opposite-direction lock | `DirectionLock` + double check + no same-cycle flip | done, tested |
| Fully automatic after enabling | `AppController` timer → `TradingEngine.runCycle` per enabled account | foreground only (§6) |
| Deterministic engines (Elliott, harmonic, divergence, classical, indicators) | `analysis/` — see `docs/ENGINES.md` | done |
| Decision engine with per-account settings | `DecisionEngine`, `AccountSettings` (35 knobs, validated) | done |
| Decision journal with reasons | `JournalEntry` for every entry/exit/skip/block/fill/error, analysis + settings snapshot attached | done |
| Performance reports | `PerformanceReport` (P&L, win rate, profit factor, drawdown, return) + Performance tab | done |
| Unit/integration tests | `trader_core/test/*` (≈45 tests), `app/test` smoke | written, not run |

## 4. Safety invariants (do not break)

1. **No live orders.** `LiveTradingGuard.buildAllowsLive` is a compile-time
   `bool.fromEnvironment('OAT_ENABLE_LIVE')`, default false. Every adapter calls
   `ensureAllowed` before `placeOrder`. IBKR additionally refuses non-`DU`
   accounts in paper mode. Do not add a runtime switch; changing this requires
   explicit user approval after paper readiness.
2. **Lock**: never open the opposite right while any quantity OR any working
   order exists on that underlying in the same account.
3. **No trade without a price**: exits/entries need a two-sided quote; missing
   quote → journal `skip`, never a guessed fill.
4. **Secrets** only in `SecretStore`. Profiles/state JSON must stay secret-free.
5. Accounts never share state; one adapter instance per account.

## 5. Next steps for the next bot (in order)

1. **Toolchain & green build** (blocking): in `rebuild/trader_core` run
   `dart pub get && dart analyze && dart test`; fix compile errors without
   weakening tests. Then `rebuild/app`: generate platforms (§2),
   `flutter pub get && flutter analyze && flutter test`. Push and make the
   `rebuild` workflow green; it uploads `app-debug.apk`.
2. **Adapter verification against real paper accounts** (user provides keys on
   their device; never paste keys into chat):
   * Alpaca: account with options level ≥ 2; check `/v2/account`, options
     snapshots feed (`indicative` vs `opra`), order round-trip, cancel.
   * TradeStation: SIM account; verify token refresh, symbol format
     `AAPL 261120C150`, order status codes mapping in `_order`, quotes batching.
   * IBKR: gateway login (paper), `/iserver/accounts` priming, confirmation
     replies, snapshot warm-up, conid resolution for options.
   Record findings in this file; fix mappings; add recorded-response tests.
3. **Background execution** (requirement "fully automatic"): the phone cannot
   guarantee continuous trading (iOS suspends apps; Android needs a foreground
   service). Recommended: run `trader_core` headless on a small server/VPS the
   user owns (a `bin/runner.dart` that loads the same account JSON + secrets from
   an encrypted file) with the phone as controller. Short-term Android option:
   foreground service (`flutter_foreground_task`) calling `runAllCycles`.
4. **Market calendar**: entries should run only in US regular hours; add a
   session calendar (holidays, early closes) and skip analysis/entries outside it.
   Daily-loss day boundary currently uses the UTC date — switch to New York date.
5. **Engine parity/quality**: add golden fixtures from real historical bars,
   walk-forward backtest runner over `SyntheticMarket`/recorded data, more classical
   patterns (flags, wedges, channels), multi-timeframe confirmation (e.g. require
   h1 trend for m15 entries).
6. **UI**: charts of equity curve and of the analysis (pivots, pattern points from
   `EngineSignal.details`), export journal (CSV/JSON), per-account notifications.
7. **Live readiness gate** (only after the user approves): ≥14 days paper, ≥20
   closed trades, zero unresolved errors (see `AppController.liveReadinessIssues`),
   then a build with `--dart-define=OAT_ENABLE_LIVE=true` — never by default.

## 6. Known limitations (honest list)

* Not compiled/run in the authoring session (no SDK, no registry, no push access).
* Automation runs only while the app is open (timer every minute).
* TradeStation and IBKR adapters follow public docs but are unverified.
* Simulator market is synthetic, 24/7, constant volatility; fills are conservative
  (buy at ask / sell at bid, no partial fills, fee $0.65/contract).
* Engine fees in `TradeRecord` approximate entry+exit commission per exited lot.
* Concurrent `refresh` and `runCycle` on the same account are not mutex-protected
  in `AppController` (engine itself refuses overlapping cycles).
* `liveReadinessIssues` treats any journal error ever recorded as blocking.

## 7. How to run locally

```sh
cd rebuild/trader_core && dart pub get && dart test
cd ../app && flutter create --platforms=android,ios --org com.optionsaitrader --project-name options_ai_trader_app . \
  && rm -f test/widget_test.dart && flutter pub get && flutter run
```
First run: add a "محاكي داخلي" account, add symbols (e.g. AAPL, MSFT), enable
automation, keep the app open; decisions appear in "سجل القرارات".

## 8. Session log — 2026-10-18 (first toolchain run, Grok Bot)

Toolchain: Flutter 3.47.7 / Dart 3.13.5, JDK 17, Android SDK 36.

* `trader_core`: `dart analyze` found 3 compile errors, fixed with no logic change
  (`harmonic_engine.dart` num→double on the fit score ×2; explicit unnamed
  `BrokerRegistry()` constructor). Result: analyze clean, **46/46 tests pass**.
* `app`: `flutter analyze` showed 3 infos only (2× deprecated `value:` →
  `initialValue:` on `DropdownButtonFormField`, 1× missing `const`); fixed.
  Result: analyze clean, **1/1 test passes** (smoke test only).
* `app/android` is now **committed** (generated by `flutter create --platforms=android`)
  because native settings were needed: debug `applicationIdSuffix ".rebuildv2"`
  (installs side by side with v1 `.papertest` builds), label "Options AI v2",
  `INTERNET` permission in the main manifest, Gradle heap 2 GB, no daemon.
  iOS is still generated by CI only.
* Debug APK built without `OAT_ENABLE_LIVE` → live is compiled out
  (`LiveTradingGuard.buildAllowsLive == false`). Paper only.
* Not yet done: real Alpaca paper verification on a phone, TradeStation/IBKR
  verification, background execution, market calendar (see §5).
