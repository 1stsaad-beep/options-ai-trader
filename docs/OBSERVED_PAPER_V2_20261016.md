# Observed-paper lifecycle v2

New accounts explicitly use `observed-paper-ledger-v2`. The original v1 transition module is frozen byte-for-byte as `observed_paper_v1.py`; genesis reconstruction dispatches by the saved contract. No account or original event is silently upgraded. The original v1 mobile fixture's commands, facts, balances and event hashes are reproduced by an actual reopened SQL ledger test.

Both new options default off and require a stopped-account configuration change:

- `addEnabled`: at most one one-contract addition, on the same explicitly selected contract, a new completed same-direction signal, at least 10% conservative liquidation gain on owned basis including fees, an unconsumed current OPRA quote and all portfolio/risk limits. Existing total position basis counts against per-position risk; a new position slot is unnecessary for the same owned position. No addition follows an exit fill in the same cycle. Alpaca-source additions remain blocked by the unimplemented qualified terms/Greeks admission gate.
- `scenarioExit`: saves the original 20-bar support for Call or resistance for Put when opening. A later qualified completed-bar close crossing that fixed level creates a durable owned close intent. This is an explicit support/resistance policy, not a fabricated wave identity. Missing optional bars cannot trigger that exit and never disable owned quote protection. Missing quotes retain intent without a fill; stop/profit/expiration protections keep priority.

The mobile server configuration understands both contracts: v1 retains its exact fields; v2 exposes the two explicit switches. Existing v1 accounts continue their original behavior and may be closed/settled normally.

## Original-receipt performance

Authenticated `GET /api/observed-paper/accounts/{id}/performance` streams original receipt payloads under the same account snapshot/version. It reports realized P&L, fees, cash, owned basis, realized-capital drawdown, contract counts, add/exit reasons and pure quote round-trip statistics. The report independently checks its reconstructed realized P&L, fees and remaining option basis against the verified ledger.

No entire event history is loaded into memory. Round-trip win rate/profit factor excludes closures involving manual settlement; total realized P&L and fees still include all settlement receipts. No denominator means null, not infinity or a fabricated success rate. Cost-basis capital is labeled separately from liquidation equity. Unrealized P&L, NAV drawdown and Sharpe remain unavailable without complete qualified valuation; an open portfolio's cash is never represented as its value. The phone accepts only a report matching the displayed account, source, version, hash and balances.

## Verification and limits

Local full Python suite:1368 passed;14 new v2/version-preservation/performance cases. Shared v1 and v2 mobile fixtures are reproducible from actual SQL events. Flutter/PG/Compose acceptance for this source is pending until raw CI results are inspected.

Batch28 first source6f32da0 failed one Flutter analyzer braces rule; correction1178247 passed analysis but failed two new widget harness assertions (an offscreen error and ambiguous scrollable), not financial tests. Those test helpers are corrected in this batch; failed runs38872155571 and38872514130 remain failures, never acceptance. No APK, emulator or phone request.

Remaining work includes actual contract qualification, adjusted/legacy lots, full wave/Demo parity, remaining capacity and complete valuation reporting, operational deployment/soak, independent final review and one final candidate APK. The provider remains GET-only and disabled by default; no credentials were read or market calls made.
