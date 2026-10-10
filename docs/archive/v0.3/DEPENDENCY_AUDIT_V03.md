# Dependency vulnerability audit — V0.3

Run date: 2026-10-09. Tool: pip-audit 2.10.1 in an isolated scratch virtual environment.

Actual command: `python -m pip_audit --no-deps --disable-pip -r backend/requirements.lock -f json -o docs/evidence/v03-dependency-audit.json`

Initial result: exit code 1; 24 explicitly locked distributions checked, 0 skipped, 12 advisory rows affecting Starlette 0.48.0. The advisory service returned duplicate entries: these are **6 distinct vulnerability IDs**, not 12 distinct CVEs.

| ID | CVE | Advisory | Fixed version |
| --- | --- | --- | --- |
| PYSEC-2026-1942 | CVE-2025-62727 | [official advisory](https://github.com/advisories/GHSA-7f5h-v6xp-fcq8) | 0.49.1 |
| PYSEC-2026-161 | CVE-2026-48710 | [official advisory](https://github.com/advisories/GHSA-86qp-5c8j-p5mr) | 1.0.1 |
| PYSEC-2026-2281 | CVE-2026-48818 | [official advisory](https://github.com/advisories/GHSA-wqp7-x3pw-xc5r) | 1.1.0 |
| PYSEC-2026-2280 | CVE-2026-48817 | [official advisory](https://github.com/advisories/GHSA-x746-7m8f-x49c) | 1.1.0 |
| PYSEC-2026-249 | CVE-2026-54283 | [official advisory](https://github.com/advisories/GHSA-82w8-qh3p-5jfq) | 1.3.1 |
| PYSEC-2026-248 | CVE-2026-54282 | [official advisory](https://github.com/advisories/GHSA-jp82-jpqv-5vv3) | 1.3.0 |

The product API does not currently use StaticFiles, FileResponse, request.form(), or HTTPEndpoint subclasses, and bearer authorization does not rely on reconstructed request URLs. This limits applicability of several findings; it does not turn a vulnerable dependency into a patched dependency.

Recommended remediation: upgrade Starlette to at least 1.3.1 (the maximum fixed version reported across these advisories), rerun the complete backend tests and HTTP smoke, and rerun the audit. FastAPI 0.143.0 installed metadata specifies starlette>=0.46.0 with no upper version bound. Compatibility still requires actual testing.

## Remediation and verified rescan

The project owner upgraded the actual runtime and pinned product dependency to **Starlette 1.7.0** in requirements.lock and pyproject.toml. The audit reviewer did not change the runtime environment or product dependencies.

The same audit command was rerun against the updated requirements.lock, writing `docs/evidence/v03-dependency-audit-after.json`. Actual result: **exit code 0; 24 locked packages checked; 0 skipped; 0 known vulnerability records reported**. Starlette 1.7.0 is present in the rescan evidence. The original result is preserved in `docs/evidence/v03-dependency-audit-before.json` (and the original initial filename). Application regression tests after the upgrade are recorded by the owner in the final test report.

The six distinct findings above are therefore remediated for the final pinned dependency set according to this audit service at scan time. This is a dependency-advisory check, not a guarantee that undisclosed vulnerabilities do not exist.

Scope limits: --disable-pip/--no-deps audits the 24 pinned entries directly; it does not resolve missing transitive dependencies, verify package integrity/hashes, audit the operating system, Flutter/Dart packages, Android libraries, or application logic. No zero-vulnerability or production-safety claim follows from this initial scan.
