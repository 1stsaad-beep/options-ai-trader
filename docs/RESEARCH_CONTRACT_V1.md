# Server research contract, version 1

Recovery engineering batch, 2026-10-11. This is synthetic SHADOW research;
none of these endpoints accepts execution authority or sends broker orders.

All responses validate `schema_version=1`, the requested `account_id` and
`symbol`, `mode=SHADOW`, `source=synthetic_fixture`, and explicit false values
for `execution_authority`, `external_connections`, `profitability_evidence`.
Authentication uses the existing API bearer boundary.

| Path after `/api/accounts/{account}/research/{symbol}` | Method | Data |
|---|---|---|
| empty suffix | GET | Current workbench, original quantitative modules and decision |
| `/snapshot` | POST `{}` | Envelope, snapshot_id, workbench captured at request time |
| `/snapshots` | GET | Envelope, items and truncated |
| `/snapshots/{id}/replay` | GET | Original workbench/decision and labeled hypothetical outcome |
| `/snapshots/{id}/observations` | POST `{}` | Capture this minute's later synthetic quote, with immutable provenance |

The mobile typed parser consumes real service outputs in
`mobile/test/fixtures/research_contract_v1.json`. Python regenerates the same
fixture under fixed IDs and clock and asserts equality. Flutter parses that
fixture and rejects unsupported versions, mismatched identities, unsafe flags,
future observations and inconsistent replay identities. This verifies the
serialization boundary; it is not a live device/network integration test.

Snapshots are persisted in the server's immutable decision journal, rather
than solely in phone memory. Restarting the phone can reload the list.
Disabling a watch symbol does not erase its historical evidence. Lists are
account scoped and capped at 100 results from the most recent 1000 account
research records; `truncated=true` warns that the list is incomplete. No
pagination/export of older research records is implemented by this endpoint.

Replay returns the exact saved `original_workbench`; the UI does not replace
original reasons with current analysis. `as_of` belongs to that original
workbench. `outcome_as_of` bounds the latest synthetic quote used for the
hypothetical outcome. Completed replay is stable as the clock advances.

Replay now reads only prospectively saved observations from migration 5's
append-only `research_observations` table. Advancing the clock alone never
creates outcomes. Two distinct later synthetic minute observations are needed;
with zero or one, status is `INSUFFICIENT_OBSERVED_OUTCOME` and P&L is null.
Both observation and capture timestamps must precede the replay time. Duplicate
capture calls in the same minute return the existing receipt. A different
account/contract/model, invalid quote, corrupted digest or future evidence is
rejected. The original decision is never modified. API callers cannot provide
prices/timestamps. Capturing does not submit an order or reconcile account trust.

Quote model `synthetic-option-fixture-v1` is pinned in new workbenches and
observations. Legacy unversioned snapshots remain viewable but cannot acquire
new evidence under an inferred generator version. Already completed replay
uses its earliest two saved observations, without repricing original fees.

**Remaining limitation:** these are saved synthetic observations, not real
option market prices. They do not establish historical execution, liquidity,
exercise behavior or profitability. The separate local Demo analysis is still
independent; this contract does not unify all five chart labs or implement
offline Demo Counterfactual P&L. Mobile snapshot data lives in the server DB.

Snapshot writes are sent once. A lost response is an unknown save outcome:
the UI directs the operator to refresh the list before manually retrying.
Switching account, symbol or page invalidates in-flight display updates.
