# V0.3 mobile build and reproducibility

Android and iOS native runners are included. They originate from Flutter 3.47.7 official SDK templates; the workspace fallback initially rendered the templates with Python because the VM could not bootstrap. Images originate from `flutter_template_images` 5.0.0 and the Gradle wrapper from the Flutter SDK's pinned official wrapper archive. A later `flutter create` run succeeded (exit 0), and `flutter pub get` succeeded after repairing the host tool environment. Template rendering, platform configuration, and workflow creation are **not successful Flutter APK builds**.

Use Flutter **3.47.7**, JDK 17, and Android SDK 36 on a normal build host. Run from `mobile/`:

```bash
bash scripts/bootstrap.sh
flutter analyze
flutter test
flutter build apk --debug --build-name=0.3.0 --build-number=3 --dart-define=API_URL=http://10.0.2.2:8000
```

Debug local networking is allowed only in the debug Android manifest. Main/release manifest does not opt into plaintext networking. API tokens must be entered on-device and must never be build flags or committed secrets. The executable has no supported real broker adapter; Live remains server-locked regardless of mobile build configuration.

`.github/workflows/android.yaml` installs JDK and pinned Flutter, analyzes, tests, builds the debug APK, and uploads `options-ai-trader-v0.3.apk`, SHA-256 and test output. It runs only after this independent repository is pushed to GitHub. No remote run is claimed by shipping this file. GitHub runner availability and account allowance apply; do not start paid services to use the app.

For iOS, `.github/workflows/ios.yaml` is manually dispatched on macOS. Supply the reverse-DNS `bundle_id`; or locally run `IOS_BUNDLE_ID=com.example.optionsTrader python3 scripts/configure_platforms.py` after bootstrapping. The included identifier is a placeholder. The workflow builds an **unsigned Runner.app**, not an installable IPA. TestFlight requires Apple Developer Program membership, your own app registration, distribution certificate/provisioning profile or managed signing, and App Store Connect submission. No Apple credentials are requested in chat. Android/iOS share Dart tests and Arabic/theme implementation; iOS build requires real macOS/Xcode validation.

## Workspace investigation

Initial Dart 3.13.5 and older Dart 3.4.4 could print `--version` but aborted executing tools because `/proc/self/maps` and `/proc/self/exe` are unavailable. A scratch-only C compatibility shim for `pthread_getattr_np`, `readlink`, and `__lxstat64` let both execute a hello program and Dart CLI help. This shim is **not included in the app or runtime deliverable** and cannot establish production correctness. The build tool also needed a scratch `TMPDIR` because `/tmp` does not exist, and a scratch pub cache. JDK 17 and Android commandline tools were downloaded to scratch; Java was configured with its local shared-library path. No system files or permissions were changed.

Final command outcomes are recorded in the V0.3 test report; do not infer an APK exists merely because dependencies or SDK files downloaded.

The normal Flutter bot-detection startup was rejected by automatic approval review because it attempted a cloud metadata probe. Source inspection established that the official `CI=true` / `BOT=true` flags short-circuit that probe; the safer run used those flags and suppressed analytics. Flutter version then ran successfully. The analysis server also needed a scratch-only memory-telemetry shim using peak RSS from `getrusage` in place of inaccessible current RSS; this changes host telemetry only, not app code or diagnostics. These host compatibility shims are not included in source/mobile runners/APK.

## Actual final V0.3 outcome

- Flutter 3.47.7 / Dart 3.13.5; final `flutter analyze`: exit 0, no issues, 10.3 seconds wall time.
- Final `flutter test --machine`: exit 0, 15 passed, 0 failed, 0 skipped, 5.1 seconds wall time.
- Android debug APK build: exit 0, 388.64 seconds; Gradle 9.3.1, JDK 17.0.20.1+1, compile/target SDK 36. Initial environmental attempts failed or timed out before host fixes and dependency caching.
- APK manifest/signature inspected using official SDK `aapt2` and `apksigner`, both exit 0: package `com.optionsaitrader.options_ai_trader`, version `0.3.0`, code `3`, minimum SDK 24 (Android 7.0), ABIs arm64-v8a / armeabi-v7a / x86_64, APK v2 signature verified with an Android Debug certificate.
- APK bytes: 152344158. SHA-256: `bbf9fd9cd1b283e99bc5d39f3e40891b99d9f7ba6382f3a05750e92264c4ada3`.
- No physical device installation, Android emulator acceptance run, macOS iOS build or TestFlight submission was executed. Software checks and the debug APK do not certify trading readiness.
