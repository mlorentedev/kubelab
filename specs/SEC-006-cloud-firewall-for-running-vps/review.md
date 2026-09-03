---
spec: "SEC-006-cloud-firewall-for-running-vps"
verdict: "PASS"
reviewed_sha: "d0f15aaf0f234c545b30752cb870337c5529e821"
reviewer: "agy/gemini-3.1-pro-high"
date: "2026-09-02"
---

## Adversarial review

**Scope**: SEC-006-cloud-firewall-for-running-vps
**Sources**: `specs/SEC-006-cloud-firewall-for-running-vps/{proposal,tasks,verification}.md`, `git diff origin/master...HEAD`

### Spec and task alignment
- **AC1** (allow-list is declared once and wired to Terraform and Ansible) is met. `provision.yml` pulls `firewall_allowed_ports` from the SSOT for the `vps` group.
- **AC2** (Terraform module does not manage the server, destroys 0) is met. Validated by preconditions and data lookup.
- **AC3/AC4** (cloud edge behavior) were verified via live testing by the operator as documented in `verification.md`.
- **AC5** (live guard fails when detached, deleted, or edited out of band) is fully met. The guard strictly asserts zero outbound rules (preventing egress lockout) and exact matches on `source_ips` for inbound rules (preventing source-narrowing lockout), fixing the previous review's findings.
- **AC6** (idempotency) is proven by the output shown in `verification.md`.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | THEORETICAL | test | If a port range (e.g. "8000-9000") is ever added to the SSOT in the future, the live guard's `int(port)` cast will throw a `ValueError` and crash the test suite instead of failing gracefully. | Code read in `tests/test_vps_cloud_firewall_is_attached.py`. | UNTESTED | tests |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | A | All acceptance criteria verified, negative paths (out-of-band edits) are rigorously covered. |
| Verification       | A | Evidence covers criteria and confirms the running state; the live guard asserts the complete live rule shape. |
| Scope              | A | Diff matches proposal exactly; no scope creep. |
| Reliability        | A | Terraform preconditions prevent attachment to the wrong machine, and the live guard comprehensively verifies the running firewall. |
| Maintainability    | A | Code is well-commented and tests provide clear explanations; previous fragility in tfvars generation is resolved. |
| Handoff-readiness  | A | Lesson captured (417) and clear documentation on findings. |

### Verdict
PASS

### Recommended next steps (before archive)
- `dotf spec archive` is advisable in the current state.
