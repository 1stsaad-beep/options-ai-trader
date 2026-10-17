# Batch48 — observed contract qualification boundary

Continued from verified `d8e6821757f506e0889d3a053d68b60efcc908d5`.

`backend/app/option_eligibility.py` adds a versioned read-only Alpaca contract decoder and replaceable GET adapter. Exact symbol/root/right/expiry/strike, UUIDs, explicit multiplier/size, bounded decimal strings and up to16 original deliverables are checked. There are no default100-share deliverables. Source, raw SHA256, normalized terms SHA256 and actual receipt time remain separate. Receipt age has a24-hour diagnostic limit; it is not a provider effective timestamp or a historical corporate-action attestation.

The supported structural observation is an American, whole-cent,100-multiplier/100-size contract with one100-share underlying-equity deliverable,100% allocation,T+1,BTOB/CCC and no delayed settlement. Other valid structures are preserved and explicitly unsupported. Both older delayed null amounts and documented delayed "0" remain locked. Current metadata cannot migrate a legacy lot, repair its receipt or establish historical effective terms.

Alpaca snapshot Greeks remain values-only without independent provider time. Quote/trade timestamps,updated_since and arbitrary timestamp-like fields cannot grant freshness. `entryEligible`, `settlementEligible` and `externalOrder` are always false. The existing Basic chain now includes the new missing-terms/Greek-time assessment while retaining its old Greek-quality contract and indicative lock. Existing financial v1/v2 transitions are unchanged.

The contract GET adapter accepts an explicitly supplied approved transport, has no credential loading, environment activation, SDK, retries or order methods. It is tested offline; production approved metadata transport wiring, durable original capture/mobile metadata presentation and historical deliverable support remain software work. No claim is made that this building block closes all R09 requirements. A future provider with genuine Greek timing needs an explicitly versioned adapter; fields are not guessed.

Primary schema references checked2026-10-17:
- https://docs.alpaca.markets/us/reference/get-options-contracts (`show_deliverables`).
- https://docs.alpaca.markets/us/reference/optionchain (`updated_since` refers to quote/trade updates).
- https://docs.alpaca.markets/us/changelog/2026-10-07-option-deliverable-amount-c94a723 (delayed "0" amount).
- https://github.com/alpacahq/alpaca-py/blob/master/alpaca/trading/models.py and enums.py (deliverable fields/enums; SDK nullability text predates the changelog).

Verification: baseline1498 Python passed.135 targeted tests passed before adding the final transport sanitization/clock regression. Full current-source results and CI acceptance are recorded in the continuation checkpoint. Schema fixtures are explicitly synthetic offline inputs, not fetched market evidence.


Final source-specific acceptance for batches48–56: backend54 d06b0fdde9607ccbcc2ec53e03c3e61d2511483e passed1585 Python and PostgreSQL22/6/10/5/25/4/20 plus20 Compose; backend/scripts/infra/workflows unchanged through56. Mobile56 a5426bb9e6a9e5bc53fabc0846aec5db49146f29 passed970 visible Flutter/61 JVM/23 chart/6 Golden (65 hidden framework records excluded). Source56 security passed in its stated scope. Original artifacts verified SHA256/CRC in evidence/stage1-20261017/batch54-56-ci-index.json. This supersedes earlier pending-CI statements only for these sources; the documented software gaps remain open, with no APK or market-session claim.
