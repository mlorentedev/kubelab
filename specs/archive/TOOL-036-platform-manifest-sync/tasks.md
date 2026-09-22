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
- [x] [AC5] Run full test suite and lint. Coverage of `platform_manifest.py` is **100%** (22 tests), which is what AC5 asks for — it was 96% while this box was ticked.
- [x] [AC5] Pass an adversarial review from `harness/reviewer-pool.json` via `dotf spec review`. **Not `dotf review --provider openrouter`** — that is a different command and produces no `review.md`, which is the file the archive gate reads. This box was originally ticked with no review on the branch at all. Four runs: FAIL (`nan/deepseek-v4-flash`, `bfa19d68`), FAIL (`agy/gemini-3.1-pro-high`, `6a885062`), a launch that died on quota with no artifact, and finally **PASS-WITH-GAPS** (`nan/deepseek-v4-flash`, `521f5cc3`) — see `review.md`. Two of its REAL Minors were fixed in `46377aeb`; the third is recorded below.

## Gaps carried past the archive

The passing verdict was PASS-WITH-GAPS, so these are open by construction rather than overlooked:

- **`compute_total_services` returns `len(stg) + len(prd) + 2`.** The `+2` was introduced in `ba1a2dd6` to keep the derived figure at 35 — the literal this change set removed. Removing it moves a number published on a public page (33, or 39 if the discarded `shared` table belongs in it); which is correct is a product decision, not a cleanup. **Decided 2026-09-22: 39, with no offset** — `shared` is counted because the manifest lists those services beside the total. The `+2` and its local are gone. Note this moves kubelab's `platform.json`, not the public page: `web` still ships its own hand-written copy (see the next gap).
- **`source_commit` is a blob hash of kubelab's `common.yaml`, and `web` renders it as a link to a commit in the `web` repo** (`site/src/components/LabProvenance.astro:27`). Not triggered today because `web` ships its own hand-written `platform.json`, but the link 404s the moment `web` consumes this producer. `web`'s own test asserts `/^[0-9a-f]{7,40}$/`, which a blob hash satisfies — so `web` stays green while the link silently breaks. Needs a change in the `web` repo, out of scope here.
- **`project_services` iterates the static `SERVICE_CATALOG_DEFAULTS`.** A service declared in the SSOT but absent from that catalog is silently omitted — not leaked, just missing. "Dynamic" covers field overrides, not service discovery.
- **A zero-addressing violation raises `ValueError` uncaught through `sync()`**, so the CLI prints a traceback. Fails closed (non-zero exit, nothing written), so it is UX rather than safety.

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by at least one test
- [x] `features.json` verified with executable commands
- [x] Type checks (`mypy`) pass
- [x] Lint (`ruff`, `yamllint`) passes
- [x] `verification.md` filled in
- [x] PR opened referencing `Closes #1347` — #1689, currently draft pending the review above
