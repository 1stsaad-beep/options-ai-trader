# Independent alert receiver — batch66

This adds the compatible receiving end of batches61–62. It is a separate process and a separate SQLite database, with no connection to the trading database, broker credentials, financial tables or outbound notification service. No actual receiver, host, URL, token or deployment was provisioned or contacted.

## Protocol and durability

A dedicated endpoint/token/store belongs to exactly one originating alert journal. POST `/oat/v1/alerts` requires the explicit bearer token and exact idempotency header/body binding to the configured endpoint hash, sequence and event hash. The receiver validates the original sanitized event, chain, raised/resolved transition and nonregressing detection time. It commits the immutable original plus durable head in one FULL-synchronous SQLite transaction before returning the exact ACK required by the sender. An exact retry returns the same ACK without inserting again, including after process restart. A conflicting event, wrong endpoint identity, gap, broken chain or corrupt tail blocks acknowledgement; no reset or overwrite occurs.

The receiver stores only alert-code events. ACK proves durable receipt by this inbox, **not human reading, email/SMS delivery, live market health or exactly-once downstream effects**. No email/SMS integration, recipient or automatic forwarding was added. A fully privileged filesystem administrator can replace both history and root; hash verification is not a provider signature. History verification is streamed but O(history); trusted checkpoint/capacity work remains separate.

GET of the same path is authenticated, returns at most25 events per page, and never changes acknowledgement or financial state. Full stored history and the head are checked even for an older duplicate/page, so a later corrupt tail cannot be hidden. The process never calls the original trading API, and can retain committed alerts while that API/database is unavailable. Detecting a new total host/database outage still requires a separately implemented outside probe; an inbox cannot infer it from silence alone.

## Explicit operation, disabled by default

`python -m app.alert_receiver` remains disabled unless `OAT_ALERT_INBOX_APPROVAL=receiver_only_approved`, paper mode and Live=false. It reads only the explicitly named `OAT_ALERT_RECEIVER_FILE` (the existing private endpoint/token JSON contract) and `OAT_ALERT_INBOX_FILE`. The endpoint identifies the public HTTPS443 `/oat/v1/alerts` address expected by the sender; the receiver itself binds only127.0.0.1:8081, with request logs disabled. An authorized operator must provide a TLS reverse proxy, trusted parent directory, independent host and process supervision. No public listener or deployment is automatically configured.

`--initialize` explicitly creates a new0600 file with exclusive/no-follow creation; it refuses existing files and symlinks and retains a failed initialization for review. Normal serving/`--healthcheck` opens an existing private regular file only and verifies identity/schema/history. No trading Repository or migration runs. The local healthcheck verifies the inbox, not public TLS reachability or sender success. Token rotation preserves the endpoint/store identity and deduplication history.

POST bodies are bounded to8192 bytes during streaming, with an absolute2-second body deadline, strict UTF8/JSON, duplicate/nonfinite rejection, exact content-type and no content encoding/query. Duplicate auth/key headers are rejected; authentication precedes body reads. All responses use no-store and fixed errors without URL, token, driver text or echoed input. SQL failure cannot return ACK; a lost response after commit safely retries the original.

## Evidence

34 new Python cases;1729 full Python tests passed locally, no failures/skips (existing Starlette deprecation warning). Tests cover the real sender→ASGI receiver contract, lost ACK/retry, exact original deduplication across16 concurrent accepts/two connections, head-write rollback, abrupt process exit after commit, immutability, corrupted tail/head/removal, endpoint identity, private/missing/symlink files, invalid/future authority claims, authentication, bounded/slow/chunked bodies, strict JSON, pagination and disabled/explicit CLI initialization. These are synthetic isolated tests, not deployment or real-message acceptance. Source GitHub CI is pending this save. Existing mobile/native/financial-v1/v2/workflows remain unchanged.
