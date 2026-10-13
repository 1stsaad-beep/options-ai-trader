# Direct Alpaca Android — work checkpoint

Start from actual recovery/v1.0-20261011 HEAD, never a hard-coded report SHA.
Original accepted source: 67995126bd095e3e3bbbae2d74e9d19e0e2c8207; Lab19 remains unchanged on users' phones.

Batch 1: native policy + Android Keystore AES-GCM vault and offline Java policy gate. CI still pending at publication; local javac/Flutter unavailable. No real provider requests or keys used. Next implement fixed-host HTTPS/WS transport with mock tests, separate direct screen, real OHLCV lab inputs, isolated virtual option ledger and bounded foreground monitoring. OPRA qualification must be explicit; stock prices must never price options. Preserve all server code and Demo stores.

New APK must use separate Lab20 identity to preserve Lab19 with an ephemeral development signing key. Publish exact SHA256/signature and actual test counts after acceptance, not before. Real account acceptance remains a user-operated phone test with keys entered privately on-device. Do not request keys here.
