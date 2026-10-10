# Stable development signing — V0.5

No private key, keystore, password, production certificate or broker secret belongs in Git, artifacts, caches or logs.

Android CI always runs analysis/tests and builds. With the complete four GitHub Actions Secrets below it signs with the same private development key on every build. With none present it emits an explicitly `unsigned` APK (not installable). A partially configured secret set fails closed. Pull requests never receive signing secrets. Release builds have no automatic debug-key fallback.

Repository Settings → Secrets and variables → Actions:

- `OAT_KEYSTORE_BASE64`: base64 of your development-only keystore, populated through GitHub's secure UI or an authenticated local CLI, never chat.
- `OAT_KEYSTORE_PASSWORD`
- `OAT_KEY_ALIAS`
- `OAT_KEY_PASSWORD`

Use one private development key for all installs intended to update each other. Keep an encrypted backup outside Git. Recovering the same private key is required after a workstation is lost; a certificate fingerprint alone cannot restore it. A production Play signing setup is a separate later task.

The workflow writes the key to a mode-0600 temporary runner file and removes it in an always-run cleanup. Only APK, test output, checksum and non-secret provenance are uploaded. `mobile/scripts/prepare_ci_signing.py` never prints key data. Build scripts and workflow changes still require code review: code that runs with secrets must be trusted.

Local development can reuse an already retained Android SDK debug keystore outside the repository. Such a key is development-only (its conventional password does not make it suitable for production). If the connected GitHub tools cannot configure Secrets, this is reported as a remaining limitation, not claimed as successful permanent cloud signing.

Inspect signatures with `apksigner verify --verbose --print-certs app.apk`. Android updates require both the same application ID and signer. Do not erase existing app data merely to resolve a certificate mismatch; preserve the older installation or test on a separate device/profile.

## V1 restoration and separately identified preview

The V0.5 local development key was not present after workspace recovery. It is not stored in Git and cannot be recreated from the old APK or certificate. The four signing Secrets mechanism remains the path to stable upgrade-compatible builds; configuration of those Secrets has not been claimed.

When no signing Secrets are configured, V1 Android CI builds the ordinary unsigned artifact and also an installable development preview with application ID `com.optionsaitrader.options_ai_trader.v1preview`. The preview uses the ephemeral runner debug signer; the private key is neither uploaded nor cached. It can coexist with the older installation and does not migrate or erase its saved Demo data. Its signer is **not stable between runners**. This is a testing deliverable, not a Play release or an upgrade to V0.5. CI verifies its APK signature and publishes only public certificate evidence. The remaining stable-signing setup must be performed through secure GitHub Secrets controls, never by posting passwords or private keys in chat.

## RC2 continuation

RC2 retains the same secure Secrets mechanism. If Secrets are absent, its separately installable preview uses `com.optionsaitrader.options_ai_trader.v1previewrc2`, build 11, and the label **Options AI Trader V1 RC2**. It can coexist with RC1 and does not delete or migrate RC1 local data. The runner key is still temporary; changing the preview identifier is not a substitute for stable signing. No signing private material is stored in the source or delivery archive.
