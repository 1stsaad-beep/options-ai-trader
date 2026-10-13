# Direct Alpaca: safe reconciliation handoff

This is a saved engineering checkpoint, **not an accepted Lab20 release**.

## What happened

Recovery began at `67995126bd095e3e3bbbae2d74e9d19e0e2c8207` on `recovery/v1.0-20261011`. All 944 original tree entries were retained. While this session implemented the data boundary, the target branch advanced independently:

1. `3bc4345d574f2be16340c214ca595bd68d730af1`: another native Alpaca policy and vault.
2. `157b91ccf21cd35b1a722d1a54ceca13abe54d19`: another `AlpacaSession`, MethodChannel and foreground monitor.

Both target update attempts used an expected SHA and `force=false`; neither replaced these newer commits. This session preserved its work on **recovery/direct-alpaca-lab20-20261013** and stopped adding overlapping UI/features. The checkpoint merges the first independent policy/vault commit, preserving its vault format and Java policy tests. It does not contain the second independent transport implementation.

## Distinguish the implementations

| Component | Isolated checkpoint | Concurrent recovery source reviewed at 157b91c |
|---|---|---|
| Transport owner | `AlpacaEngine` + `AlpacaTransport` | `AlpacaSession` + `AlpacaRuntime` |
| REST | Fixed GET historical/latest stock bars, <=6 requests/minute | Historical bars and explicit OPRA quote reads, <=15 requests/minute |
| WebSocket | Optional; off by default; 406 leaves REST available | Required to authenticate before historical reads; 406 stops this session |
| Credentials | Compatible Keystore vault, native-only read helper; no Flutter reveal | Keystore vault and save/status-only channel |
| Foreground monitor / phone screen | Not connected in this checkpoint | Native bounded monitor saved; Flutter connection screen not yet in the reviewed commit |
| Option simulation | Explicitly unavailable; no option pricing or order capability | Quote boundary saved; integration/risk acceptance must be checked at the newest head |

**Do not merge the entire branch blindly.** Choose one session owner; never open both engines or duplicate subscriptions. Prefer extending the current accepted recovery implementation with reviewed useful fixes from this checkpoint. Keep Demo storage keys, old backend service and server configuration intact.

## Acceptance status

| Requirement | Status in this session |
|---|---|
| Fixed Alpaca data hosts/GET-only calls; no order/cancel/replace endpoints | Implemented, native mocks under CI |
| IEX/SIP choice; explicit entitlement refusal | Implemented in transport; phone controls not integrated |
| Complete OHLCV, timestamp deduplication, source fields | Implemented in memory cache; no real feed acceptance |
| API cooldown and reconnect | Implemented; 429 wait retained across manual restart, auth timeout and socket-generation guards |
| Keystore ciphertext storage | Implemented; physical device/instrumented storage test not executed |
| Flutter settings, five chart labs on real observations | Not implemented by this session |
| Market Paper accounts, exits, scaling, reversal | Not integrated; no simulated contract fills claimed |
| Background service on a phone | Not tested |
| New APK, checksum and certificate | Not produced by this session |
| Actual Alpaca / OPRA entitlement test | Not executed; still requires separate approval and on-device keys |

The initial isolated run 38403905558 failed before native tests because OkHttp 5.5.0 required compileSdk 37. The existing toolchain targets compileSdk 36. The dependency was corrected to 5.3.2; see the final acceptance receipt in `DIRECT_ALPACA_LAB20_STATUS.md` for actual subsequent results. Retain failures in the audit history.

## Resume sequence

1. Read the **actual** newest recovery head, this checkpoint and `PROGRESS.md`. Establish one active writer for overlapping mobile transport/Flutter files. Do not force-push or discard either lineage.
2. Review current `AlpacaSession` against the extra protections here: independent REST mode for the shared Basic account, stream-limit handling, same-timestamp corrections, bounded cooldown that survives reconnect, no credential-bearing errors, cancellation of stale callbacks.
3. Resolve transport ownership before connecting the new Flutter screen. Preserve backend/Oracle selections and the separate Demo Synthetic namespace. Never expose saved secrets through a reveal channel.
4. Use real stock bars in pure chart calculations; keep provider timestamps and IEX/SIP provenance. A fresh minute bar is not a real option quote. Only qualified contract quotes may enter a separate virtual-fill gate; otherwise display analysis-only.
5. Targeted unit/widget/native tests first, then the Android acceptance workflow. For a new preview use a distinct **Lab20** application ID and launcher label; do not change or uninstall Lab19. Verify actual APK identity, signature and SHA-256 before delivery. Stable signing is not established by an ephemeral CI development key.
6. Only after an accepted APK: user enters keys on the device, understands extraction risk, explicitly tests connectivity. Check invalid credentials/feed, loss of internet, old bars, other-app stream conflict, stop action, screen-off behavior and device restart. A powered-off phone cannot maintain the engine.

No provider credentials were requested, no account was connected, no financial order was sent, no paid resource was purchased, and no other application was accessed.

## Later concurrent advance observed during acceptance

The requested recovery branch advanced a third time to `7935c01c56a4df22101d16495dcb0689b5a867ca` (`feat(flutter): connect stock labs and isolated OPRA-gated Market Paper`). It adds direct Flutter screens/labs and a separate virtual ledger. This checkpoint did not overwrite or merge that work. Its presence is not acceptance: inspect that commit or a newer head and its own tests/build before making any phone-release claim. The component table above intentionally describes the previously reviewed 157b91c snapshot.

Review questions for the newer ledger (not reproduced failures in this session): verify whole-account pending/open exposure limits, reassessment of the opposite signal after the close/quote await, persistence failure ambiguity before any further fills, and exchange-local expiry/session protection. Do not label these gates passed merely because a basic mocked open/close succeeds.
