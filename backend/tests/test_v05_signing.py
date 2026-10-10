"""CI signing preparation must not disclose secrets or silently rotate the key."""
import base64
import os
from pathlib import Path
import subprocess
import sys
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'mobile/scripts/prepare_ci_signing.py'
NAMES = ('OAT_KEYSTORE_BASE64','OAT_KEYSTORE_PASSWORD','OAT_KEY_ALIAS','OAT_KEY_PASSWORD')


def run(tmp_path, values):
    env = {k:v for k,v in os.environ.items() if k not in NAMES}
    env.update(GITHUB_ENV=str(tmp_path/'env'),RUNNER_TEMP=str(tmp_path),**values)
    return subprocess.run([sys.executable,str(SCRIPT)],env=env,text=True,capture_output=True)


def test_missing_secrets_produces_explicit_unsigned_build(tmp_path):
    r=run(tmp_path,{})
    assert r.returncode==0
    assert 'OAT_UNSIGNED_BUILD=true' in (tmp_path/'env').read_text()
    assert not (tmp_path/'options-development.jks').exists()


@pytest.mark.parametrize('name',NAMES)
def test_partial_secret_configuration_fails_closed(tmp_path,name):
    r=run(tmp_path,{name:'synthetic-not-a-secret'})
    assert r.returncode!=0
    assert not (tmp_path/'env').exists()


def test_complete_fixture_is_private_and_not_printed(tmp_path):
    # Arbitrary bytes exercise transport, not a real private key or valid keystore.
    encoded=base64.b64encode(b'fixture-only-'*40).decode()
    r=run(tmp_path,dict(zip(NAMES,[encoded,'fixture-pass','fixture-alias','fixture-key-pass'])))
    assert r.returncode==0
    target=tmp_path/'options-development.jks'
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.read_bytes()==b'fixture-only-'*40
    for value in [encoded,'fixture-pass','fixture-alias','fixture-key-pass']:
        assert value not in r.stdout+r.stderr+(tmp_path/'env').read_text()
    assert 'OAT_SIGNING_MODE=stable-development' in (tmp_path/'env').read_text()
