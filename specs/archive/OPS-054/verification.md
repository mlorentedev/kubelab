---
tags: [spec, verification, templates]
created: "2026-11-01"
---

# Verification - OPS-054

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] AC1 -> `make load-test ENV=staging`, `docs/runbooks/load-test.md`, image pinned at `load_test.image`, digest in results
- [x] AC2 -> `tests/test_load_test.py::TestStaysInStaging`; mutants of the env guard, the host check and `maxRedirects` go red under `make mutate`; `make load-test ENV=prod` refused; the k6 script refused `api.kubelab.live`
- [x] AC3 -> `docs/load-test/2026-11-02-7ccf57f4.{md,json}`
- [x] AC4 -> `infra/load-test/limiter-bypass-route.yaml`, stated in the report; route `NotFound` after both runs
- [x] AC5 -> `docs/load-test/report-2026-11-02.md`
- [x] AC6 -> report, "How staging differs from production"
- [x] AC7 -> #2975, #2977

## Test status

- Test suite: `tests/test_load_test.py` -> 47 passed; CI `Tests` passed on the merged head `b78cf988`
- Manual smoke test: two full runs against staging on 2026-11-02, reported in `docs/load-test/`; `--env prod` and `--env dev` refused with exit 1
- No regressions in existing test suite: yes, per CI. Local failures in six files this change does not touch were not investigated

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- A run stops on a rollout and on an edge restart instead of averaging them in, added after both corrupted early ramps.
- The bypass route lives outside `infra/k8s`, so no overlay syncs it. The static rate-limit coverage test does not scan it; the live one does.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/kubernetes/lesson-696-a-load-tests-limit-can-be-a-limit-nobody-declared.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: a measurement tool, with no structural decision
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: seen in one project

## Archive checklist

- [x] `proposal.md` frontmatter set to `status: archived`
- [x] Folder moved: `specs/OPS-054/` -> `specs/archive/OPS-054/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [x] Promotions above executed (if any)
