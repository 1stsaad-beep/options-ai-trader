# Options AI Trader mobile V0.4

Arabic RTL Flutter client for the independent MockBroker development backend. Dark theme defaults; light and system themes are available. No broker credentials or real financial accounts are supported here. Live is disabled in the client and locked on the server.

See [mobile documentation](../docs/MOBILE.md) and [build instructions](../docs/BUILD_V04.md). Pin Flutter 3.47.7 with Dart 3.13.5, Java 17 and Android SDK 36. Native Android/iOS runners are included; run `bash scripts/bootstrap.sh`, `flutter analyze`, and `flutter test` before compiling. The Android GitHub workflow produces a debug APK only after an actual successful remote run. The iOS workflow produces an unsigned app and requires macOS/Xcode; TestFlight signing is a separate later task.

Do not store API tokens in source or `--dart-define`. Enter the local development token in the app connection dialog. On Android emulator use `http://10.0.2.2:8000`; on Termux on the same phone use `http://127.0.0.1:8000`. Release builds require HTTPS. All balances and reports come from backend data; disconnected states show unavailable data.
