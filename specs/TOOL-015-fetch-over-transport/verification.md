---
tags: [spec, verification, templates]
created: "2026-06-21"
---

# Verification - TOOL-015-fetch-over-transport

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] End-to-end fetch from non-admin box -> working kubeconfig -> `kubectl get ns`
- [ ] Idempotent overwrite (0600, no accumulation)
- [ ] Guaranteed teardown: no orphan bridge on injected failure (test)
- [ ] Deterministic known_hosts (no "host key changed", no user known_hosts writes)
- [ ] No hardcoded IPs; pure helpers unit-tested

## Test status

- Test suite: `<command> -> <output>`
- Manual smoke (the point of this spec): `make fetch-kubeconfig ENV=staging` from EGW-LEN029 (non-admin) -> kubeconfig written -> `make connect ENV=staging && kubectl get ns`
- No regressions in TOOL-014 (`tests/test_k8s_connect.py`) after extracting the shared tunnel helper

## Decisions made during implementation

-
-

## Promotion candidates

- [ ] Lesson for `docs/lessons.md`? <yes / no>
- [ ] ADR-worthy? <no — ADR-052 covers it>
- [ ] Pattern candidate? <no>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved to `specs/archive/`
- [ ] Bitácora #733 closed with PR link (ADR-018)
