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

**Remaining limitation:** the legacy research replay still reconstructs two
deterministic synthetic quotes using the fixture function. These are not
persisted real option observations and do not establish historical execution,
liquidity, exercise behavior or profitability. A later batch must persist
versioned outcome evidence or report insufficient observations. The separate
local Demo analysis is still an independent synthetic implementation; this
batch unifies the connected research surface, not all five chart labs.

Snapshot writes are sent once. A lost response is an unknown save outcome:
the UI directs the operator to refresh the list before manually retrying.
Switching account, symbol or page invalidates in-flight display updates.
