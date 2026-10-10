"""Idempotent local-network permissions and optional iOS bundle identifier."""
from pathlib import Path
import os
import plistlib
import re

manifest = Path('android/app/src/main/AndroidManifest.xml')
content = manifest.read_text()
if 'android.permission.INTERNET' not in content:
    content = content.replace('<application', '<uses-permission android:name="android.permission.INTERNET"/>\n    <application', 1)
manifest.write_text(content)
debug = Path('android/app/src/debug/AndroidManifest.xml')
if debug.exists():
    content = debug.read_text()
    if 'usesCleartextTraffic' not in content:
        content = content.replace('</manifest>', '    <application android:usesCleartextTraffic="true"/>\n</manifest>')
    debug.write_text(content)
info = Path('ios/Runner/Info.plist')
if info.exists():
    data = plistlib.loads(info.read_bytes())
    data['CFBundleDisplayName'] = 'Options AI Trader'
    data['CFBundleLocalizations'] = ['ar', 'en']
    data['NSAppTransportSecurity'] = {'NSAllowsLocalNetworking': True}
    info.write_bytes(plistlib.dumps(data, sort_keys=False))
bundle = os.getenv('IOS_BUNDLE_ID', '')
if bundle:
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*){2,}', bundle):
        raise SystemExit('IOS_BUNDLE_ID must be a reverse DNS identifier')
    project = Path('ios/Runner.xcodeproj/project.pbxproj')
    content = project.read_text()
    content = re.sub(r'PRODUCT_BUNDLE_IDENTIFIER = [^;]+;',
                     lambda match: f'PRODUCT_BUNDLE_IDENTIFIER = {bundle}' + ('.RunnerTests' if '.RunnerTests;' in match[0] else '') + ';', content)
    project.write_text(content)
