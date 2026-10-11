# Options AI Trader — RC2 Lab 15

Offline Arabic RTL Demo with a separately identified Android development preview. Continue from `recovery/v1.0-20261011`; this is an engineering candidate, not a complete or broker-connected V1.0.

## Phone repair and safe installation

See [the repair/evidence report](../docs/PHONE_BUILD15_REPAIR.md) and [Arabic phone instructions](../docs/PHONE_BUILD15_INSTALL_AR.md). Build 15 uses `com.optionsaitrader.options_ai_trader.v1previewrc2b15` and launcher label **Options AI Trader Lab 15**. Keep Build 14 installed; there is no in-place migration or automatic sharing of its private storage. Manual Demo backup/import remains available.

Chart Lab includes explicit display-only wave/ABC/Bat/divergence fixtures, independent RSI/MACD scales, confirmed pivot overlays, replay and honest no-result states. The emergency page links to five isolated safety exercises using the actual local engine without accessing the user's account/store. These features do not connect research outputs to execution.

## Reproduce the gates

Pin Flutter **3.47.7** and its bundled Dart SDK, Java 17 and the Android SDK required by the pinned Flutter runner. From this directory:

```sh
bash scripts/bootstrap.sh
flutter analyze
flutter test --exclude-tags=golden
flutter test --tags=golden
OAT_PREVIEW_BUILD=true flutter build apk --debug --build-name=1.0.0 --build-number=15
```

The reviewed golden reference is Linux at 360×440 with the pinned SDK's Roboto. Set `FLUTTER_ROOT` to that SDK for the golden test. CI compares committed images; it never updates them automatically. See [baseline review notes](test/goldens/README.md).

CI verifies the actual APK package/version/launcher label, development signature and SHA-256 before delivery. Without configured private development signing Secrets the preview uses the runner's ephemeral development key; this does not establish future upgrade compatibility. Do not put a private keystore, credentials or tokens in Git. The iOS workflow runs on macOS and builds without distribution signing; it is not an IPA or TestFlight delivery.

## Existing optional backend client

The separate FastAPI/Mock mode remains available. Local Demo balances/prices/decisions are local synthetic data; connected Mock mode uses backend records. Live remains locked. No IBKR or Paper connection is authorized by these build/test instructions.

Earlier backend setup is documented in [MOBILE.md](../docs/MOBILE.md) and the historical [BUILD_V04.md](../docs/BUILD_V04.md). Enter a local development token in the connection dialog, never in source or dart-define. On a local emulator the development backend is normally at `http://10.0.2.2:8000`; release connections require HTTPS.
