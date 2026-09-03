---
spec: "SEC-006-cloud-firewall-for-running-vps"
verdict: "FAIL"
reviewed_sha: "6eb60be2452f31066c79c80a053f4ddf374eb237"
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
- **AC5** (live guard fails when detached, deleted, or edited out of band) is partially met, but contains a significant gap regarding the types of out-of-band edits that will fail the guard.
- **AC6** (idempotency) is proven by the output shown in `verification.md`.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL | live-guard | The live guard ignores `out` rules (`if direction != "in": continue`), allowing a malicious or accidental out-of-band outbound rule to pass without failing the test. Since egress is unrestricted by default and assumed so by the system, an unexpected outbound rule could break the cluster. | Code read of `tests/test_vps_cloud_firewall_is_attached.py::TestTheFirewallIsLive` (`_ssot_rules` parser). | `tests/test_vps_cloud_firewall_is_attached.py::TestTheFirewallIsLive` | tests |
| Major | THEORETICAL | live-guard | The live guard ignores `source_ips` when extracting attached rules, checking only `port` and `protocol`. An out-of-band edit restricting an inbound rule (e.g., 22/tcp) to a specific IP will pass the guard, defeating its purpose to detect unauthorized modifications that could lock operators out. | Code read of `tests/test_vps_cloud_firewall_is_attached.py::TestTheFirewallIsLive`. | `tests/test_vps_cloud_firewall_is_attached.py::TestTheFirewallIsLive` | tests |
| Minor | SPECULATIVE | tfvars-validation | `toolkit infra terraform vps-firewall-tfvars` validates SSH presence using `r.get("port") == 22`. If the YAML defines the port as a string (e.g. `"22"`), this check evaluates to `False`, failing safely but confusingly. | Code read in `toolkit/cli/infra.py`. | UNTESTED | code |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | C | The negative path (guard against out-of-band edits) misses substantial edits like outbound rules and `source_ips` restrictions. |
| Verification       | B | Evidence covers criteria and confirms the running state, but the live guard itself leaves gaps in automated verification. |
| Scope              | A | Diff matches proposal exactly; no scope creep. |
| Reliability        | B | Terraform preconditions prevent attachment to the wrong machine, but live guard reliability is partially degraded. |
| Maintainability    | B | Code is well-commented and tests provide clear explanations; minor fragility in tfvars python type checking. |
| Handoff-readiness  | A | Lesson captured (417) and clear documentation on findings. |

### Verdict
FAIL

### Recommended next steps (before archive)
- Update `test_the_live_rules_match_the_ssot` (or the API response parser) to assert that there are zero `out` rules present in the attached firewall.
- Update the live guard rule parser to include and verify the `source_ips` array for each inbound rule against the `0.0.0.0/0` and `::/0` expectation defined in the Terraform module.
- Fix the integer parsing in `tf_vps_firewall_tfvars` during validation (`int(r.get("port", 0)) == 22`).
