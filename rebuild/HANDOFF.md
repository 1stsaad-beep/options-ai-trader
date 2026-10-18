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

## 9. Batch A — interactive per-symbol chart (2026-10-18, versionCode 2)

Open: account → tap a watchlist symbol (or an open position) → chart.

* **Same bars as the engines**: `AppController.chartBars` makes the exact engine
  call `adapter.bars(symbol, timeframe, limit: 300)` (Alpaca `/v2/stocks/{sym}/bars`,
  `feed=iex`; simulator → `SyntheticMarket`). `ChartAnalysis.compute` runs on those
  bars in an isolate; every overlay is in bar indices of that list, so it aligns.
* Timeframes 5m/15m/1h/1d (the account's analysis timeframe is marked `•`).
* Pan (drag), pinch zoom around the focal bar, double-tap → latest bar,
  long-press crosshair with O/H/L/C/V, % change, score at that bar and any
  account decision on that bar; tap hides it. Chart is always LTR.
* Layers (toggle sheet): EMA20/50/200 (off by default), support/resistance
  (clustered confirmed swings), trend lines (last two swing highs/lows),
  ZigZag + confirmed fractal pivots + dashed provisional last leg, classical
  (double top/bottom + neckline, H&S + sloping neckline, triangle boundaries,
  20-bar range box), harmonic (XABCD, XB/BD, PRZ box), Elliott wave labels,
  divergence (swing-to-swing line with RSI values), targets/invalidation of the
  signals that count in the score, account trade markers (hollow triangle =
  order submitted, filled = fill; blue buy / orange sell), composite score
  sub-pane (causal: score as known at each bar, re-analysed per prefix).
* Engine geometry comes from the engines themselves (`EngineSignal.geometry`),
  not re-derived in the UI; geometry is not journalled and does not affect
  decisions (all previous core tests unchanged).
* Performance: only visible bars are painted (culling for candles, series,
  segments, points, markers); candle paths cached (`CandleCache`) and the
  crosshair is a separate painter, so moving it never rebuilds candles;
  candles sit in a `RepaintBoundary`.
* Tests: core `chart_test.dart` (10), app `chart_viewport_test.dart` (6),
  `chart_screen_test.dart` (6), `chart_account_test.dart` (1).

Known gaps: engines only report patterns that are currently actionable
(recent D/break), so harmonic/classical/Elliott overlays are often empty —
that is the engines' behaviour, shown honestly. Exactly 300 bars per
timeframe (no lazy loading of older history). Alpaca may include the
still-forming last bar (same for the engine). Times are shown in device local
time. Not yet tested on the phone.

## 10. Batch B — market hours, completed bars, NY day, account lock (versionCode 3)

* **Calendar** (`trader_core/lib/src/market/market_calendar.dart`):
  America/New_York from the US DST rule (exact for 2007+, no tz database needed;
  tested across both 2026 transitions). Official NYSE holidays and 13:00 early
  closes for 2026–2028 (nyse.com, fetched 2026-10-18); other years by NYSE rules
  (tested to reproduce the official table). Phases: pre 04:00–09:30, regular
  09:30–16:00 (13:00 early close), post until 20:00 (17:00) ET; next open/close.
* **Broker clock**: `AlpacaAdapter` implements `MarketClockSource` (`GET /v2/clock`
  on the paper host). `MarketHoursGate` = calendar AND broker clock (both must say
  open); broker error → calendar alone. `/v2/calendar` is not used (the offline
  table + clock cover it).
* **Order policy**: outside regular hours a cycle does no analysis and places **no
  orders of any kind** — entries, exits and scale-ins (US equity options trade in
  RTH only; Alpaca would reject/queue them). Following existing orders/fills and
  cancelling stale ones still happens. One journal note per closed period.
  `_submit` re-checks the calendar right before `placeOrder` (last-line guard).
  The simulator (synthetic 24/7 market) has no gate.
* **Completed bars only**: engines drop the still-forming last bar
  (`MarketCalendar.completedBars`: intraday end = start + length, capped at the
  session close; a daily bar completes at its session's close). The chart draws
  the forming bar hollow/faded, outside the analysis, and the readout says so.
* **Daily-loss limit**: trading day = New York date (`yyyy-mm-dd`). On the first
  cycle after updating, the old UTC key differs, so the day start equity is
  re-taken once.
* **Per-account lock** (`AccountLock`): refresh, runCycle and testConnection on one
  account run strictly one after another. Adapter creation is shared by concurrent
  callers (chart loads do not take the lock). A deadlock in the first version of
  that sharing (whenComplete waiting on its own future) was caught by tests.
* **UI**: market status card (accounts list + account overview): phase, holiday /
  weekend reason, early close, next open/close in ET and the phone's time, source
  (broker clock or NYSE calendar). Chart axis and readout times in New York (ET).
* Tests: core `market_test.dart` (19); app `batch_b_app_test.dart` (6) and chart
  updates. core 75/75, app 21/21.

## 11. Batch C — background service, activity log, safety, positions (versionCode 4)

* **Background execution** (`app/lib/services/background_service.dart`):
  Android foreground service via `flutter_foreground_task` 11.0.3, type
  `specialUse` (not `dataSync`: Android 15 caps dataSync at 6 h per 24 h), with
  `PROPERTY_SPECIAL_USE_FGS_SUBTYPE`, `stopWithTask="true"`, wake lock + Wi-Fi lock,
  no auto-start on boot. Started/stopped only by the user (accounts screen switch);
  the choice is persisted (`oat_v2/app.json`) and re-applied on the next launch.
  Design: cycles still run in the **main isolate** (accounts, secrets, locks live
  there); the service keeps the process/CPU alive, shows the persistent
  notification ("N accounts enabled • last cycle HH:MM ET • market state") and
  sends a tick every 60 s. `runAllCycles` skips if a pass is running or the last
  one was < 30 s ago, so the in-app timer and the ticks never double-run.
  Notification buttons: **إيقاف طارئ** (kill switch) and **إيقاف الخدمة**.
  Battery: the card shows whether the app is battery-optimised and opens the
  system list (`openIgnoreBatteryOptimizationSettings`) — no
  `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` permission, the user decides.
  Notification permission (Android 13+) is requested when the user turns it on.
* **Limits (documented in the app too)**: no server — the phone is the host.
  Swiping the app from Recents, force-stop, reboot or an OEM task killer
  (Xiaomi/Huawei/Samsung…) stops trading until the app is opened again. Doze can
  delay cycles/network by minutes despite the wake lock. Ticks are ~60 s, not exact.
  Real-device validation of screen-off behaviour is still to be done by the user.
* **Kill switch**: one tap (AppBar hand icon on accounts and account screens, or
  the notification button) pauses **all** accounts: no cycle runs, nothing is sent
  (entries *and* exits); positions stay as they are. Persisted; red banner while on;
  resume asks for confirmation.
* **Engine safety** (`trading_engine.dart`, `AccountSettings`):
  `maxOrdersPerDay` (default 10) caps **opening** orders (entries + scale-ins) per
  New York day; exits are never capped. `symbolCooldownMinutes` (default 60): no
  new entry on a symbol for N minutes after any entry or exit on it (this also
  delays a Call→Put flip by the cooldown). `maxOpenPositions`, daily-loss limit and
  the Call/Put direction lock are unchanged. Counters/timestamps persist in
  `AccountState` (`ordersToday`, `ordersDay`, `lastTrade`).
* **Cycle records** (`trading/cycle_record.dart`): every cycle stores market phase
  and summary, per-symbol score/bias and the final decision + Arabic reason (even
  when the journal rate-limits repeated "skip" notes), orders sent, fill count,
  errors, note and duration; last 600 kept. Journal entries carry `cycle`.
* **UI**: account screen tabs — نظرة عامة / المراكز / سجل الدورات / سجل القرارات /
  الأداء. Activity log filters: all, trade decisions, with orders, errors, market
  closed, per symbol. Positions: unrealised P/L ($ and %, from mid or bid), Greeks
  (Δ Γ Θ ν + IV from Alpaca snapshots when present; the simulator gives Δ only),
  entry reason/score/time (ET), underlying invalidation and target, chart link.
  Risk & safety card on the overview (kill switch, risk %, positions x/y, opening
  orders today x/y, cooldown, daily loss, stop, allowed rights, direction lock,
  live locked). Settings gained the two new limits.
* **13:15 ET nuance**: on early-close days equity options stop at 13:00 ET, but
  broad index options (SPX/XSP/NDX/RUT…) and some ETF options (SPY/QQQ/IWM on
  some venues) trade until 13:15 ET (like 16:00 vs 16:15). The app keeps **13:00
  for every symbol** — conservative, never sends after a venue closes; documented
  in `market_calendar.dart`.
* Live trading still compiled out (`OAT_ENABLE_LIVE` not set).
* Tests: core `safety_test.dart` (6: settings JSON/validate, cooldown, opening-order
  cap + NY reset + exits allowed, cycle record content + JSON, bound, Alpaca
  greeks); legacy engine tests pin cooldown 0. App `batch_c_app_test.dart` (8:
  kill switch, background start/stop/tick/gap/restore, filters, log screen,
  position card, risk card + kill switch toggle, detail tabs). core 81/81, app 29/29.
* Next (Batch D candidates): device validation of the service; per-account pause;
  notification on fills/errors; export of the activity log.
* Build: `rebuild-v2-debug-4` (private builds repo), versionCode 4 / 2.0.0-dev.4,
  162,610,015 bytes, SHA-256
  `a59ec4791a06fc0f944050bb6a80ed6b1bbf2f90baa0ea39077c82ca7744967c` (verified by
  re-download), signer SHA-256 `dde693a8…6720` (box debug cert, updates in place).

## 12. Batch D — reports, exports, notifications, settings, real-bar tests (versionCode 5)

* **Reports** (`trader_core/lib/src/trading/report.dart`, app `screens/reports_tab.dart`,
  tab "التقارير"): realized P/L (after fees), unrealized P/L of open positions at the
  last quotes, total return, max drawdown (% and $, from the per-cycle equity curve),
  trades, **wins / losses / breakevens** (a zero-P/L trade is no longer counted as a
  loss; win rate = wins ÷ all trades), profit factor, averages, fees; daily and
  weekly breakdown by **New York exit date** (week = Monday NY); per-engine
  contribution (each trade is credited to every engine that supported its entry,
  so rows overlap — stated in the UI); closed trades with entry/exit reasons.
  Engine attribution flows TrackedOrder → PositionMeta → TradeRecord (`eng` key,
  optional; trades closed before dev.5 show as "untagged").
* **Exports** (`services/report_exporter.dart`): CSV (RFC 4180, UTF-8 BOM so Arabic
  opens correctly in spreadsheets) — `<name>_<NYdate>_trades.csv`,
  `_daily_weekly.csv`; or one `_report.json`. Activity log (current filter):
  `_activity.csv` (one row per symbol per cycle) or `_activity.json`. Files are
  written to the app's temp dir and handed to the Android share sheet (share_plus
  12.0.x — 13.x needs flutter_secure_storage 10+, deliberately not upgraded to
  avoid touching the stored keys).
* **Local notifications** (`services/notifier.dart`, flutter_local_notifications
  22.3.2; core-library desugaring enabled in `android/app/build.gradle.kts`):
  fills, errors (same account+text at most once per 30 min), kill switch on/off,
  market open/close (observed transition while the app/service runs). Each kind is
  a switch in the "الإشعارات" card (defaults: market off, others on), persisted in
  `app.json`. On-device only, no push server.
* **Settings**: sections حالة الحساب / المخاطرة / حدود الأمان / الدخول / الأوزان /
  اختيار العقد / الخروج / التعزيز; every number shows an Arabic explanation, the
  allowed range (`AccountSettings.allowedRanges`, same numbers `validate()` enforces
  — tested) and a conservative suggestion. Reset-to-defaults (confirm; not saved
  until "حفظ"; watchlist and keys untouched). **Per-account pause**
  (`pauseNewEntries`, also a switch on the overview): no entries or scale-ins, exits
  and stops keep running — distinct from the account's on/off switch (no cycles)
  and the global kill switch (nothing sent).
* **Real historical bars** (`trader_core/test/fixtures/*.csv`, `real_bars_test.dart`):
  AAPL and SPY, daily (2 years, 501 bars) and hourly (60 days, RTH only, 420 bars),
  fetched 2026-10-18 from the public Yahoo Finance chart API **without any key**
  (Stooq now requires a JS challenge). Tests: data sanity; all six engines over
  rolling windows (finite score ≤ 100, strengths 0..1, signals known inside the
  window, deterministic); full engine replays (hourly and daily, Alpaca-like
  adapter so the NYSE gate and completed-bar rule apply) asserting: engines never
  see the forming bar, Call/Put lock, max open positions, max opening orders per NY
  day, no errors, every closed trade has entry/exit reasons and engines, report
  totals reconcile. Options in the replay are Black-Scholes-priced on the real
  underlying (no public options history without keys) — **behaviour/safety tests,
  not a backtest**. Replay results with default-ish settings (informational, all
  negative): AAPL h1 3 trades −$3,534; SPY h1 1 trade −$440; AAPL d1 5 trades
  −$1,122; SPY d1 14 trades −$17,931 (max DD 18.3% on $100k, risk 2%/trade).
* **CI**: workflow "rebuild (v2 core + app)" was green for every Batch A–C push
  (latest before this batch: run 39120616763, success). Only a stale comment was
  fixed.
* Tests: core 94/94 (report_test 5, real_bars_test 6, safety_test +2); app 37/37
  (batch_d_app_test 8: fill notification + engine attribution, error rate-limit /
  toggles / persistence, exports (BOM, JSON, share), reports tab, activity export,
  settings explanations/reset/pause/validation, live screen locked, unrealized P/L).
* Build: `rebuild-v2-debug-5`, versionCode 5 / 2.0.0-dev.5, 189,512,450 bytes,
  SHA-256 `86f56f6b2b37d04190efd884b185659778be1b12990631aeb223e363548c9511`
  (verified by re-download), signer `dde693a8…6720`.

### What remains (honest list after Batch D)

1. **Device validation** by the user: foreground service with screen off for a full
   session, OEM battery killers, notification permission flow, share sheet, and the
   update-in-place from debug-4 (keys/state preserved).
2. **Strategy quality is unproven.** The real-bar replays lose money with the
   current defaults; before any thought of live, run Paper for weeks, review the
   per-engine report, and tune/disable weak engines. No backtest on real options
   prices exists (needs an options-history source; Alpaca historical options bars
   need the user's keys — could be added as an opt-in in-app backtest).
3. Live trading remains compiled out (`OAT_ENABLE_LIVE`); enabling it would need a
   deliberate release build, a release keystore and a separate review.
4. Release signing / Play-style release build (debug builds only so far; APK ~190 MB
   because debug includes all ABIs and JIT).
5. Market open/close notifications only fire while the app or service is running;
   the transition is not tested with an injected clock.
6. Background run stops on swipe-from-recents/reboot (by design, `stopWithTask`);
   no auto-start on boot.
7. TradeStation and IBKR adapters are unit-tested with fakes only (no real
   accounts tested); Alpaca is the only broker exercised by the user.
8. iOS: CI can build an unsigned archive on demand; no background execution on iOS.
9. Dependency updates (flutter_secure_storage 10 migration, share_plus 13) deferred.
