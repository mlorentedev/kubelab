---
spec: "ANSIBLE-037-dev-node-gitea-access"
verdict: "PASS"
reviewed_sha: "20310218f3ee293ac853b1443237c5fb5baad33c"
reviewer: "agy/gemini-3.8-flash-high"
date: "2026-11-14"
---

## Adversarial review

**Scope**: ANSIBLE-037-dev-node-gitea-access
**Sources**: specs/ANSIBLE-037-dev-node-gitea-access/{proposal,tasks,verification}.md, git diff 8f3763b3d1157516263921f6319ad116d92a2f4e...HEAD

### Spec and task alignment
- **Acceptance Criteria**:
  - AC1 (Clone & Push / Idempotence): Verified live via `ac1_clone_push_probe.sh` (timestamped push and branch deletion on `personal/resume`), second run reports `changed=0` under `TAGS=gitea`.
  - AC2 (Identity SSOT & Secret Scoping): Verified via static unit tests (`test_dev_node_gitea_identity.py`, `test_dev_node_gitea_agent_key.py`). Identity resolves from `apps.auth.identities.agent`, former identity cleans up from `apps.auth.identities.machine`, and credentials route through the forge's own vault (`gitea_secrets` / `gitea_identity_env: prod`).
  - AC3 (Host-Key Pinning): Verified via `ac3_host_key_probe.sh` (cleared known_hosts drill demonstrating strict rejection without pin, prompt-free batch greeting after reprovisioning) and static test `test_dev_node_gitea_host_key_pin.py`. Drop-in enforces `HostKeyAlgorithms` to the declared key type (`ssh-ed25519`).
  - AC4 (Immediate Fail-Closed Revocation): Verified via `ac4_revocation_probe.sh` (deleting key from admin API immediately fails closed with `Permission denied (publickey)` in <1s; reprovisioning restores access).
  - AC5 / R1 (SSH Transport Feasibility): Settled prior to role implementation via `r1_transport_probe.sh` confirming listening OpenSSH server and publickey rejection.
  - AC6 (Interactive Human Access via Agent Forwarding): Formally withdrawn by owner decision on issue #1075 due to fleet-wide policy (`ssh_hardening` disables agent forwarding). Documented in `proposal.md`, `tasks.md`, `verification.md`, and lesson-740.
- **Tasks Alignment**:
  - All tasks in `tasks.md` are marked `[x]` with concrete evidence dates and references.
  - Verification commands in `features.json` are non-vacuous and align directly with acceptance criteria.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | THEORETICAL | ansible-check-mode | Task `Read the comment on this node's forge key` (`ssh-keygen -lf {{ dev_node_gitea_key_path }}.pub`) runs with `check_mode: false` without a `failed_when` check mode exception. On a completely fresh, unprovisioned node where the key has never been generated, running in `--check` mode would fail because the preceding `ssh-keygen` generation task is skipped during a dry run. | `infra/ansible/roles/dev_node/tasks/main.yml:569-575` compared to line 657 | UNTESTED | code (`infra/ansible/roles/dev_node/tasks/main.yml`) |
| Minor | THEORETICAL | gitea-api | Key lookup on Gitea API `GET /users/{{ item }}/keys?fingerprint=...` does not pass an explicit `limit` parameter. If an identity account accumulated more than Gitea's default page size (30 keys), pagination could omit keys if filtering were evaluated after pagination. In practice, `agent` and `machine` accounts hold only a few machine keys. | Gitea API pagination defaults (`routers/api/v1/user/key.go`) | UNTESTED | code (`infra/ansible/roles/dev_node/tasks/main.yml`) |
| Question | SPECULATIVE | test-drills | `ac3_host_key_probe.sh` fetches `origin master` and validates that `HEAD` is an ancestor of `origin/master`. In isolated feature branches or detached worktrees where remote master has advanced, the probe will refuse to run until master is fetched and merged. | `specs/ANSIBLE-037-dev-node-gitea-access/ac3_host_key_probe.sh:66-71` | `ac3_host_key_probe.sh` | tests |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | A | All acceptance criteria verified; negative paths demonstrated; AC6 cleanly withdrawn per fleet policy. |
| Verification       | A | Comprehensive live hardware drills backed by static unit tests, red-green mutation verified. |
| Scope              | A | Strict adherence to dev_node forge access; out-of-scope probes cleanly relocated. |
| Reliability        | B | Idempotent with changed=0 and loud skip handling; minor theoretical dry-run edge case on fresh nodes. |
| Maintainability    | A | High code readability, thorough architectural comments explaining WHY, and resilient test assertions. |
| Handoff-readiness  | A | Lesson-740 captured in repo docs, contract digests match, ticket updated. |

### Verdict
PASS

### Recommended next steps
- For future maintenance outside the contract set (e.g. in a follow-up hygiene ticket):
  - In `infra/ansible/roles/dev_node/tasks/main.yml`: add `failed_when: _gitea_key_comment.rc != 0 and not ansible_check_mode` to task "Read the comment on this node's forge key" so that dry-runs on brand new nodes pass cleanly.
- `dotf spec archive ANSIBLE-037-dev-node-gitea-access` is **advisable** in the current state.
