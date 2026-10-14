# Options AI Trader V1 — completion contract

Authority: the complete user-attached `Options_AI_Trader_Work_Master_Prompt.txt`, received 2026-10-13. Baseline is actual Recovery HEAD `9ff7b6084c5a874dd3621748346bf0692f5bc962`, not main or an earlier delivery. Earlier phone-test/stop instructions in historical reports are superseded by this mission. No unavailable conversation is claimed recovered.

## Product boundaries

Four distinct modes: Demo Synthetic (offline generated observations), Direct Alpaca Market Data (read-only authorized data), Market Paper (independent virtual ledger; qualified option quotes required), and Server Market Runtime (independent collector/research process). No balances, execution rights or prices flow implicitly between modes. Long single Call/Put only; no external broker orders, Live, connected IBKR Paper, paid subscription or server deployment. Shadow research never overrides deterministic admission.

## Acceptance requirements

| ID | Required behavior |
|---|---|
| R01 | Independent capital, allocation, watchlist, strategy, risks, orders, positions, reasons, costs and controls; explicit four-account Market Paper experiment, USD1,000 each, four distinct rules, three-session comparison with actual evidence only. |
| R02 | Per-trade/day/exposure/pending caps; revalidate admission and fills; serialize/idempotently reconcile uncertain operations; no LLM authority. |
| R03 | Causal 1–5, ABC, third-of-third and C scenarios, alternatives, Fibonacci and invalidation; preserve numbering known at each time. |
| R04 | Gartley/Bat/Butterfly/Crab/Cypher geometry and PRZ; regular/hidden RSI/MACD divergence with structural confirmation and completed multiple timeframes; specified classical indicators. |
| R05 | Five chart labs with candles, axes, timeframes, zoom/layers, valid model labels, entry/exit/add markers and original reasons; explicit unavailable states. |
| R06 | Named quantitative research engines and independent supervisor; published execution-vs-Shadow authority and tests; no paid LLM dependency. |
| R07 | Signal/data/contract/liquidity/timing/risk gates; protective and partial exits, holding/scenario/expiry and scaling; optional research failure cannot veto an independently justified exit; no missing-price fill. |
| R08 | Same-account/symbol opposite-direction lock across ownership and unresolved orders; cancel/settle, fully close, reconcile, then revalidate opposite direction; partial/restart/duplicate tests. |
| R09 | Option identity, strike/expiry, spread, liquidity, Greeks, modeled fees/slippage, exercise/assignment/settlement boundaries; stock never substitutes for option price; indicative never qualifies execution. |
| R10 | Android Keystore, visible connection outcomes, 401/403/406/429/timeouts, persisted opt-in, one bounded reconnecting socket, authorized IEX/SIP, provenance/freshness and actual chart bars; secure-screen protection. |
| R11 | Mode isolation and unconditional external-order/Live lock. |
| R12 | Optional bounded Android foreground monitor with notification/Stop; lifecycle/outage behavior; no phone-off guarantee; retain future Oracle portability without deployment. |
| R13 | Immutable contemporaneous wave/chart/trade/replay evidence; account cash, realized/unrealized P&L, return, trades, win rate, drawdown, fees, reasons, interruptions/risk violations; unknown outcomes remain unknown. |
| R14 | Account isolation, safe persistence/migration/backup/restore, secret-free source/APK/logs, authenticated API and dependency review; no Mawj or Sharia filter. |
| R15 | RTL, stability/performance, preserve existing installations/data; stable Android signer only when securely available; iOS distribution requires actual signing/device evidence. |

## Delivery gates

1. Audit current implementation and close critical defects with regression evidence and frequent non-forced Git checkpoints.
2. Independent review pass after implementation and final applicable Python/Flutter/Golden/native/API/security/PostgreSQL/Compose/causality/lifecycle verification. Mocks, real provider access and physical-phone evidence remain distinct.
3. Only after those gates: one final candidate APK with SHA-256, signer, source SHA/artifact, readiness matrix and short final phone acceptance. Never ask the user to test intermediate APKs. Do not label incomplete essentials V1.0 complete. Three real sessions cannot be fabricated or replaced by fixture results.

## Current gate correction — 2026-10-14

The user explicitly requests an honest post-Build23 audit and continued feasible repairs. No new APK before software gaps are closed, and no phone test now. Build23 is a historical verified engineering artifact; it does not fulfill the final V1.0 delivery gate. An independent review requires a distinct reviewer and a documented report; another pass by the implementer is not sufficient. See docs/POST_BUILD23_AUDIT_20261014_AR.md.
