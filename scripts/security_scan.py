"""Redacted, offline secret-pattern scan of this Git repository.

This is a bounded review aid, not a full vulnerability or credential audit.
No matching secret, source line or credential hash is printed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import subprocess


RULES = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "openai_key": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{24,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{20,}\b"),
    "credential_url": re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s/:@]+:([^\s/@]{8,})@"),
}
ASSIGNMENT = re.compile(r'''(?im)\b(?:[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|ACCESS_KEY))\s*[:=]\s*["']([^"'\r\n]{24,})["']''')
SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".jks", ".keystore", ".mobileprovision"}
SENSITIVE_NAMES = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "key.properties", ".env"}
ARCHIVE_SUFFIXES = {".zip", ".gz", ".tgz", ".tar", ".7z", ".bundle", ".apk", ".ipa"}
# Exact non-production fixtures are exempt only in tests or workflow fixtures.
# Never exempt all strings in test files, and never exempt real token prefixes.
FIXTURE_TOKENS = frozenset({
    # Literal introduced in e579947's in-process TestClient; never a provider key.
    # Exact-value, test-path exemption also covers that reachable historical blob.
    "fixture-only-token-not-a-secret",
    "test-token-at-least-32-characters-long",
    "v03-token-longer-than-32-characters",
    "independent-review-token-32-characters",
    "adversarial-review-local-token-32-characters",
    "test-automation-token-never-production",
    "ci_integration_only",
})
# Reviewed baseline disposable CI password and local documentation placeholder.
# Exact path + digest exceptions do not exempt an arbitrary replacement value.
FIXTURE_CREDENTIAL_DIGESTS = {
    # Reviewed batch66 in-process ASGI fixture; never issued or used as a real credential.
    # Exact path/value also covers its reachable original; no history is removed.
    "backend/tests/test_alert_receiver.py": "2d5b510ba44491734f8b1fcabf206f0a9da3907114470f27daa99793b681745f",
    ".github/workflows/checks.yaml": "3e17fbc6521e18184bbdee3883b7046707f8f112a44487514194c01711d3d628",
    "docs/DATABASE.md": "edc57f2c6a1f6ad3c9325288a57b74883ed4b9b24d4f00ff23df7808e221c75a",
    "docs/DATABASE_V03.md": "edc57f2c6a1f6ad3c9325288a57b74883ed4b9b24d4f00ff23df7808e221c75a",
    "docs/archive/v0.3/DATABASE_V03.md": "edc57f2c6a1f6ad3c9325288a57b74883ed4b9b24d4f00ff23df7808e221c75a",
}
# Historical generator expression in f8d59cb was source code, not a secret:
# the matched value is exactly whitespace + secrets.token_hex(32) + whitespace.
# Keep history intact and exempt only that expression in its original path.
GENERATOR_EXPRESSION_DIGESTS = {
    "scripts/compose_smoke.py": "04748d3e46f85073035879bbda364c06b1bf8f4dd70cbe0f1e4f2b2066d90ffd",
}


def _fixture(path: str, value: str) -> bool:
    return ((value in FIXTURE_TOKENS and path.startswith(("backend/tests/", "mobile/test/", ".github/workflows/")))
            or FIXTURE_CREDENTIAL_DIGESTS.get(path) == hashlib.sha256(value.encode()).hexdigest()
            or GENERATOR_EXPRESSION_DIGESTS.get(path) == hashlib.sha256(value.encode()).hexdigest())


def _placeholder(value: str) -> bool:
    return value.startswith(("${", "REPLACE_WITH_", "<")) or value in {"example", "placeholder"}


def _entropy(value: str) -> float:
    return -sum((count / len(value)) * math.log2(count / len(value)) for count in Counter(value).values()) if value else 0


def scan_text(path: str, content: str, ref: str = "working-tree") -> list[dict]:
    findings = []
    for rule, regex in RULES.items():
        for match in regex.finditer(content):
            value = match.group(1) if rule == "credential_url" else match.group(0)
            if rule == "credential_url" and (_placeholder(value) or _fixture(path, value)):
                continue
            findings.append({"path": path, "ref": ref, "line": content.count("\n", 0, match.start()) + 1, "rule": rule})
    for match in ASSIGNMENT.finditer(content):
        value = match.group(1)
        if _fixture(path, value) or _placeholder(value):
            continue
        if value in FIXTURE_TOKENS:
            findings.append({"path": path, "ref": ref, "line": content.count("\n", 0, match.start()) + 1, "rule": "fixture_credential_outside_tests"})
        elif len(set(value)) >= 16 and _entropy(value) >= 3.5:
            findings.append({"path": path, "ref": ref, "line": content.count("\n", 0, match.start()) + 1, "rule": "high_entropy_secret_assignment"})
    return findings


def path_findings(path: str, ref: str) -> list[dict]:
    name = PurePosixPath(path).name.lower()
    suffix = PurePosixPath(path).suffix.lower()
    sensitive = name in SENSITIVE_NAMES or suffix in SENSITIVE_SUFFIXES
    sensitive |= name.startswith(".env.") and name not in {".env.example", ".env.template", ".env.sample"}
    return [{"path": path, "ref": ref, "line": None, "rule": "sensitive_file_path"}] if sensitive else []


def _git(repository: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repository), *args], capture_output=True, check=False)
    if result.returncode:
        raise ValueError("Git repository inspection failed")
    return result.stdout


def scan_repository(repository: str | Path, all_history: bool = False, max_bytes: int = 8 * 1024 * 1024) -> dict:
    repository = Path(repository).resolve()
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("Invalid maximum scan size")
    top = Path(_git(repository, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if top != repository:
        raise ValueError("Scan must explicitly target the repository root")
    report = {"format_version": 1, "scope": "tracked_working_tree_and_all_reachable_history" if all_history else "tracked_working_tree",
              "files_scanned": 0, "history_blobs_scanned": 0, "history_commits": 0,
              "findings": [], "skipped": [], "limitations": [
                  "Pattern matching does not prove absence of secrets or vulnerabilities.",
                  "Untracked and ignored files, unreachable Git objects, submodules and archived/binary contents are not scanned.",
                  "No remote secret validation, dependency vulnerability lookup or paid service is used."]}

    def inspect(path: str, data: bytes, ref: str, history=False):
        report["findings"].extend(path_findings(path, ref))
        if len(data) > max_bytes:
            report["skipped"].append({"path": path, "ref": ref, "reason": "size_limit"})
            return
        if PurePosixPath(path).suffix.lower() in ARCHIVE_SUFFIXES:
            report["skipped"].append({"path": path, "ref": ref, "reason": "opaque_archive"})
            return
        try:
            if b"\0" in data:
                raise UnicodeError()
            content = data.decode("utf-8")
        except UnicodeError:
            report["skipped"].append({"path": path, "ref": ref, "reason": "binary_or_non_utf8"})
            return
        report["findings"].extend(scan_text(path, content, ref))
        report["history_blobs_scanned" if history else "files_scanned"] += 1

    for raw_path in _git(repository, "ls-files", "-z").split(b"\0"):
        if not raw_path:
            continue
        path = raw_path.decode("utf-8")
        file = repository / path
        if file.is_symlink():
            report["findings"].append({"path": path, "ref": "working-tree", "line": None, "rule": "unscanned_symlink"})
            continue
        if not file.exists():
            report["skipped"].append({"path": path, "ref": "working-tree", "reason": "tracked_file_deleted"})
            continue
        if file.stat().st_size > max_bytes:
            report["findings"].extend(path_findings(path, "working-tree"))
            report["skipped"].append({"path": path, "ref": "working-tree", "reason": "size_limit"})
            continue
        inspect(path, file.read_bytes(), "working-tree")
    if all_history:
        seen = set()
        commits = _git(repository, "rev-list", "--all").decode().splitlines()
        report["history_commits"] = len(commits)
        for commit in commits:
            for row in _git(repository, "ls-tree", "-r", "-z", commit).split(b"\0"):
                if not row:
                    continue
                metadata, raw_path = row.split(b"\t", 1)
                mode, kind, oid = metadata.decode().split()
                path = raw_path.decode("utf-8")
                if kind != "blob":
                    report["skipped"].append({"path": path, "ref": commit, "reason": "submodule"})
                    continue
                identity = (oid, path)
                if identity in seen:
                    continue
                seen.add(identity)
                if mode == "120000":
                    report["findings"].append({"path": path, "ref": commit, "line": None, "rule": "unscanned_symlink"})
                    continue
                size = int(_git(repository, "cat-file", "-s", oid))
                if size > max_bytes:
                    report["findings"].extend(path_findings(path, commit))
                    report["skipped"].append({"path": path, "ref": commit, "reason": "size_limit"})
                    continue
                inspect(path, _git(repository, "cat-file", "blob", oid), commit, history=True)
    report["status"] = "findings_require_review" if report["findings"] else "no_matching_patterns_found"
    report["finding_count"] = len(report["findings"])
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--all-history", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = scan_repository(args.repository, args.all_history)
    except (ValueError, OSError, UnicodeError):
        print(json.dumps({"status": "scan_failed", "error": "Repository could not be inspected safely"}))
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 1 if result["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
