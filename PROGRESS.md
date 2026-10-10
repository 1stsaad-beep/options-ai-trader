# Progress — recovery/v1.0-20261011

## Batch 0: recovery checkpoint

- Base: 3d35475cd92058f8470d6f81826aaa4a16f587b1 (latest saved RC2).
- Verified five original branch heads, RC2 ancestry (17 commits), 33 workflow runs and current deliverable artifact metadata.
- Preserved existing RECOVERY_STATUS.md and appended this session's limitations.
- No code changes or test reruns in this documentation-only batch.
- Remote branch created successfully; checkpoint commit `cd990434a2f3e0066953ae1df418140d544bfcbe` was read back from GitHub successfully before the next batch.

## Next batch

Restore exact saved source, verify artifact logs/counts/signatures and inspect requirements and critical safety tests. Fix evidenced gaps in small tested commits. Completion remains unclaimed.

## Batch 1: recovered evidence and critical baseline

- Reconstructed exact RC2 source tree and remote commit identities from verified Git objects and existing history bundles; Git fsck reported no missing or corrupt reachable objects. Old checkout and all recovered objects retained.
- Inventoried all 33 workflow runs and all artifacts returned by their run endpoints. No releases exist.
- Downloaded and CRC-checked RC2 Android/iOS and backend/Compose/security artifacts. APK SHA-256 matches CI; CI apksigner verifies v2 signature with temporary development key.
- Verified historical RC1 Python 537, current RC2 Python 625, Flutter 142 on each platform; zero failures/skips. PostgreSQL backup/restore 10 checks and Compose 12 checks passed.
- Re-ran the existing 51 critical selected Python cases locally: all passed. Exact command, JUnit and output retained.
- No application code changed in this batch. Evidence is in docs/evidence/recovery-20261011.
- Next: failure-injection review of optional analysis versus protective exits; then current delivery reports.
