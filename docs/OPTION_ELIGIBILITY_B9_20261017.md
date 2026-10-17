# Batch B9 — on-phone option eligibility for entries (2026-10-17)

Branch: `work/option-eligibility-b9` (stacked on B8). Paper only; the Live lock is unchanged; no new hosts (contract terms come from `paper-api.alpaca.markets`, which was already on the allowlist; the underlying quote comes from the existing Direct session).

## Behaviour
Every entry (BUY_TO_OPEN) for any broker now passes `OPTION_ELIGIBILITY` after the B4 checks, during both review and re-admission before sending. If it fails, it is refused with `OPTION_NOT_ELIGIBLE` and the reasons are shown. Closing orders are never vetoed by eligibility. The INTENT record stores the full eligibility evidence (`oat-option-eligibility-v1`, with the policy and model values).

Checks (`lib/brokers/option_eligibility.dart`):
1. Contract terms (`GET /v2/options/contracts/{OCC}`):
   - Identity matches (root/expiry/type/strike).
   - active + tradable.
   - Standard contract by the same server rule (option-eligibility-v1): American, multiplier/size 100, single equity deliverable of 100 underlying shares, 100% allocation, T+1, not delayed.
   - Otherwise `ADJUSTED_OR_UNSUPPORTED_CONTRACT`.
2. Open interest ≥ 100, and its date no older than 5 days (`OPEN_INTEREST_TOO_LOW/STALE/UNAVAILABLE`).
3. Quote spread ≤ 1500 bps of mid (`SPREAD_TOO_WIDE`).
4. Underlying quote matches the symbol and is ≤ 30 s old (`UNDERLYING_QUOTE_UNAVAILABLE/STALE`).
5. Time to expiry from the shared calendar (`EXPIRY_TIME_UNAVAILABLE`).
6. Model IV from the mid (American CRR, 150 steps), from B8. Fails closed with `IMPLIED_VOL_<reason>`; IV ≤ 300%; |Δ| between 0.15 and 0.85.

Source of terms: the Alpaca account itself, or for IBKR/TradeStation the first registered active Alpaca Paper account (metadata only, read-only). Without one: `CONTRACT_TERMS_UNAVAILABLE`, so IBKR/TS entries are refused until an Alpaca account exists or the user chooses another terms source.

## User decisions required (defaults are conservative and temporary)
- Policy thresholds: OI 100, spread 15%, delta 0.15–0.85, IV 300%, OI age 5 days.
- Risk-free rate 4% and dividend yield 0 (no external source).
- Whether to allow IBKR/TS to use an Alpaca account for contract terms, or to build a terms source on each broker's own API.

## Evidence
`docs/evidence/option-eligibility-b9-20261017/`: analyze clean, **1093** tests (B8: 1084, +9 in `test/option_eligibility_test.dart`), debug APK, secret scan 0, SHA256SUMS. The B4/B5 tests use `requireEligibility: false` only to isolate their paths; the production default is `true`.

## Not proven / OPEN
- No real Alpaca terms response or real quote; the mock follows the documented shape.
- Discrete dividends, adjusted contracts (refused rather than priced), vol surface, and per-broker terms are not covered.
- Provider Greeks are not cross-checked against the model values (the provider has no timestamp).
