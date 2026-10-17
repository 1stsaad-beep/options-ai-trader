"""Approved configuration still must fail promptly on an unexpected file type."""
import json
import os
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app import health_exporter


@pytest.mark.parametrize('module,function', [('app.alert_webhook','from_file'), ('app.health_exporter','token_file')])
def test_fifo_configuration_fails_without_waiting_for_a_writer(tmp_path, module, function):
    path = tmp_path / 'synthetic-config-fifo'
    os.mkfifo(path, 0o600)
    script = '''import importlib,sys
read=getattr(importlib.import_module(sys.argv[1]),sys.argv[2])
try: read(sys.argv[3])
except ValueError: sys.exit(0)
sys.exit(2)
'''
    result = subprocess.run([sys.executable, '-c', script, module, function, str(path)],
                            capture_output=True, timeout=3)
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b''


def test_health_config_growth_after_stat_remains_bounded(tmp_path, monkeypatch):
    path = tmp_path / 'synthetic-health.json'
    body = json.dumps({'token': 'fixture-only-token-not-a-secret'})
    path.write_text(body + ' ' * (4097-len(body))); path.chmod(0o600)
    monkeypatch.setattr(health_exporter.os, 'fstat', lambda _: SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_size=10))
    with pytest.raises(ValueError, match='^Health token file unavailable$'):
        health_exporter.token_file(path)
