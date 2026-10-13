# Completion decisions

| ID | Decision and rationale | Evidence/constraint |
|---|---|---|
| D01 | Continue only `recovery/v1.0-20261011` in this private repository; preserve every original tree entry and history. | User authorization; base `9ff7b608`. Git HTTPS lacks credentials; use connected Git Data API with current parent, expected SHA and `force=false`. |
| D02 | Current attached mission supersedes historical next-step phone tests and scope restrictions. Preserve original reports as history. | User explicitly forbids intermediate phone testing and authorizes routine engineering across this project. |
| D03 | Keep quantitative research in Shadow unless an explicit deterministic policy and regression suite grants virtual execution. | R02/R06. Existing research has useful functionality without blanket execution authority. |
| D04 | Block realistic market-option execution without qualified OPRA data; do not simulate a completed market study. | R09. Existing quote-side research simulation is approximate and must remain labeled. |
| D05 | Separate optional stock analysis validity from owned-option protective exits. Require fresh, matching, qualified option observations and trusted ledger for every simulated close. | Source audit: MarketPaper.evaluate currently checks stock data before considering protection. |
| D06 | Ambiguous persistence must stop mutation and opposite entry until readback/recovery; a thrown write alone does not prove unchanged disk. | Source audit: PaperStore.write can commit before an exception; R08/R14. |
| D07 | Build/signing not started during audit; use existing CI test gates and defer packaging until final acceptance. | R15 and user instruction. `[chart-check]` is the existing Android/iOS skip mechanism, not a new automation. |
| D08 | Preserve existing account balances/configuration during migration. Four USD1,000 experiment accounts must be an explicit, idempotent action. | R01/R14; no account replacement/reset. |
| D09 | Declared tests reflect executed results only; prior successful CI is historical evidence tied to its source. | Baseline Lab22 316 Flutter/6 Golden/41 JVM/11 emulator reported and successful runs inspected; current run still separately required. |
