# Batch B2: Android build verification on the agent box (2026-10-17)

Base: `work/broker-paper-b1` @ `f6fd0d2c22ea0e3e0104368fe70788f0e2cab137` (B1, not amended). Local branch `work/android-build-b2`. **Not pushed.**
No source changes were needed. The project built and its native tests passed as committed, so this batch adds only records.

## Toolchain (box-local, under `/workspace/tools`, not committed)

Temurin JDK 17.0.20.1, Android cmdline-tools (latest), `platform-tools`, `platforms;android-36`, `build-tools;36.0.0`.
Gradle downloaded NDK 28.2.13676358 and CMake 3.22.1 on its own (Flutter `ndkVersion`).
Flutter 3.47.7 / Dart 3.13.5 (the CI pin), Gradle wrapper 9.3.1, AGP 9.1.0, Kotlin 2.4.0. The SDK and JDK use about 0.8 GB, plus the NDK.
Memory: the committed `mobile/android/gradle.properties` asks for `-Xmx8G`. The box has only about 4 GB free, so it was overridden only by a
box-local `$GRADLE_USER_HOME/gradle.properties` (`-Xmx2g`, Kotlin daemon 768m, 4 workers, no daemon), and every Gradle call used `--no-daemon`.
The repository file is unchanged. `mobile/scripts/bootstrap.sh` (the CI step) was run. It upgraded two transitive packages in `pubspec.lock`;
that change was reverted so the committed lock stays authoritative.

## Results

| Check | Result |
|---|---|
| `python3 mobile/scripts/test_monitor_policy.py` | 30 checks passed |
| `python3 mobile/scripts/test_alpaca_policy.py` | 44 checks passed |
| `./gradlew :app:testDebugUnitTest --no-daemon` | **61 JVM tests passed** (AlpacaAccess 12, AlpacaSession 31, PaperIndependentStore 10, PaperSegments 8). 0 failures, errors or skips. Matches the accepted CI count of 61. |
| `flutter build apk --debug` | Built. `com.optionsaitrader.options_ai_trader`, versionCode 23, minSdk 24, targetSdk 36, debuggable, signed with the box's Android Debug key. 165,241,370 bytes, SHA-256 `e499e64d325a5d11d8da693afd0a42ac7f40e7db3889c8948b43fc00f7fdb2c4` |
| CI-style `OAT_PREVIEW_BUILD=true flutter build apk --release --build-name=1.0.0 --build-number=23` | Built. `…options_ai_trader.v1previewrc2b23`, minSdk 24, not debuggable, signed with the box's Android Debug key (cert SHA-256 `dde693a8…6720`). 61,904,547 bytes, SHA-256 `3e333e81006805ae9ed59560f76800a3a3683217d70f4b318f7fd5e5427b39bd`. `verify_preview_identity.py` passed. |
| `flutter_secure_storage` 11.2.0 integration | Plugin registered in `GeneratedPluginRegistrant` (`com.it_nomads.fluttersecurestorage.FlutterSecureStoragePlugin`). Its Android minSdk 24 equals the app's minSdk 24 (`flutter.minSdkVersion`). Brings `com.google.crypto.tink:tink-android:1.23.0`. Classes are present in the dex. No manifest or Gradle change was needed. |
| `scripts/android_dependency_audit.py` (releaseRuntimeClasspath) | 94 Maven packages, 0 OSV advisories |

Evidence: `docs/evidence/android-build-b2-20261017/` (logs, JUnit XML, badging, apksigner output, APK SHA-256 and size, dependency list and audit, toolchain, SHA256SUMS).
APK binaries are **not committed**; the repository does not store APKs in Git. Local copies:
`/workspace/tools/apk/options-ai-trader-b2-debug.apk` and `/workspace/tools/apk/options-ai-trader-b2-release-preview-debugsigned.apk`.

## Limits

- No emulator or device run. `androidTest` (`AlpacaVaultDeviceTest`) and on-device Keystore behaviour of flutter_secure_storage have not been checked.
- Both APKs are signed with this box's ephemeral Android Debug key. The preview APK reuses the Build23 preview application id and
  versionCode 23 but has a different signer, so Android will refuse to install it over Build23. Never uninstall older builds to get around this (see KNOWN_GAPS / D15).
  These are engineering artifacts, not a release candidate, and the user has not been asked to test them on a phone.
- Pre-existing Kotlin warning (`PaperIndependentStore.kt:98`, unnecessary `!!`) and Gradle 10 deprecation notices are left unchanged.
