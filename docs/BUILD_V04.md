# V0.4 mobile builds

The existing V0.3 Android and iOS runners are retained. V0.4 uses Flutter 3.47.7 / Dart 3.13.5, JDK 17, Android compile/target SDK 36, and app version 0.4.0+4.

From `mobile/` on a normal development computer:

```bash
bash scripts/bootstrap.sh
flutter analyze
flutter test --machine > flutter-tests.json
flutter build apk --debug --build-name=0.4.0 --build-number=4 --dart-define=API_URL=http://10.0.2.2:8000
```

Android debug permits local HTTP for the development API; the release manifest does not opt into plaintext traffic. Enter a local API token on the device. Do not put tokens or credentials in build flags or source. The APK communicates with the separately running simulation server; the server enforces the Live lock and MockBroker-only execution.

## Cloud build preparation

`.github/workflows/android.yaml` analyzes, runs Flutter tests, builds the debug APK, and publishes `options-ai-trader-v0.4.apk` plus its SHA-256 checksum and test output. The workflow has read-only repository permissions. It requires a separately authorized GitHub repository and runner allowance; delivering workflow files is not evidence that GitHub Actions ran.

`.github/workflows/ios.yaml` is a manual macOS unsigned build. Set the reverse-DNS `bundle_id` input or run `IOS_BUNDLE_ID=com.example.optionsTrader python3 scripts/configure_platforms.py` locally. Native runners include Arabic localization and local-network ATS configuration. An unsigned Runner.app is not an installable IPA. Signing and TestFlight require macOS/Xcode, an Apple Developer account, App Store Connect registration, and distribution signing handled outside the conversation. No iOS build or device installation has been executed in this Linux workspace.

## Workspace restoration

The previous temporary toolchain had been pruned; it was downloaded again from official Flutter, Eclipse Adoptium, Google Android, and Gradle distribution sources. The Flutter archive SHA-256 matched the official release manifest (`af7455f540df951184c7953fbe3cf884766e7541dacf8571f9f582db03dd6230`). The Gradle 9.3.1 distribution SHA-256 matched the committed wrapper setting (`17f277867f6914d61b1aa02efab1ba7bb439ad652ca485cd8ca6842fccec6e43`). Pub package archives were checked against `pubspec.lock` hashes.

This host lacks `/proc` and `/tmp`. A scratch-only compatibility library supplies executable-path and thread-stack queries and uses peak RSS for inaccessible memory telemetry. It is excluded from the source archive and APK. `TMPDIR` and package caches are in scratch; JDK uses the existing system certificate trust store. Flutter runs with `CI=true`, `BOT=true`, and analytics suppression to avoid cloud metadata detection. Application, analyzer, compiler, and tests retain their normal logic. A partially extracted SDK kernel snapshot was restored byte-for-byte from the verified archive before execution; a Dart hello program then completed successfully.

Actual final analyze, test, APK build, signature and manifest results are recorded below after execution and in the V0.4 test report. Downloading tools or creating workflows alone does not constitute a build.

## Actual final V0.4 outcome

- Flutter 3.47.7 / Dart 3.13.5; `flutter analyze --no-pub`: exit 0, no issues, 10.10 seconds.
- `flutter test --no-pub --machine`: exit 0, **24 passed, 0 failed, 0 skipped**, 14.38 seconds. Loader events are excluded from test counts.
- Android APK build: exit 0, 298.34 seconds. JDK 17.0.20.1+1, Gradle 9.3.1, Android Gradle Plugin 9.1.0, SDK 36, NDK 28.2.13676358. Gradle emitted deprecation warnings for a future Gradle 10 upgrade; the pinned build succeeded.
- `aapt2 dump badging` and `apksigner verify --verbose --print-certs`: both exit 0. Package `com.optionsaitrader.options_ai_trader`, version `0.4.0`, code `4`, min SDK 24 (Android 7.0), target SDK 36. Universal debug APK includes arm64-v8a, armeabi-v7a, x86_64 and a verified APK v2 Android Debug signature.
- File: `options-ai-trader-v0.4.apk`, **152351982 bytes** (145.29 MiB). ZIP entry CRC checks passed after copying to the delivery path.
- SHA-256: `c1a695f5715b7f24f990d900d3dc9ca1810c821c3df9047f71876b2ff6cb9ab5`.
- Debug certificate SHA-256: `a04b4b0907e5e275818e0975ae8ee33cc93e5789552b2d8ec65e226ff0ed9025`. The previous temporary signing key was not restored. An existing V0.3 installation signed with another key may need to be uninstalled before V0.4 can install; preserve any local settings first. Server data remains separate from the app.
- No physical Android device/emulator acceptance test, macOS iOS build, TestFlight upload, or GitHub Actions run occurred. A signed debug artifact and software tests do not certify financial trading readiness.

Initial build attempts failed on an inherited unreachable host proxy; scratch Gradle settings were corrected to the permitted local proxy and system CA trust store. An attempt was interrupted for verbose diagnosis and local Android signing configuration. Final success follows those repairs. Raw project test outcomes, build command/exit/time, manifest, signature, and copied-artifact hashes are under `docs/evidence/v04/`; `mobile-environment-attempts.json` records the setup failures separately from the successful project tests.
