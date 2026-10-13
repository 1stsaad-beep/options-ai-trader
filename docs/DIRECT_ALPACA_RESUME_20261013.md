# Direct Alpaca Android — work checkpoint

Start from actual recovery/v1.0-20261011 HEAD, never a hard-coded report SHA.
Original accepted source: 67995126bd095e3e3bbbae2d74e9d19e0e2c8207; Lab19 remains unchanged on users' phones.

Batch 1: native policy + Android Keystore AES-GCM vault and offline Java policy gate. CI still pending at publication; local javac/Flutter unavailable. No real provider requests or keys used. Next implement fixed-host HTTPS/WS transport with mock tests, separate direct screen, real OHLCV lab inputs, isolated virtual option ledger and bounded foreground monitoring. OPRA qualification must be explicit; stock prices must never price options. Preserve all server code and Demo stores.

New APK must use separate Lab20 identity to preserve Lab19 with an ephemeral development signing key. Publish exact SHA256/signature and actual test counts after acceptance, not before. Real account acceptance remains a user-operated phone test with keys entered privately on-device. Do not request keys here.

Batch 2: native HTTPS + WebSocket session, bounded cache/backoff/rate limit, explicit OPRA quote read (no orders), activity method channel, optional nonexported 30-minute foreground indicator monitor. Nine JVM mock transport cases and dedicated CI gate added. Native compile/test acceptance pending. Flutter UI/ledger are the next batch. No saved key read channel; no secret in Intent/snapshot/error/log. Existing server service untouched. Automatic Android backups disabled for the new build; manual Demo export remains available.

Batch 2 native CI38403262671 succeeded (mock HTTP/WS, native compile, existing Flutter suite, policy). Batch 3 adds Flutter direct settings, genuine OHLCV inputs to five existing calculation/painter labs with provenance, a new Market Paper store, virtual OPRA-only fills, risk controls and durable close-first reversal. Demo defaults and stores remain unchanged. UI/paper/native additional tests are pending CI. Real credentials still never supplied or used; real connection and physical Android acceptance remain unperformed. Paper decisions pause outside Flutter while native foreground monitoring continues prices/RSI/MACD only.
