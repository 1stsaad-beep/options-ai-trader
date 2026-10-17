# Durable notification transport — batch61

The existing immutable observed-worker alert inbox is also the source of a separate, opt-in notification sender. It does not create broker orders, alter financial events, acquire a trading-worker lease, mark owner-polled alerts read, or clear worker/provider faults. All verification in this change uses disposable databases and synthetic receivers. No real receiver was contacted.

## Delivery contract

`python -m app.observed_alert_delivery_worker` opens an **existing** migrated database only. Migration13 is additive: per-target retry/lease state and immutable exact-event delivery receipts. The process remains disabled unless `OAT_ALERT_DELIVERY_APPROVAL=notifications_only_approved`. It reads only the explicit `OAT_ALERT_RECEIVER_FILE`; no receiver, token, service subscription or deployment is created by this code. Existing paper/live hard locks remain in force.

The mounted file must be a regular, non-symlink file, at most4096 bytes, with no permissions for other users; provision read access only to the worker identity. It contains exactly `endpoint` and `token`. Endpoint is HTTPS on443 with fixed path `/oat/v1/alerts`, no credentials, query or fragment. A separately provisioned receiver must support the following contract. The program never discovers recipients or reads broker keys.

A POST body contains `contract=observed-alert-delivery-v1`, the original sanitized alert event, `idempotencyKey`, and `externalOrder=false`. It sends no account positions, cash, provider payloads or credentials in the body. Authentication uses the explicitly provided bearer token. `Idempotency-Key` is a SHA256 binding of protocol version, normalized endpoint hash, original sequence and event hash. Token rotation preserves the destination cursor; changing the destination deliberately starts its own backlog.

The receiver **must durably deduplicate this key** before replying HTTP200 with exactly `{"contract":"observed-alert-ack-v1","sequence":N,"eventHash":"original SHA256"}`. HTTP200 alone is insufficient. Delivery is **at least once**: a crash after remote receipt and before local ACK can resend the same key. This code cannot promise exactly-once remote effects for an incompatible receiver. Historical raised/resolved events are delivered in original order; their detection time is retained rather than presented as a current fault.

## Failure and security boundaries

- A serialized DB transaction validates the entire original alert chain and all prior receipts, then commits a30-second owner/generation lease and retry reservation **before network I/O**. Another connection cannot concurrently reserve that target. A stale sender cannot commit its successor's ACK.
- Exact ACK and local receipt commit together. A failed local commit leaves a conservative reservation and retries the same event/key after lease expiry. Unexpected status, malformed ACK and network errors never advance delivery.
- Retry delay grows from5 to300 seconds; HTTP429 has a60-second floor. HTTP401/403 latch `AUTH_BLOCKED` across restarts. After correcting the explicit receiver configuration, `--reset-auth-lock` resets only this notification latch and refuses an active delivery lease. It does not reset provider access or financial state.
- Public DNS answers only; any private, link-local, reserved or multicast result rejects the target before socket creation. Validated literal IP is pinned for the connection, while TLS verification and SNI retain the configured hostname. Broker-host suffixes are excluded. No redirect is followed.
- Whole-request deadline5 seconds, DNS wait at most2 seconds, one pending resolver thread per worker instance, request at most8192 bytes, ACK at most4096 bytes, strict UTF8/JSON with duplicate keys and nonfinite constants rejected. A slow response is interrupted at the absolute deadline, not merely by per-read timeouts. A stuck OS resolver may retain one daemon thread; repeated attempts do not spawn more lookups.
- Failure output is fixed and sanitized. URL, token, provider text and driver errors are not printed. Sender heartbeat is independent, expires after30 seconds, and is invalidated on owned shutdown. `--healthcheck` is read-only and reports process liveness; `AUTH_BLOCKED` being live does not mean delivery succeeds.

The CLI supports `--once` for an explicitly configured deployment and `--healthcheck` for a process supervisor. No Compose receiver secret or auto-enabled service is added. Production service/supervisor configuration and a compatible external receiver remain unconfigured. An external monitor outside the host/database is still required to observe a complete host/DB outage; a sender depending on the same database cannot truthfully claim delivery during that outage.

Verification of inbox/receipts is streamed but still O(history), under the existing bounded DB transaction. This is not a trusted historical checkpoint or a constant-time delivery scan. That separate storage/history work remains open.

## Verification

35 focused Python tests cover exact ACK/order, retry after lost local commit, wrong ACK, auth latch,429, fencing, corrupted/future originals, independent manual ACK, private-address rejection, pinned TLS destination, fixed POST, no redirects, bounded strict response, slow-body deadline, single pending DNS, private secret file, owner-fenced health and absent-database refusal. The full suite passes1664 tests locally. No test uses a real receiver.

Four new shared checks run against two actual PostgreSQL connections in the existing disposable CI gate. Backup/restore also verifies the exact immutable receipt, pending retry reservation and stable event/key after restoring a new database. PostgreSQL/Compose/security acceptance is pending the source commit's existing Actions; local SQLite results are not represented as PostgreSQL results.
