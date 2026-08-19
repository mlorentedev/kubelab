---
spec: "ANSIBLE-021-tmux"
verdict: "PASS WITH GAPS"
reviewed_sha: "1f8cf13a71fd487a387e0f8379c88dfc5f5ef463"
reviewer: "nan/deepseek-v4-flash"
date: "2026-08-18"
---

## Adversarial review

**Scope**: ANSIBLE-021-tmux
**Sources**: specs/ANSIBLE-021-tmux/{proposal,tasks,verification}.md, commit 46b9103, current HEAD 1f8cf13

### Spec and task alignment

- The implementation is a single commit (46b9103) adding one line — `tmux` — to `base_packages` in `infra/ansible/roles/base_system/defaults/main.yml`. The diff matches the proposal exactly.
- All tasks in `tasks.md` are marked `[x]` except the archive steps (adversarial review + archive), which are the correct remaining items.
- AC2 (idempotency) is marked `[~]` — accepted rather than done. The spec acknowledges this.
- ace2 is deferred (powered off). The spec acknowledges this.
- The spec was corrected in commit ddbbeea to account for scope drift (rpi3 now runs base_system via #1059, not #817; VPS has unmanaged tmux).
- No `[AGENT-DRAFT]` or `[AGENT-SUGGESTION]` tags remain in any spec file.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|----------|---------|------|---------|----------|---------------------------|--------------|
| Minor | REAL | scope-accuracy | **Spec scope boundary invalidated by unrelated change.** rpi3 was excluded from coverage, but `provision-rpi3.yml:105` now runs `base_system` (adopted via #1059 for firewall reasons), so rpi3 gets tmux while the ticket this spec predicted (#817) is still OPEN. The spec documents this correctly in an inline correction, but the original scope paragraph was wrong for 7 weeks before being caught at archive time. | `git show 3c9629b` (merge of #1059); `provision-rpi3.yml:105` includes `base_system`; #817 is still OPEN per `gh issue view 817` | UNTESTED — no test asserts any scope boundary; the spec's own measurement caught it at archive time | spec (already corrected in `proposal.md`) |
| Minor | THEORETICAL | verification | **AC2 (idempotency) not verified.** Re-running `make provision` to observe `changed: 0` on any host was deliberately skipped. The argument that this proves a property of Ansible's `apt` module rather than of this change is technically sound — the `apt` module is idempotent by design — but the acceptance criterion is not evidenced. A plain `apt-get install -y tmux 2>/dev/null; echo $?` on any host would confirm no regression at negligible cost. | `tasks.md` marks this `[~]` with a detailed rationale; `verification.md` records it as "accepted, not as done" | UNTESTED | verification (add a low-cost idempotency check — e.g. `ssh host 'apt-get install -y tmux 2>/dev/null; echo $?'` returns 0) |
| Minor | THEORETICAL | verification | **ace2 not verified.** 4 of 5 covered hosts return `tmux 3.4`; ace2 is powered off. The deferral is bounded by identical role membership, but the acceptance criterion says "every covered host." ace2's role membership is identical, but the `apt` transaction was never observed on it. | `verification.md` shows the smoke loop output: `ace2: Connection timed out` | UNTESTED | verification (verify when ace2 is powered on, or document the deferral as a formal exception in the AC) |
| Minor | REAL | naming | **Naming inconsistency: `beelink` vs `provision-bee.yml`.** The smoke loop correctly uses `beelink` as the SSH hostname (it resolves in Tailscale). But `make provision NODE=beelink` would fail — the playbook is `provision-bee.yml`, and the Makefile documents `NODE=bee` as the valid option. This doesn't affect the correctness of the installed package, but it means the provisioning path for beelink is visually disconnected from the hostname used in the spec and smoke loop. | `Makefile:56` lists `NODE=bee`; `provision-bee.yml` exists; no `provision-beelink.yml` exists | UNTESTED | docs (either rename `provision-bee.yml` to `provision-beelink.yml` or add a comment in the spec noting the alias) |
| Minor | THEORETICAL | tests | **No test coverage for `tmux` in `base_packages`.** No test asserts that `tmux` appears in the role's defaults. The spec argues a permanent assertion pinning one line of a package list is a "change-detector" and not valuable. This is a defensible position, but the absence means a future refactor or accidental deletion of the `tmux` line would not be caught by CI. | `grep -rn 'tmux\|base_packages' tests/` returns no matches | UNTESTED | tests (optional — a simple `grep -q 'tmux' roles/base_system/defaults/main.yml` in a bats test) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness | B | All criteria met on happy path; AC2 accepted rather than verified; ace2 deferred; no defects in the code itself |
| Verification | B | Evidence covers measurable outputs (git show, ssh loop) but AC2 is not evidenced and ace2 is unverified; the self-awareness of gaps is itself documented |
| Scope | A | Diff is exactly one insertion in `base_packages`; no scope creep; spec corrections for scope drift are documented, not hidden |
| Reliability | B | One-line package addition; apt handles idempotency; no port/service risk; but AC2 idempotency not independently confirmed |
| Maintainability | A | One-line change, clear naming, well-commented defaults file; no dead code |
| Handoff-readiness | B | Spec updates included (corrections, verification.md, promotion candidates); lessons captured; but the spec sat unreconciled for 7 weeks before being caught |

### Verdict
**PASS WITH GAPS**

The implementation is correct: a single-line YAML addition that places `tmux` into `base_packages` for every host that runs the `base_system` role. The diff is verified against the working tree, and 4 of 5 covered hosts return `tmux 3.4` on `ssh` smoke. The Jetson exclusion is confirmed. The code is trivially correct and carries zero blast radius.

The gaps are in *verification completeness* and *scope durability*:

1. **AC2 (idempotency)** is accepted on trust in Ansible's `apt` module rather than measured. The logic is sound, but the criterion is not evidenced.
2. **ace2** is deferred (powered off, on-demand node). Identical role membership makes the risk negligible, but the acceptance criterion says "every covered host."
3. **Scope drift** (rpi3 now covered by a different change, VPS has unmanaged tmux) is correctly documented in the spec, not hidden. But it demonstrates that a spec's "not covered by this" is a statement about a date, not a durable guarantee.

These are Minor findings with no Blocker or Major issues. The rubric grades are all B or above, confirming the change is solid. The gaps are transparently documented in the spec itself.

### Recommended next steps (before archive)

- **Accept the gaps as-is** — the gaps are clearly documented, the risk is negligible, and the change is correct. The spec's own verification.md is honest about every gap. Running `dotf spec archive ANSIBLE-021-tmux` is **advisable** with the current review.
- **Optional: add a low-cost idempotency check** — `for h in ace1 ace2 aws1 beelink rpi4; do ssh "$h" 'apt-get install -y tmux 2>/dev/null; echo "EXIT: $?"'; done` on a maintenance window would close the AC2 gap at near-zero cost.
- **Optional: verify ace2 when powered on** — the next time ace2 is provisioned, re-run the smoke loop.
- **The naming inconsistency (beelink vs provision-bee.yml) is a pre-existing issue** — not a blocker for this spec, but could be ticketed separately if desired.
