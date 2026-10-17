"""Local smoke-script guard tests; these do not imply Docker was executed."""
import copy
import importlib.util
import json
from pathlib import Path
import stat
import subprocess

import pytest


spec = importlib.util.spec_from_file_location("compose_smoke", Path(__file__).resolve().parents[2] / "scripts" / "compose_smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
PROJECT = "oat-smoke-" + "a" * 24


def fixture_containers():
    result = []
    for service in ("api", "worker", "postgres"):
        result.append({"Config": {"Labels": {"com.docker.compose.project": PROJECT, "com.docker.compose.service": service},
                                  "User": "trader", "Env": ["ENABLE_LIVE=false", "TRADING_MODE=paper", "BROKER_PROVIDER=mock",
                                      "DATABASE_URL=postgresql://trader:" + "fixture" + "@postgres:5432/options_demo"]},
                       "State": {"Status": "running", "Health": {"Status": "healthy"}},
                       "HostConfig": {"ReadonlyRootfs": True}, "NetworkSettings": {"Ports": {
                           "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}]} if service == "api" else {}}})
    return result


def test_remote_daemon_refused_before_running_any_command(monkeypatch):
    monkeypatch.setattr(smoke, "command", lambda *_: pytest.fail("Remote check issued a command"))
    with pytest.raises(smoke.SmokeFailure, match="REMOTE_DOCKER_REFUSED"):
        smoke.require_local_engine({"DOCKER_HOST": "tcp://remote.invalid:2376"})


def test_remote_context_refused_before_contacting_daemon(monkeypatch):
    calls = []
    def command(args, env, timeout):
        calls.append(args)
        return "ssh://remote.invalid"
    monkeypatch.setattr(smoke, "command", command)
    with pytest.raises(smoke.SmokeFailure, match="REMOTE_DOCKER_CONTEXT_REFUSED"):
        smoke.require_local_engine({})
    assert len(calls) == 1 and calls[0][1:3] == ["context", "inspect"]


def test_cleanup_project_guard_precedes_any_docker_command(monkeypatch):
    monkeypatch.setattr(smoke, "command", lambda *_: pytest.fail("Ownership guard issued a command"))
    with pytest.raises(smoke.SmokeFailure, match="PROJECT_OWNERSHIP_GUARD"):
        smoke.project_resources("another-project", {})


@pytest.mark.parametrize("mutation,reason", [
    ("foreign", "FOREIGN_CONTAINER"), ("public", "PUBLIC_OR_UNEXPECTED_PORT"),
    ("live", "SAFE_MODE_REQUIRED"), ("sqlite", "ISOLATED_POSTGRES_REQUIRED"),
    ("root", "RUNTIME_HARDENING_MISSING"), ("db_port", "PUBLIC_OR_UNEXPECTED_PORT"),
])
def test_inspection_rejects_unsafe_or_foreign_services(mutation, reason):
    containers = fixture_containers()
    if mutation == "foreign":
        containers[0]["Config"]["Labels"]["com.docker.compose.project"] = "other-project"
    elif mutation == "public":
        containers[0]["NetworkSettings"]["Ports"]["8000/tcp"][0]["HostIp"] = "0.0.0.0"
    elif mutation == "live":
        containers[0]["Config"]["Env"][0] = "ENABLE_LIVE=true"
    elif mutation == "sqlite":
        containers[0]["Config"]["Env"][-1] = "DATABASE_URL=sqlite:///wrong.db"
    elif mutation == "root":
        containers[0]["Config"]["User"] = "root"
    else:
        containers[2]["NetworkSettings"]["Ports"] = {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5432"}]}
    with pytest.raises(smoke.SmokeFailure, match=reason):
        smoke.inspect_owned_containers(PROJECT, containers)


def test_safe_inspection_and_heartbeat_require_no_accounts():
    assert set(smoke.inspect_owned_containers(PROJECT, fixture_containers())) == {"api", "worker", "postgres"}
    payload = {"api_ready": True, "database_ready": True, "live_enabled": False, "mode": "synthetic_mock",
               "trading_ready": False, "accounts": [], "schema_versions": [1, 2, 3, 4],
               "worker": {"present": True, "fresh": True, "status": "OK", "age_seconds": 2.1}}
    assert smoke.validate_readiness(payload)
    bad = copy.deepcopy(payload)
    bad["worker"]["fresh"] = False
    assert smoke.validate_readiness(bad) is False
    bad["accounts"] = [{"id": "unexpected"}]
    with pytest.raises(smoke.SmokeFailure):
        smoke.validate_readiness(bad)


def test_observed_worker_is_disabled_nonroot_and_secret_isolated():
    containers=fixture_containers()
    worker=copy.deepcopy(containers[1])
    worker['Config']['Labels']['com.docker.compose.service']='observed-paper'
    worker['Config']['Env']+=['OAT_OBSERVED_PAPER_APPROVAL=','OAT_ALPACA_DATA_APPROVAL=']
    containers.append(worker)
    assert 'observed-paper' in smoke.inspect_owned_containers(PROJECT,containers,observed_paper=True)
    worker['Config']['Env'][-2]='OAT_OBSERVED_PAPER_APPROVAL=virtual_only_approved'
    with pytest.raises(smoke.SmokeFailure,match='DISABLED'): smoke.inspect_owned_containers(PROJECT,containers,observed_paper=True)
    worker['Config']['Env'][-2]='OAT_OBSERVED_PAPER_APPROVAL='
    containers[0]['Mounts']=[{'Destination':'/run/secrets/oat_observed_paper'}]
    with pytest.raises(smoke.SmokeFailure,match='SECRET'): smoke.inspect_owned_containers(PROJECT,containers,observed_paper=True)


def test_http_redirect_never_forwards_credentials():
    with pytest.raises(smoke.SmokeFailure, match="HTTP_REDIRECT_REFUSED"):
        smoke.NoRedirects().redirect_request(None, None, 302, "redirect", {}, "https://external.invalid")


def test_failed_command_does_not_disclose_output(monkeypatch):
    marker = "private-fixture-do-not-print"
    monkeypatch.setattr(smoke.subprocess, "run", lambda *_, **__: subprocess.CompletedProcess([], 1, marker, marker))
    with pytest.raises(smoke.SmokeFailure) as caught:
        smoke.command(["docker", "compose"], {}, 1)
    assert marker not in str(caught.value)


def test_build_failure_still_cleans_only_generated_owned_project(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(smoke, "require_local_engine", lambda *_: None)
    monkeypatch.setattr(smoke, "project_resources", lambda *_: [])
    class Probe:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def bind(self, address): assert address == ("127.0.0.1", 8000)
    monkeypatch.setattr(smoke.socket, "socket", Probe)
    calls, env_values = [], []
    def command(args, env, timeout):
        calls.append(args)
        env_file = Path(args[args.index("--env-file") + 1])
        assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
        env_values.extend(line.split("=", 1)[1] for line in env_file.read_text().splitlines())
        assert "OPTIONS_API_TOKEN" not in env and "POSTGRES_PASSWORD" not in env
        if "up" in args:
            raise smoke.SmokeFailure("COMMAND_FAILED")
        assert "down" in args and "--volumes" in args
        return ""
    monkeypatch.setattr(smoke, "command", command)
    result = smoke.run_smoke()
    assert result["status"] == "failed" and result["cleanup"] == "owned_resources_removed"
    assert len(calls) == 2
    assert all(args[args.index("--project-name") + 1] == result["project"] for args in calls)
    assert all(value not in json.dumps(result) for value in env_values)
    assert not list(tmp_path.iterdir())


def test_historical_generator_exception_cannot_hide_a_replaced_literal():
    scanner_spec = importlib.util.spec_from_file_location("scanner", Path(__file__).resolve().parents[2] / "scripts" / "security_scan.py")
    scanner = importlib.util.module_from_spec(scanner_spec)
    scanner_spec.loader.exec_module(scanner)
    expression = ' + secrets.token_hex(32) + '
    prefix = "POSTGRES_" + "PASSWORD="
    assert scanner.scan_text("scripts/compose_smoke.py", prefix + repr(expression)) == []
    assert scanner.scan_text("app/settings.py", prefix + repr(expression))
    replacement = "aB3!cD4_eF5-gH6IjK7LmN8OpQ9"
    assert scanner.scan_text("scripts/compose_smoke.py", prefix + repr(replacement))


def test_disposable_smoke_cannot_inherit_notification_or_metadata_approvals(monkeypatch,tmp_path):
    monkeypatch.setattr(smoke.tempfile,'tempdir',str(tmp_path))
    for name in ['OAT_ALERT_DELIVERY_APPROVAL','OAT_ALERT_RECEIVER_FILE','OAT_OPTION_METADATA_APPROVAL','OAT_MARKET_RUNTIME_ROLE']:
        monkeypatch.setenv(name,'must-not-be-inherited')
    def preflight(env):
        assert not any(k.startswith('OAT_') for k in env)
        raise smoke.SmokeFailure('OFFLINE_GUARD_ONLY')
    monkeypatch.setattr(smoke,'require_local_engine',preflight)
    result=smoke.run_smoke(observed_paper=True)
    assert result['error_code']=='OFFLINE_GUARD_ONLY' and result['cleanup']=='not_required'
