---
spec: "ADR028-004-classify-stateful-service-placement"
verdict: "PASS WITH GAPS"
reviewed_sha: "00854de2c4d0e1c85539057ba178d506283a0069"
reviewer: "agy/gemini-3.1-pro-high"
date: "2026-10-10"
---

## Adversarial review

**Scope**: ADR028-004-classify-stateful-service-placement
**Sources**: `specs/ADR028-004-classify-stateful-service-placement/{proposal,tasks,verification}.md`, `git diff de1584131b4c92323cd7a0a65a3afcf06b7eaae5...HEAD` (focused on the 4 PRs for this spec)

### Spec and task alignment
- **AC1** (ADR emits classification): Met. ADR-061 created and fields verified by `features.json` f1.
- **AC2** (Static test for missing classification): Met. Gate implemented, proven red-to-green, and extended with the duplication clause.
- **AC3** (Kustomize/e2e green after retirement): Met. Both overlays render clean; staging e2e passed. (MinIO retired via OPS-023).
- **AC4** (Emptiness evidence before deletion): Partial. Prod and staging Gitea captured correctly. Staging MinIO wasn't captured before OPS-023 deleted it. This is a known, tracked gap.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | Spec/Process | AC4 for staging MinIO wasn't met prior to its removal in OPS-023. | Noted in `verification.md` and `features.json` f5. | UNTESTED | spec |
| Minor | REAL | Code Quality | Cyclomatic complexity for `classification_problems` in `test_stateful_service_classification.py` is 11, exceeding the <= 10 limit from the skill rubric. | `radon cc` reports `130:0 classification_problems - C (11)` | `tests/test_stateful_service_classification.py` | code |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | Criteria met on happy path; AC4 missing evidence for MinIO is a process gap. |
| Verification       | B | Evidence proves criteria, but MinIO AC4 capture was lost to a superseding PR. |
| Scope              | A | Diff matches proposal exactly; no scope creep in the spec's PRs. |
| Reliability        | A | Addressed tailscale boot race condition robustly with systemd unit. |
| Maintainability    | B | Acceptable structure with CC 11 in `classification_problems`. |
| Handoff-readiness  | A | Spec updates included and accurate; lessons documented. |

### Verdict
PASS WITH GAPS

### Recommended next steps
- Acknowledge the AC4 gap for MinIO as superseded by OPS-023 in `verification.md` (disposition it).
- Consider refactoring `classification_problems` in `tests/test_stateful_service_classification.py` to reduce cyclomatic complexity to <= 10.
