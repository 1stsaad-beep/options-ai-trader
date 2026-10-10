# V0.4 source provenance

This repository contains the existing Options AI Trader V0.4 source, imported through the authenticated GitHub connector.

- Original source commit: `741d18b0bb3b6100064e4d41ab3fd5d614b9d7f6`.
- Original V0.3 commit: `87a97d80bd73c34f7f166c3cfb8f1ae486764e40`.
- The 17 original commits, branch references and V0.3/V0.4 tags are preserved without rewriting inside `options-ai-trader-v0.4-original.bundle`.
- GitHub import commits have different identifiers. Original history is archived in the bundle, rather than represented as the parent chain of GitHub `main`.
- The source files were imported byte for byte; no broker credentials or private signing keys are included.
- Live trading remains locked. Only MockBroker simulation is supported in this delivery.

## Recover the original history in a separate directory

```sh
git bundle verify repository/options-ai-trader-v0.4-original.bundle
git clone -b v0.4 repository/options-ai-trader-v0.4-original.bundle options-ai-trader-original-history
git -C options-ai-trader-original-history log --all --oneline
```

Do not force-push over GitHub `main`. The bundle can be used later to restore the original branches in a controlled migration without losing subsequent GitHub commits.
