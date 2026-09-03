---
spec: "SEC-006-cloud-firewall-for-running-vps"
verdict: "PASS"
reviewed_sha: "33b29d1d321f96c424fa1702455af6bfdc3a8985"
reviewer: "nan/mimo-v2.5"
date: "2026-09-02"
---

## Adversarial review

**Scope**: SEC-006-cloud-firewall-for-running-vps
**Sources**: `specs/SEC-006-cloud-firewall-for-running-vps/{proposal,tasks,verification,features.json}.md`, `git diff master...HEAD` (24 files, +1566/-16), `tests/test_vps_cloud_firewall_is_attached.py`, `infra/terraform/vps-firewall/{main.tf,variables.tf}`, `infra/config/values/common.yaml`, `infra/ansible/playbooks/provision.yml`, `toolkit/cli/infra.py`, `Makefile`

### Spec and task alignment

- **AC1** (allow-list declared once, consumed by both Terraform and Ansible): **met.** `networking.firewall.vps_inbound` in `common.yaml` is the single declaration. The Terraform module reads it via `toolkit infra terraform vps-firewall-tfvars` (renders `.auto.tfvars`). Ansible reads it via `set_fact` in `provision.yml` for the `vps` group. Three consumers all resolve from the same YAML key: the Terraform guard, the traefik-port test, and the Ansible wiring test.
- **AC2** (Terraform plan shows 0 to destroy, no managed server): **met.** `data "hcloud_server"` is a read-only source; `hcloud_firewall_attachment` binds without managing. Precondition asserts `ipv4_address == expected_public_ip`. Validation refuses empty rules, missing SSH, and invalid protocols. Plan output: "2 to add, 0 to change, 0 to destroy."
- **AC3** (port outside allow-list refused at cloud edge): **met.** Port 8080 went from `200 OK` (plaintext HTTP) to `timeout` across the apply, measured from a non-tailnet path confirmed by `ip route get`. 9000 is correctly identified as useless as a probe (#1541 already closed it at Traefik).
- **AC4** (allow-listed ports still work): **met.** SSH, HTTP, HTTPS, K3s API (6443 → 401), and `vpn.kubelab.live` (200) all verified. Tailnet unchanged (`Relay: "kubelab"`, `Online: true`). ICMP impact correctly assessed: no monitor targets VPS public IP with ICMP.
- **AC5** (live guard fails when detached, deleted, or edited out of band): **met.** `TestTheFirewallIsLive` queries the Hetzner API, checks outbound rules, source_ips on every inbound rule, port parsing (including ranges), and bidirectional set comparison. Pre-apply: `FAILED assert []`. Post-apply: `PASSED`. Continuous sentinel: Uptime Kuma `upsideDown: true` on port 8080.
- **AC6** (idempotent): **met.** Re-plan: "No changes. Your infrastructure matches the configuration." Em-dashes in descriptions survive round-trip.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | THEORETICAL | token-extraction | `Makefile` extracts the Hetzner token via `toolkit secrets show ... \| tail -1`. If `toolkit secrets show` ever emits a warning or info line before the token, `tail -1` grabs the wrong line and Terraform silently authenticates with garbage. The same pattern exists for `tf-dns-*` targets — a systemic assumption that stdout is exactly one line. | Code read of `Makefile:1277`. | UNTESTED (Makefile targets have no automated tests) | code (use `--raw` or `--clip` flag if available; or add a length/assertion gate) |
| Minor | THEORETICAL | spec-closure | `tasks.md` closing task `#1557 closed with the change that closed it` is still unticked `[ ]`. This is a process gap, not a code gap — the archive will refuse without it being resolved. | `tasks.md:128`. | N/A | spec-artifacts (tick the closing task with the correct `Closes #N` keyword) |
| Minor | SPECULATIVE | monitoring-sentinel | The Uptime Kuma sentinel covers one port (8080). "Every port not in the allow-list" cannot be enumerated as monitors. The exhaustive complement is the live guard, which nothing schedules (tracked as `#1570`). | Spec explicit: "Deliberately partial" in `tasks.md` and `verification.md`. | N/A (tracked as #1570) | — (accepted scope limit, already ticketed) |

**No Blocker or Major findings.** The two Major findings from the previous review (`agy/gemini-3.1-pro-high`) — outbound rules ignored and `source_ips` ignored — are both fixed in commit `33b29d1d` and verified by mutation M9/M10 assertions in the test source. The Minor tfvars SSH validation type issue is also fixed (`int()` conversion handles YAML-quoted `"22"`).

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | A | All six ACs verified with evidence; negative paths (empty rules, missing SSH, wrong server, out-of-band edits in both directions) covered by validation and mutation tests. |
| Verification       | A | Each criterion has reproducible evidence: plan output, before/after port state, tailnet status, pre/post-apply guard results, mutation test red results (M1/M2/M3/M6). |
| Scope              | A | Diff matches proposal exactly. Incidental corrections (monitoring docstring, DR runbook key extraction, stale monitor cleanup) are documented in `verification.md` and directly caused by the work. |
| Reliability        | A | Terraform preconditions prevent wrong-server attachment; input validation refuses dangerous states; idempotency proven; live guard covers inbound/outbound/sources/ports with clear error messages. |
| Maintainability    | A | Every file is thoroughly commented with WHY, not WHAT. Functions are short. The test file's docstring is a self-contained explanation of the design. Cyclomatic complexity is low throughout. |
| Handoff-readiness  | A | Lesson 417 written. `features.json` has 7 features with verification commands and mutation evidence. Spec closure task is the only pending item. `#1570` tickets the monitoring gap. |

### Verdict
PASS

### Recommended next steps (before archive)
- Close `#1557` with a `Closes #N` keyword referencing the ACs, per `tasks.md:128`. This is the only unticked task and `dotf spec archive` requires it.
- Consider adding `--raw` or an assertion gate to the `toolkit secrets show` token extraction in the Makefile targets (the `tail -1` pattern is shared across `tf-dns-*` and `tf-vps-firewall-*`).
- Archive is **advisable** once the closing task is ticked.
