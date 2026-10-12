"""Bounded, disposable base-Compose integration smoke; no accounts or orders.

Run explicitly with --run on a local Unix Docker engine. Only generated
oat-smoke-* project resources can be cleaned up. Output never contains raw
Compose config, environment values, command output, database rows or logs.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
PROJECT_PATTERN = re.compile(r"oat-smoke-[0-9a-f]{24}\Z")


class SmokeFailure(RuntimeError):
    pass


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SmokeFailure("HTTP_REDIRECT_REFUSED")


def command(args: list[str], env: dict, timeout: int) -> str:
    try:
        result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True,
                                text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise SmokeFailure("COMMAND_UNAVAILABLE_OR_TIMED_OUT") from None
    if result.returncode:
        raise SmokeFailure("COMMAND_FAILED")
    return result.stdout


def require_local_engine(env: dict):
    explicit = env.get("DOCKER_HOST")
    if explicit and not explicit.startswith("unix://"):
        raise SmokeFailure("REMOTE_DOCKER_REFUSED")
    # Inspect local context metadata before issuing any daemon request.
    endpoint = command(["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], env, 15).strip()
    if not endpoint.startswith("unix://"):
        raise SmokeFailure("REMOTE_DOCKER_CONTEXT_REFUSED")
    command(["docker", "version", "--format", "{{.Server.Version}}"], env, 20)
    command(["docker", "compose", "version", "--short"], env, 15)


def project_resources(project: str, env: dict) -> list[str]:
    if PROJECT_PATTERN.fullmatch(project) is None:
        raise SmokeFailure("PROJECT_OWNERSHIP_GUARD")
    selector = "label=com.docker.compose.project=" + project
    found = []
    for category, verb in (("container", "ps"), ("volume", "volume"), ("network", "network")):
        args = ["docker", verb] + (["--all"] if category == "container" else ["ls"])
        found.extend(category + ":" + item for item in command(args + ["--filter", selector, "--quiet"], env, 15).split())
    return found


def inspect_owned_containers(project: str, containers: list[dict], *, market_runtime=False) -> dict:
    if PROJECT_PATTERN.fullmatch(project) is None:
        raise SmokeFailure("PROJECT_OWNERSHIP_GUARD")
    services = {}
    expected = {'api', 'worker', 'postgres'} | ({'market-collector'} if market_runtime else set())
    for container in containers:
        config, state = container.get("Config", {}), container.get("State", {})
        labels = config.get("Labels", {})
        if labels.get("com.docker.compose.project") != project:
            raise SmokeFailure("FOREIGN_CONTAINER_REFUSED")
        service = labels.get("com.docker.compose.service")
        if service not in expected or service in services:
            raise SmokeFailure("UNEXPECTED_SERVICE")
        if state.get("Status") != "running":
            raise SmokeFailure("SERVICE_NOT_RUNNING")
        if service == "postgres" and state.get("Health", {}).get("Status") != "healthy":
            raise SmokeFailure("POSTGRES_NOT_HEALTHY")
        for bindings in container.get("NetworkSettings", {}).get("Ports", {}).values():
            for binding in bindings or []:
                if service != "api" or binding.get("HostIp") != "127.0.0.1" or binding.get("HostPort") != "8000":
                    raise SmokeFailure("PUBLIC_OR_UNEXPECTED_PORT_REFUSED")
        if service == "api":
            bindings = container.get("NetworkSettings", {}).get("Ports", {}).get("8000/tcp", [])
            if bindings != [{"HostIp": "127.0.0.1", "HostPort": "8000"}]:
                raise SmokeFailure("API_LOOPBACK_BINDING_REQUIRED")
        if service in {"api", "worker", "market-collector"}:
            if not container.get("HostConfig", {}).get("ReadonlyRootfs") or config.get("User") in (None, "", "0", "root"):
                raise SmokeFailure("RUNTIME_HARDENING_MISSING")
            values = dict(item.split("=", 1) for item in config.get("Env", []) if "=" in item)
            if any(values.get(key) != value for key, value in {"ENABLE_LIVE": "false", "TRADING_MODE": "paper", "BROKER_PROVIDER": "mock"}.items()):
                raise SmokeFailure("SAFE_MODE_REQUIRED")
            database = urlsplit(values.get("DATABASE_URL", ""))
            if database.scheme != "postgresql" or database.hostname != "postgres" or database.port != 5432 or database.path != "/options_demo":
                raise SmokeFailure("ISOLATED_POSTGRES_REQUIRED")
            if market_runtime:
                if service != 'market-collector' and any(m.get('Destination') == '/run/secrets/oat_alpaca_data' for m in container.get('Mounts', [])):
                    raise SmokeFailure('ALPACA_SECRET_MUST_BE_COLLECTOR_ONLY')
                if service == 'market-collector':
                    if values.get('OAT_ALPACA_DATA_APPROVAL') or state.get('Health', {}).get('Status') != 'healthy':
                        raise SmokeFailure('COLLECTOR_MUST_BE_DISABLED_AND_HEALTHY')
                if service == 'api' and values.get('OAT_MARKET_RUNTIME_ROLE') != 'api_cache_only':
                    raise SmokeFailure('API_CACHE_ONLY_REQUIRED')
        services[service] = True
    if set(services) != expected:
        raise SmokeFailure("BASE_COMPOSE_SERVICES_INCOMPLETE")
    return services


def get_json(path: str, token: str | None = None):
    if path not in {"/health", "/api/readiness", "/api/accounts"}:
        raise SmokeFailure("HTTP_PATH_REFUSED")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirects())
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request("http://127.0.0.1:8000" + path, headers=headers)
    try:
        response = opener.open(request, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        payload = response.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            raise SmokeFailure("HTTP_BODY_TOO_LARGE")
        return response.status, json.loads(payload)


def validate_readiness(payload):
    worker = payload.get("worker", {})
    if (payload.get("api_ready") is not True or payload.get("database_ready") is not True
            or payload.get("live_enabled") is not False or payload.get("mode") != "synthetic_mock"
            or payload.get("trading_ready") is not False or payload.get("accounts") != []):
        raise SmokeFailure("UNSAFE_OR_NONEMPTY_READINESS")
    if worker.get("present") is not True or worker.get("fresh") is not True or worker.get("status") != "OK":
        return False
    age = worker.get("age_seconds")
    if type(age) not in (int, float) or not 0 <= age <= 120:
        raise SmokeFailure("INVALID_HEARTBEAT_AGE")
    versions = payload.get("schema_versions", [])
    if not versions or any(type(value) is not int for value in versions) or versions != sorted(set(versions)):
        raise SmokeFailure("MIGRATION_HISTORY_INVALID")
    return True


def run_smoke(*, market_runtime=False) -> dict:
    project = "oat-smoke-" + secrets.token_hex(12)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("COMPOSE_", "OAT_ALPACA_", "APCA_")) and key not in {"OPTIONS_API_TOKEN", "POSTGRES_PASSWORD"}}
    result = {"test": "base_compose_runtime", "project": project, "status": "failed",
              "checks": [], "live_enabled": False, "accounts_created": 0, "orders_created": 0,
              "cleanup": "not_required", "source": "isolated_synthetic_mock"}
    stage, owned = "preflight", False
    with tempfile.TemporaryDirectory(prefix="oat-compose-smoke-") as private:
        os.chmod(private, 0o700)
        env_file = Path(private) / ".env"
        descriptor = os.open(env_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        token = secrets.token_urlsafe(40)
        private_settings = {"POSTGRES_PASSWORD": secrets.token_hex(32), "OPTIONS_API_TOKEN": token}
        if market_runtime:
            placeholder = Path(private) / 'empty-data-secret.json'
            placeholder.write_text('{}')
            placeholder.chmod(0o600)
            private_settings['OAT_ALPACA_SECRET_FILE'] = str(placeholder)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("\n".join(f"{name}={value}" for name, value in private_settings.items()) + "\n")
        compose = ["docker", "compose", "--project-name", project, "--env-file", str(env_file),
                   "--file", str(ROOT / "infra" / "compose.yaml")]
        if market_runtime:
            compose += ['--file', str(ROOT / 'infra' / 'compose.market-runtime.yaml'), '--profile', 'market-runtime']
        try:
            require_local_engine(env)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 8000))
            if project_resources(project, env):
                raise SmokeFailure("PROJECT_ALREADY_EXISTS")
            owned = True
            stage = "build_and_start"
            command(compose + ["up", "--detach", "--build", "--wait", "--wait-timeout", "120"], env, 900)
            stage = "container_ownership_and_ports"
            identifiers = command(compose + ["ps", "--all", "--quiet"], env, 20).split()
            if len(identifiers) != (4 if market_runtime else 3) or any(re.fullmatch(r"[0-9a-f]{12,64}", item) is None for item in identifiers):
                raise SmokeFailure("EXPECTED_OWNED_CONTAINERS")
            containers = json.loads(command(["docker", "inspect", *identifiers], env, 20))
            inspect_owned_containers(project, containers, market_runtime=market_runtime)
            result["checks"].extend(["owned_services_running", "postgres_healthy", "loopback_only_ports", "api_worker_nonroot_readonly", "paper_mock_live_false"])
            stage = "http_and_worker_readiness"
            deadline = time.monotonic() + 120
            ready = False
            while time.monotonic() < deadline:
                try:
                    status, health = get_json("/health")
                    if status != 200:
                        time.sleep(2)
                        continue
                    if any(health.get(key) != value for key, value in {"status": "ok", "broker": "mock", "mode": "paper", "market_data": "synthetic", "live_enabled": False, "external_analysis_enabled": False}.items()):
                        raise SmokeFailure("UNSAFE_HEALTH_RESPONSE")
                    status, payload = get_json("/api/readiness", token)
                    if status == 200 and validate_readiness(payload):
                        ready = True
                        result["schema_versions"] = payload["schema_versions"]
                        result["worker_age_seconds"] = payload["worker"]["age_seconds"]
                        break
                except (urllib.error.URLError, TimeoutError, ConnectionError):
                    pass
                time.sleep(2)
            if not ready:
                raise SmokeFailure("READINESS_TIMED_OUT")
            result["checks"].extend(["public_health_safe", "authenticated_database_readiness", "fresh_worker_heartbeat", "trading_not_ready_without_accounts"])
            stage = "authorization_and_empty_ledger"
            for path in ("/api/accounts", "/api/readiness"):
                if get_json(path)[0] != 401:
                    raise SmokeFailure("UNAUTHENTICATED_ACCESS_NOT_REJECTED")
            status, accounts = get_json("/api/accounts", token)
            if status != 200 or accounts != []:
                raise SmokeFailure("EXPECTED_EMPTY_AUTHENTICATED_ACCOUNTS")
            sql = "SELECT json_build_object('accounts',(SELECT count(*) FROM accounts),'orders',(SELECT count(*) FROM orders),'positions',(SELECT count(*) FROM positions))"
            counts = json.loads(command(compose + ["exec", "--no-TTY", "postgres", "psql", "--username", "trader", "--dbname", "options_demo", "--tuples-only", "--no-align", "--command", sql], env, 20))
            if counts != {"accounts": 0, "orders": 0, "positions": 0}:
                raise SmokeFailure("LEDGER_NOT_EMPTY")
            result["checks"].extend(["unauthorized_endpoints_401", "authenticated_accounts_empty", "postgres_account_order_position_counts_zero"])
            if market_runtime:
                stage = 'independent_disabled_collector_restart_and_database_outage'
                def heartbeat():
                    query = "SELECT payload FROM runtime_health WHERE name='market_collector'"
                    return json.loads(command(compose + ['exec', '--no-TTY', 'postgres', 'psql', '--username', 'trader', '--dbname', 'options_demo', '--tuples-only', '--no-align', '--command', query], env, 20))
                def wait_changed(before, *, new_owner=False):
                    deadline = time.monotonic() + 50
                    while time.monotonic() < deadline:
                        item = heartbeat()
                        changed = item['owner'] != before['owner'] if new_owner else item['heartbeat_at'] > before['heartbeat_at']
                        if changed and item['state'] == 'DISABLED' and not item['virtual_fills_enabled'] and not item['external_orders_enabled']:
                            return item
                        time.sleep(1)
                    raise SmokeFailure('COLLECTOR_HEARTBEAT_NOT_ADVANCING')
                before = heartbeat()
                command(compose + ['stop', 'api'], env, 45)
                wait_changed(before)
                result['checks'].append('collector_heartbeat_advances_without_api_or_phone')
                before = heartbeat()
                command(compose + ['restart', 'market-collector'], env, 60)
                wait_changed(before, new_owner=True)
                result['checks'].append('new_collector_process_resumes_persisted_postgres_state')
                before = heartbeat()
                command(compose + ['stop', 'postgres'], env, 45)
                try:
                    command(compose + ['exec', '--no-TTY', 'market-collector', 'python', '-m', 'app.market_runtime_worker', '--healthcheck'], env, 20)
                except SmokeFailure:
                    pass
                else:
                    raise SmokeFailure('HEALTHCHECK_ACCEPTED_DATABASE_OUTAGE')
                command(compose + ['up', '--detach', '--wait', '--wait-timeout', '90', 'postgres'], env, 150)
                wait_changed(before)
                result['checks'].extend(['database_outage_fails_healthcheck_then_worker_recovers', 'collector_disabled_without_secret_or_approval', 'api_has_no_alpaca_secret_or_transport'])
                result['test'] = 'compose_base_plus_disabled_market_runtime'
                result['market_connection_tested'] = False
            result["status"] = "passed"
        except Exception as exc:
            result["failed_stage"] = stage
            result["error_code"] = str(exc) if isinstance(exc, SmokeFailure) else "INTEGRATION_CHECK_FAILED"
        finally:
            if owned:
                try:
                    if PROJECT_PATTERN.fullmatch(project) is None:
                        raise SmokeFailure("PROJECT_OWNERSHIP_GUARD")
                    command(compose + ["down", "--volumes", "--remove-orphans", "--rmi", "local", "--timeout", "10"], env, 90)
                    if project_resources(project, env):
                        raise SmokeFailure("OWNED_RESOURCES_REMAIN")
                    result["cleanup"] = "owned_resources_removed"
                except Exception:
                    result["status"] = "failed"
                    result["cleanup"] = "cleanup_failed"
                    result["error_code"] = "OWNED_RESOURCE_CLEANUP_FAILED"
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Create and remove a disposable local Docker Compose project")
    parser.add_argument('--market-runtime', action='store_true', help='Include disabled collector and restart/outage checks')
    args = parser.parse_args(argv)
    if not args.run:
        parser.error("--run is required; no Docker project was started")
    result = run_smoke(market_runtime=args.market_runtime)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
