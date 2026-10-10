"""Restore a stable development key only to RUNNER_TEMP, never logs/artifacts.
A missing complete secret set selects unsigned CI output; a partial set fails.
"""
import base64
import os
from pathlib import Path

names = ('OAT_KEYSTORE_BASE64', 'OAT_KEYSTORE_PASSWORD', 'OAT_KEY_ALIAS', 'OAT_KEY_PASSWORD')
values = [os.environ.get(name, '') for name in names]
if any(values) and not all(values):
    raise SystemExit('Incomplete development signing Secrets; refusing fallback')
output = Path(os.environ['GITHUB_ENV'])
if all(values):
    raw = base64.b64decode(values[0], validate=True)
    if not 256 <= len(raw) <= 65536:
        raise SystemExit('Unexpected keystore size')
    target = Path(os.environ['RUNNER_TEMP']) / 'options-development.jks'
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
    with output.open('a') as env:
        env.write(f'OAT_KEYSTORE_PATH={target}\nOAT_UNSIGNED_BUILD=false\nOAT_SIGNING_MODE=stable-development\n')
    print('Stable development signing configured from Secrets; private key not exported')
else:
    with output.open('a') as env:
        env.write('OAT_UNSIGNED_BUILD=true\nOAT_SIGNING_MODE=unsigned\n')
    print('Signing Secrets unavailable: building UNSIGNED APK, not installable until privately signed')
