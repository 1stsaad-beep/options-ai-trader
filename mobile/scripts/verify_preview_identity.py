"""Fail packaging if the actual APK could replace the user's Build 14/15/16/17 apps."""
from pathlib import Path
import re
import sys

badging = Path(sys.argv[1]).read_text()
package = re.search(r"^package: name='([^']+)' versionCode='([^']+)'", badging, re.M)
expected = 'com.optionsaitrader.options_ai_trader.v1previewrc2b18'
if not package or package.groups() != (expected, '18'):
    raise SystemExit('Refusing delivery: APK identity/version does not match isolated Build 18')
if "application-label:'Options AI Trader Lab 18'" not in badging:
    raise SystemExit('Refusing delivery: missing distinct launcher label')
print('Verified actual APK: isolated Build 18 identity and launcher label')
