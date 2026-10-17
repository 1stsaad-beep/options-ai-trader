"""Fail packaging unless the APK is the isolated B15 phone-test identity.

It must never replace Build 23 (…v1previewrc2b23) or the default app id, and must be
non-debuggable and signed with the expected certificate.
usage: verify_paper_test_identity.py <aapt-badging.txt> <apksigner-certs.txt> <expected-version-code> [cert-sha256]
"""
from pathlib import Path
import re
import sys

badging = Path(sys.argv[1]).read_text()
certs = Path(sys.argv[2]).read_text()
expected_code = sys.argv[3]
expected_cert = sys.argv[4].lower().replace(':', '') if len(sys.argv) > 4 else None
package = re.search(r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'", badging, re.M)
if not package or package.group(1) != 'com.optionsaitrader.options_ai_trader.papertest':
    raise SystemExit('Refusing: package is not the isolated .papertest identity')
if package.group(2) != expected_code:
    raise SystemExit(f'Refusing: versionCode {package.group(2)} != {expected_code}')
if "application-label:'Options AI Trader – Paper Test'" not in badging:
    raise SystemExit('Refusing: missing distinct launcher label')
if 'application-debuggable' in badging:
    raise SystemExit('Refusing: APK is debuggable')
digests = re.findall(r'certificate SHA-256 digest: ([0-9a-f]{64})', certs)
if len(set(digests)) != 1:
    raise SystemExit('Refusing: expected exactly one signing certificate')
if expected_cert and digests[0] != expected_cert:
    raise SystemExit('Refusing: signing certificate differs from the stable box key')
print(f'Verified: {package.group(1)} {package.group(3)} ({package.group(2)}), cert {digests[0]}')
