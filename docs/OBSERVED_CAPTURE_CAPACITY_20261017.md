# Bounded observed capture v1

No new worker, schedule or external sender. The existing opt-in worker remains the sole process. The existing OPRA-only read route and hard new-entry eligibility lock are unchanged.

Each capture selects at most30 distinct option contracts and10 analysis symbols. Owned contracts take priority; when there are more than30, a durable lexical ring rotates them across ticks. Remaining slots rotate optional configured contracts. Selected owned symbols take analysis priority. Missing optional analysis never substitutes a price and does not suppress valid owned quotes.

The capture_cursor row in observed_paper_data_state holds only a version and the last reserved contract/symbol. It is separate from the request budget/auth latch. Rotation and request reservation share the fenced SQL transaction. An HTTP failure keeps both charged request and advanced cursor; a blocked reservation keeps the cursor unchanged. Demand insertion/removal uses bisect after the saved identity and wraps, rather than resetting all accounts to the beginning.

OBSERVED_PARTIAL_COVERAGE is a persistent operational warning whenever demand exceeds one capture or returned members/analysis are missing. With large owned demand, coverage spans multiple15-second ticks and can be further delayed by provider failure/budget/backoff. The warning is not a guarantee of timely protection. Operators must keep demand within a verified deployment capacity; the code neither closes every position automatically nor invents marks.

No financial records or observed ledger-v1/v2 transitions are migrated or edited. Both request cursor and immutable alert inbox are included in whole-database backup/restore. Tests are explicitly offline fixtures; actual OPRA entitlement, continuous deployed monitoring and three market sessions remain unproven.
