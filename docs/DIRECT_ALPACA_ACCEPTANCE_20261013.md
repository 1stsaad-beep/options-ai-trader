# Direct Alpaca Android Lab20 — acceptance and delivery

Date: 2026-10-13 UTC. Android release artifact verified; Keystore emulator gate is finishing. No real provider/physical-phone acceptance is claimed.

## Recovery and preservation

Recovered the actual remote branch `recovery/v1.0-20261011` at `67995126bd095e3e3bbbae2d74e9d19e0e2c8207`, not a historical report SHA. The workspace was initially empty. No unavailable edits from a previous workspace/session are claimed recovered. Reconstructed the exact Git tree and retained unseen entries; checked clean status before changes. No reset, force push, clean, branch deletion or user database deletion.

Existing Lab19 had the synthetic labs, account isolation, market-server client and optional server monitor; Backend/Market Runtime, PostgreSQL archive/restore and Oracle deployment paths remain in the repository. This batch adds a separate direct-phone path. It does not replace the server architecture, change the other Alpaca app, or migrate existing Demo accounts. No broker account was accessed, no user key was requested, no trading request was sent, and no service was purchased.

## Implemented scope

- Explicit on-device API key entry; obscured secret, cleared input after saving, no saved-secret read channel. Android Keystore AES-GCM key and encrypted file in noBackupFilesDir, screen capture protection on the direct page, disabled automatic APK data backup. A compromised device can still expose in-memory credentials; application policy does not reduce the provider permissions of a key.
- Fixed Alpaca market-data HTTPS/WebSocket hosts; GET-only allowlisted paths, no redirects, explicit IEX/SIP, authenticated subscription, per-feed entitlement rejection, bounded reconnect and rate-limit backoff. Connection limit 406 stops this app without disconnecting the other app. No order/create/replace/cancel route exists in the direct adapter.
- Real completed minute OHLCV, corrections without duplicate candles, UTC provenance and New York Regular/Extended filter with DST. Up to ten symbols and 1,000 in-memory bars per symbol. No synthetic fallback or gap fabrication. LIVE additionally requires authenticated connection, recent native receipt and a recently completed bar; the displayed value is minute close, not a tick quote.
- Wave, Classic, Harmonic, Indicator and AI Confluence use the existing local chart/indicator calculations with these OHLCV inputs. RSI, MACD and averages are available. Pattern interpretation remains research; AI Confluence is a local rule combination, not an LLM or a predictive-performance claim.
- Independent Market Paper namespace, virtual cash/accounts, per-account enablement, Call/Put signals, one direction per symbol, durable close-first confirmed-divergence reversal, risk caps including entry commissions, SL/TP/trailing and one optional addition. Persistence or quote failure blocks reversal. The shared ledger and coalesced initialization prevent a page reentry from overwriting pending account state.
- Stock data never prices an option. Only explicitly requested fresh, valid OPRA option quotes can price the separately labeled approximate research simulation; missing entitlement/invalid/stale/indicative quotes mean signals only. Ask/bid fills, standard multiplier 100 and simulated commissions are simplifications, not realistic execution, liquidity, exercise or assignment modeling.
- Optional nonexported foreground service: persistent Stop notification, price/RSI/MACD monitoring, bounded 30-minute session, no boot restart. Android/network/battery restrictions can end it earlier. It cannot run with the phone powered off. Market Paper pauses when Flutter leaves the foreground; existing virtual positions are not guaranteed protection in the background.

## Verified APK receipt

- APK source: `24e19611b38f8b43c41410d42b6b4ff98af96557`. Subsequent changes are CI/report/evidence only.
- [Successful Android run38411807924](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38411807924) and [downloadable artifact11822923266](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38411807924/artifacts/11822923266). Artifact ZIP SHA-256 `f17d9261bf7f2c1cc4e56bc529abb3a8a5008927c6c572bd6dd450cee1eea6e5`, CRC checked. Actions retention is14 days from upload (2026-10-13); download a copy promptly.
- APK `options-ai-trader-rc2-build20-preview.apk` (delivery copy `Options_AI_Trader_Lab20.apk`),57,135,549 bytes. SHA-256: `e06e4a8879c419b3f88c65456727187661a7fcbb6b9332186297edcfd1a586ee`. Recomputed after download and matched CI receipt; APK ZIP CRC also passed.
- Package `com.optionsaitrader.options_ai_trader.v1previewrc2b20`, version1.0.0/code20, label `Options AI Trader Lab 20`, minSDK24/targetSDK36; arm64-v8a, armeabi-v7a, x86_64. Release mode; `application-debuggable` absent from verified package data.
- APK Signature Scheme v2 verified by apksigner; one RSA2048 certificate, DN `C=US, O=Android, CN=Android Debug`. Certificate SHA-256: `333931a16179f986fc12f2ca8157b16b27945b1f47ad355e68152647116028b9`.
- **Ephemeral runner development signing key**, not a stable production distribution key. Private signing material was not published or recovered. Future same-package upgrade compatibility is not guaranteed. Lab19 is preserved by a separate application ID.
- Flutter3.47.7/Dart3.13.5. Source version metadata remains1.0.0-rc.2+20; CI deliberately emits preview APK versionName1.0.0/code20.
- The attempt to save a persistent attachment in this Work session failed because the file-saving helper could not obtain its authentication. The verified GitHub artifact and local delivery copy exist; persistent in-chat storage is not claimed.

