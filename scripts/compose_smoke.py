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


def inspect_owned_containers(project: str, containers: list[dict]) -> dict:
    if PROJECT_PATTERN.fullmatch(project) is None:
        raise SmokeFailure("PROJECT_OWNERSHIP_GUARD")
    services = {}
    for container in containers:
        config, state = container.get("Config", {}), container.get("State", {})
        labels = config.get("Labels", {})
        if labels.get("com.docker.compose.project") != project:
            raise SmokeFailure("FOREIGN_CONTAINER_REFUSED")
        service = labels.get("com.docker.compose.service")
        if service not in {"api", "worker", "postgres"} or service in services:
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
        if service in {"api", "worker"}:
            if not container.get("HostConfig", {}).get("ReadonlyRootfs") or config.get("User") in (None, "", "0", "root"):
                raise SmokeFailure("RUNTIME_HARDENING_MISSING")
            values = dict(item.split("=", 1) for item in config.get("Env", []) if "=" in item)
            if any(values.get(key) != value for key, value in {"ENABLE_LIVE": "false", "TRADING_MODE": "paper", "BROKER_PROVIDER": "mock"}.items()):
                raise SmokeFailure("SAFE_MODE_REQUIRED")
            database = urlsplit(values.get("DATABASE_URL", ""))
            if database.scheme != "postgresql" or database.hostname != "postgres" or database.port != 5432 or database.path != "/options_demo":
                raise SmokeFailure("ISOLATED_POSTGRES_REQUIRED")
        services[service] = True
    if set(services) != {"api", "worker", "postgres"}:
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


def run_smoke() -> dict:
    project = "oat-smoke-" + secrets.token_hex(12)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("COMPOSE_") and key not in {"OPTIONS_API_TOKEN", "POSTGRES_PASSWORD"}}
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
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("\n".join(f"{name}={value}" for name, value in private_settings.items()) + "\n")
        compose = ["docker", "compose", "--project-name", project, "--env-file", str(env_file),
                   "--file", str(ROOT / "infra" / "compose.yaml")]
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
            if len(identifiers) != 3 or any(re.fullmatch(r"[0-9a-f]{12,64}", item) is None for item in identifiers):
                raise SmokeFailure("EXPECTED_THREE_CONTAINERS")
            containers = json.loads(command(["docker", "inspect", *identifiers], env, 20))
            inspect_owned_containers(project, containers)
            result["checks"].extend(["three_owned_services_running", "postgres_healthy", "loopback_only_ports", "api_worker_nonroot_readonly", "paper_mock_live_false"])
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
    args = parser.parse_args(argv)
    if not args.run:
        parser.error("--run is required; no Docker project was started")
    result = run_smoke()
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
