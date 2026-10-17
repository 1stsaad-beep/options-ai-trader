# Bounded server responses — batch60

The personal-server client previously used `http.Response.fromStream` and unrestricted `jsonDecode`. A server response could allocate its entire body/object graph before any report-specific validation. The client now enforces4MiB while receiving bytes, rejects an oversized declared length, cancels the subscription on failure and retains one12-second absolute deadline across headers and body. Late headers are discarded and their stream cancelled. Neither timeout nor size rejection retries a mutation.

JSON preflight applies before graph allocation:4MiB UTF8,500000 values,64 levels, and rejection of duplicate/escaped-equivalent keys. Existing source/account/financial report checks are unchanged. This bounds transport consumption and decoding; it does not close native ledger storage/export/migration limits or guarantee a hostile HTTP library cannot allocate a chunk internally.

Eight new Dart tests cover exact-byte limit with split Arabic UTF8, declared/chunked overflow with cancellation, duplicate/escaped keys, nesting, slow body absolute timeout, and late headers without retry. Source Flutter analyzer/tests are pending the existing CI gate. No APK, provider connection or external notification was sent.