## Accepted automated tests

| Gate | Actual result | Source / run |
| --- | --- | --- |
| Flutter analyze | No issues |24e1961 /38411807924 |
| Flutter tests |294 passed,0 skipped |24e1961 /38411807924; independent mock run38411807349 also passed |
| Reviewed chart Goldens |6 passed |24e1961 /38411807924 |
| Native HTTP/WS JVM mocks |11 passed,0 errors/failures/skips |24e1961 /38411807924 |
| GET-only Alpaca policy |42 checks passed, no network |24e1961 /38411807924 |
| Existing server monitor policy |30 checks passed |24e1961 /38411807924 |
| Backend Python |1055 passed,0 failures/errors/skips |c3e03a3 /38407423803; backend unchanged afterward |
| Actual disposable PostgreSQL |22 existing +6 journal +8 runtime passed |c3e03a3 /38407423803 |
| Actual PostgreSQL backup/restore |16 passed |c3e03a3 /38407423803 |
| Compose smoke |17 checks passed |c3e03a3 /38407423803 |
| Source/history patterns |806 text files,105 commits,1314 historical blobs;0 matches |24e1961 /38411807925 |
| Known dependency advisories |24 Python,43 Pub,90 resolved Maven package/version entries;0 advisories |24e1961 /38411807925 and38411807924 |

Zero findings is the result of these scoped checks at query time, not a security certification. Secret scanning excludes binary/untracked/unreachable content; dependency checks do not certify OS/SDK security. Existing iOS unsigned CI38411807520 also succeeded, but this Android delivery makes no iOS device/direct-provider claim.

## Validation boundaries

All transport/authentication tests use mocks or intercepted HTTP and fake sockets. Android Keystore tests use mock strings on a disposable emulator. A successful build or emulator test is not evidence of real Alpaca connectivity or of the user's physical phone behavior. No production data API was called during development.

The exact final test and binary receipts, hashes and source/run mapping are recorded below and in `evidence/direct-alpaca-lab20/acceptance.json`. Raw JSON/JUnit receipts are retained with a SHA-256 manifest. Historical unsuccessful gates are preserved and are not counted as passes.

## Failed attempts and corrections

- Flutter preflight38405189019: 289 passed / 3 new test cases failed (typed fixture map, offscreen widget lookup, reused-observation expectation). Corrected fixtures/assertions; subsequent full suite passed. These were not hidden with skips.
- Release38407423416: Flutter/native/golden/advisory gates passed, then Android release lint required explicit `includeSubdomains=false` on three exact local HTTP domains. Added the attributes without expanding cleartext policy or disabling lint.
- Initial Keystore emulator could not locate its generated AVD. Aligned the explicit AVD directory and bounded startup waits. Android35 attempts38409692607 and38410865274 then failed before boot because the default userdata allocation exceeded available free-runner disk. CLI partition sizing did not override the generated configuration. Set the AVD configuration to 1GiB and selected the smaller official Android28 image. Android28 run38412885421 also failed before boot: upstream emulator enforces a6GiB minimum at first boot for API>=24. The final workflow allocates that supported size before Flutter consumes runner disk and preserves target metadata. No user files were deleted and no paid runner was used. Failed preparation attempts did not execute device tests. See the [upstream implementation](https://android.googlesource.com/platform/external/qemu/+/emu-master-dev/android-qemu2-glue/main.cpp).
- Superseded APK builds were canceled when the risk-fee and shared-ledger regressions required a newer source. Only the final source's successful artifact is accepted for delivery.

## Installation and phone acceptance

See [Arabic installation/key-entry guide](DIRECT_ALPACA_LAB20_AR.md). Install Lab20 alongside Lab19. Do not uninstall Lab19 or clear its storage; keep its existing APK and use its own Demo export for a separate backup. Lab20 does not automatically import Lab19 data or credentials. A signing mismatch is not a reason to uninstall an app that holds user data.

On the phone: enter keys privately, save, choose feed/session/symbols, enable Real Market Data, and press Test Connection. Then inspect Connected, source, timestamp and freshness. Start with signals only. The user's real-account connection, feed entitlement, OPRA coverage and physical-phone foreground/notification/battery behavior remain to be checked by the user. Never send keys, screen captures of keys, or broker account secrets into Work/GitHub.

## Remaining work and next checkpoint

1. User-operated physical Android acceptance with private on-device credentials; report only sanitized status/code, source and timestamps. Check Lab19 coexistence, failed authentication, entitlement rejection, network interruption/recovery, screen-off behavior and notification Stop.
2. Establish a stable privately held distribution signing key before treating this preview identity as a long-term upgrade channel. Do not overwrite an existing app with a differently signed APK.
3. Direct-bar cache and last 100 connection events are bounded in-memory data, not a long-term market archive. Market Paper keeps its separate decision ledger and stops instead of deleting old entries when its 10,000-entry limit is reached. Dedicated durable direct-data archival/export is a later batch; the existing server archive remains available independently.
4. More recent Android device coverage, real provider validation and broader option-contract semantics/market simulation remain unclaimed. The foreground monitor is experimental and does not execute Market Paper in the background. Full autonomous production V1.0 is not declared complete.
