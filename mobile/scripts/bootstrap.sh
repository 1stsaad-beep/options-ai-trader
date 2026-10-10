#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Generate missing official runners and wrapper with the installed SDK.
# Existing app source, tests and platform identifiers are preserved.
flutter create --platforms=android,ios --org com.optionsaitrader --project-name options_ai_trader .
python3 scripts/configure_platforms.py
flutter pub get
