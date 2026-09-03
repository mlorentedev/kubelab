---
spec: "SEC-006-cloud-firewall-for-running-vps"
verdict: "PASS"
reviewed_sha: "bad64c04b61531155cf24d37608d38abb5b8821d"
reviewer: "nan/mimo-v2.5"
date: "2026-09-02"
---

## Adversarial review

**Scope**: SEC-006-cloud-firewall-for-running-vps
**Sources**: `specs/SEC-006-cloud-firewall-for-running-vps/{proposal,tasks,verification}.md`, `git diff master...HEAD` (20 files, +1335 / -13)

### Spec and task alignment

- **AC1** (single SSOT for inbound allow-list): Implemented and verified. `common.yaml` declares `networking.firewall.vps_inbound` once. `provision.yml` reads it for the VPS group via `set_fact`. `toolkit infra terraform vps-firewall-tfvars` renders `.auto.tfvars` from the same key. The SEC-005 traefik guard (`test_traefik_ports_stay_behind_the_firewall.py`) was rewired from `base_system` defaults to `common.yaml`. Mutation M3 (unwire playbook from SSOT) → red. All test paths verified: `test_the_ansible_side_reads_the_ssot_rather_than_its_own_copy` passes.
- **AC2** (plan 0 destroy, no managed server): Plan evidence: `Plan: 2 to add, 0 to change, 0 to destroy` — firewall + attachment only. Server is a `data` source, never a `resource`. Precondition asserts `ipv4_address == expected_public_ip`. Mutation M2 (`data` → `resource`) → red. `test_the_module_does_not_manage_the_server` verifies both the `data` and absence of `resource "hcloud_server"`. The operator read the plan before apply.
- **AC3** (port outside allow-list refused at cloud edge): Verified by consequence. Before apply: `8080/tcp → 200 OK`. After apply: `8080/tcp → timeout`. Path confirmed non-tailnet via `ip route get 162.55.57.175 → via 10.0.0.1 dev wlp1s0`. `9000/tcp` is acknowledged as a useless probe (#1541 already closed it at Traefik). Operator-dependent: cannot independently reproduce the non-tailnet path without the production network.
- **AC4** (all allow-listed ports still work): SSH, 80, 443, 6443 (K3s API, HTTP 401), and `vpn.kubelab.live` (HTTP 200) all verified post-apply. Tailnet: `Relay: "kubelab"`, `CurAddr: ""`, `Online: true`. Pre-apply monitoring audit: 37 Uptime Kuma monitors checked, no monitor targets the VPS's public IP with ICMP, two that reach it use 22 and 443 (both allow-listed). Operator-dependent for post-apply re-verification.
- **AC5** (live guard fails when firewall absent/detached/edited): Two layers, both verified. Static: `TestTheDeclarationIsInternallyConsistent` (5 tests, all pass). Live: `TestTheFirewallIsLive::test_the_live_rules_match_the_ssot` — compares rules bidirectionally (missing + extra). Run before apply: FAILED (`assert []`). Run after: PASSED. Same test, same command, opposite verdict. Mutations M1 (drop 22/tcp), M6 (unescaped `${...}`), M7 (blank server name), M8 (wrong IP) all → red. Continuous sentinel: Uptime Kuma `port` monitor on `162.55.57.175:8080` with `upsideDown: true`, applied via `make monitoring-apply`, confirmed `0 create, 0 edit, 0 delete` on re-run.
- **AC6** (idempotent re-apply): Verified. Re-plan after apply: `No changes. Your infrastructure matches the configuration.` Em-dashes in rule descriptions survive round-trip (no perpetual `~ description` diff).

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | THEORETICAL | secrets | Makefile token extraction pattern (`2>/dev/null \| tail -1`) is shared with `tf-dns-*` targets and works, but if `toolkit secrets show` ever emits multi-line output or changes its format, the assignment captures only the last line. Same risk exists in every other target and has never fired. | code read of Makefile diff | UNTESTED (no Makefile-level test for token propagation) | — (surfaces only; no action recommended) |
| Minor | SPECULATIVE | naming | `features.json` in the spec folder has `"state": "pending"` and `"verification": "echo 'not implemented' && exit 1"` — a template placeholder never updated with real evidence. `dotf spec archive` may or may not parse this; it is harmless but untidy. | code read of `specs/SEC-006-cloud-firewall-for-running-vps/features.json` | N/A | spec artifacts (features.json) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | A | All six ACs verified with evidence (plan output, API before/after, bidirectional rule comparison, mutation tests). Negative paths (missing SSH, wrong server, wrong IP, description interpolation) all caught. |
| Verification       | A | Reproducible commands and outputs for every criterion. Pre-apply vs post-apply comparison for AC3. Bidirectional set comparison for AC5. Mutation tests with named mutations (M1-M3, M6-M8). |
| Scope              | A | Diff matches proposal exactly. All changes trace to an AC or a task. Two incidental corrections documented and scoped (DR runbook sops, toolkit monitoring docstring). Zero unrelated changes. |
| Reliability        | A | Input validation in `variables.tf` refuses empty rules, refuses missing 22/tcp, refuses invalid proto. `precondition` on attachment catches wrong server. Idempotent (AC6 verified). |
| Maintainability    | A | Clear naming, comments explain *why* (not just *what*), module header is load-bearing design documentation. Functions under 40 lines. CC ≤ 10 across all new code. |
| Handoff-readiness  | A | Spec updated in-session (tasks, verification, proposal all current). Lesson written (`lesson-417`). ADR evaluated and correctly declined. Outstanding operator tasks clearly tracked. |

### Verdict
PASS

### Recommended next steps (before archive)
- **Operator-dependent tasks remaining** (not blocking this review, blocking archive):
  - AC2: human reads plan, confirms Hetzner web console reachable, then `make tf-vps-firewall-apply`
  - AC3: verify from non-tailnet path that a port outside allow-list is refused
  - AC4: verify all allow-listed ports still work post-apply (SSH, HTTPS, tailnet)
  - AC6: re-run apply, assert no changes
  - AC5: run `make test-vps-firewall-live` against applied state
- **Spec hygiene** (minor, non-blocking):
  - Update or remove the placeholder `features.json` entry
  - Record plan output and AC3 verification in `verification.md` as evidence (already partially done)
- **Archive**: `dotf spec archive` is advisable once all operator-dependent tasks are complete. This review satisfies the independent review gate.
