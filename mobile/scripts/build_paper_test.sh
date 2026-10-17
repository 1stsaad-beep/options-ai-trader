#!/usr/bin/env bash
# B15 phone-test APK: release mode, isolated id ".papertest", signed with the box's stable debug key.
# usage: build_paper_test.sh <versionCode> <versionName> <channel> <out-dir>
set -euo pipefail
CODE=$1 NAME=$2 CHANNEL=$3 OUT=$4
cd "$(dirname "$0")/.."
KEY=${HOME}/.android/debug.keystore
[ -f "$KEY" ] || { echo "missing stable box key $KEY" >&2; exit 2; }
CERT=$(keytool -list -v -keystore "$KEY" -storepass android -alias androiddebugkey | sed -n 's/.*SHA256: //p' | tr -d ':' | tr 'A-F' 'a-f')
OAT_PAPER_TEST_BUILD=true flutter build apk --release --build-name="$NAME" --build-number="$CODE" \
  --dart-define=OAT_BUILD_CHANNEL="$CHANNEL"
APK=build/app/outputs/flutter-apk/app-release.apk
BT=$(ls -d "$ANDROID_HOME"/build-tools/* | sort -V | tail -1)
mkdir -p "$OUT"
"$BT/aapt" dump badging "$APK" > "$OUT/aapt-badging.txt"
"$BT/apksigner" verify --print-certs --verbose "$APK" > "$OUT/apksigner-verify.txt"
python3 scripts/verify_paper_test_identity.py "$OUT/aapt-badging.txt" "$OUT/apksigner-verify.txt" "$CODE" "$CERT" | tee "$OUT/identity.txt"
(cd "$(dirname "$APK")" && sha256sum app-release.apk && stat -c '%n %s bytes' app-release.apk) > "$OUT/apk-release-sha256-size.txt"
