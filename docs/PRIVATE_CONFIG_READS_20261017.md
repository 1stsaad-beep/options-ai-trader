# Private configuration reads — batch70

The explicitly configured notification and health token readers already rejected symlinks and nonregular files, but their blocking `open()` could wait indefinitely on a FIFO before reaching `fstat()`. Both now use O_NONBLOCK together with O_NOFOLLOW and reject the unexpected file type immediately. No key discovery, alternate path or relaxed permission rule is added. The health reader also checks the bounded read length, so growth after the initial size check cannot evade the existing4096-character parser guard. Initial file size is still capped at4096 bytes.

Two real child-process tests create disposable FIFOs with no writer and require a prompt sanitized failure; a third simulates growth after stat and proves rejection.1789 full local Python tests pass with zero failures/errors/skips. Source70 CI follows publication. Provider/financial/mobile/native behavior and all approval defaults remain unchanged. No real configuration file, external request, message, deployment or APK was used.

Source69 9a3320901a96ea891a4270890f6d9e3a59d43c8c passed backend39040186145/security39040186162:1786Python, PostgreSQL22/6/10/5/35/4/23 and23Compose. Original source-bound artifacts are verified SHA256/CRC in batch69-ci-index.json. This scoped hardening does not implement the still-missing durable outside monitor loop.

Final scoped acceptance: source70 23f23f40f92347d737b87210ce5ea0bb57e181ee passed backend39040474320/security39040474325 with1789Python, PostgreSQL22/6/10/5/35/4/23 and23Compose. Original artifacts verified SHA256/CRC in batch70-ci-index.json. Historical pending/failure notes above are superseded only by this accepted source; phase one remains PARTIAL.
