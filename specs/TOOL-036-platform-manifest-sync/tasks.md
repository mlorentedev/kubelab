---
tags: [spec, tasks, sync, platform, idp]
created: "2026-09-05"
---

# Tasks - TOOL-036-platform-manifest-sync

> TDD order. One task = one focused commit.

## Setup

- [x] Branch created: `feat/1347-sync-platform-json`
- [x] `proposal.md` is complete and acceptance criteria are testable
- [x] No open questions left in `proposal.md`

## Implementation

- [x] [AC1] [AC2] Write failing tests in `tests/test_sync_platform_json.py` for schema conformance, node/service projection, and zero-addressing sanitization.
- [x] [AC1] [AC2] Implement `toolkit/features/platform_manifest.py` to extract and sanitize platform manifest from `common.yaml`.
- [x] [AC3] [AC4] Wire `tk sync platform-json` in `toolkit/cli/sync.py`, add Makefile targets `sync-platform-json` and `sync-platform-json-check`, and wire into drift gate.
- [x] [AC5] Run full test suite, lint, and adversarial review (`dotf review --provider openrouter`).

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by at least one test
- [x] `features.json` verified with executable commands
- [x] Type checks (`mypy`) pass
- [x] Lint (`ruff`, `yamllint`) passes
- [ ] `verification.md` filled in
- [ ] PR opened referencing `Closes #1347`
