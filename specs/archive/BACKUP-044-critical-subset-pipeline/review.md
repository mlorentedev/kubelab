---
spec: "BACKUP-044-critical-subset-pipeline"
verdict: "PASS"
reviewed_sha: "eb34e6059af5f6201d549452fabe3b6e1107132a"
reviewer: "nan/deepseek-v4-flash"
date: "2026-08-24"
---

## Adversarial review

**Scope**: BACKUP-044-critical-subset-pipeline — the critical-subset (node-path) backup pipeline: restic to Cloudflare R2, driven from Ansible, four nodes, two trigger models.
**Sources**: `specs/BACKUP-044-critical-subset-pipeline/{proposal,tasks,verification}.md`; implementation in `infra/ansible/roles/{node_backup,node_notify}/`, `infra/ansible/playbooks/{backup,backup-node,backup-schedule}.yml`, `infra/config/values/common.yaml` (`backup.sources` / `backup.r2`), `toolkit/features/{backup_destination,r2_backup_health}.py`, `toolkit/features/secrets_manager.py`, `infra/config/uptime-kuma/{monitors,tags}.json`. No single PR: the change is merged to `master` across the #1112–#1353 series; reviewed at `eb34e6059` (HEAD == master).

### Spec and task alignment

- All nine acceptance criteria (AC1–AC9) are demonstrated in `verification.md` with dated, timestamped evidence — injections, a real smart-plug power cycle, a timer-stop that paged at the predicted instant, a Gitea restore that booted, and R2 snapshot listings read from the workstation. The re-synced evidence index (2026-08-23) agrees with the dated sections underneath.
- Every implementation task in `tasks.md` is `[x]`; the required Part 0 gating risks (R-A/R-B/R-C) were settled by on-device measurement, two of which changed the design (Before=docker.service, not the compose unit; `pvc` source type).
- Proposal AC1's re-scope (node-path consumers only — the PVC class moved to BACKUP-046/#1111) is consistent between proposal, tasks, verification and the code; Authelia/n8n joined through the declared `pvc` mechanism rather than silently.
- No `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tags remain in any spec file. No `review: waived` declared.
- Verified by running, not reading: `1391 passed, 14 skipped, 142 deselected`, 253s (unit suite, `-m "not e2e and not infra"`); the 140 backup-focused unit tests pass; rendered capture/ship scripts for all four nodes from the real SSOT pass `bash -n`; `yamllint` clean on the role/playbooks; mutation edit removing a source's `sqlite:` key fails loudly under StrictUndefined (test I ran, then reverted); AC8 grep confirms zero `minio:9000` consumers in the pipeline (the only occurrence is a comment).

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | spec/common.yaml drift | The "DEFERRED, deliberately" comment under `backup.sources.vps.headscale` (common.yaml:1190–1197) still says Authelia "need[s] the `pvc` source type" and that both it and postgres "currently have a copy via the PVC CronJob; it is in-cluster, so it is not offsite". Authelia has been a declared `pvc` source since #1236 and was restored from R2 on 2026-08-22 (verification.md lists `/opt/node-backup/staging/authelia/db.sqlite3` and `authelia/db.sqlite3 integrity=ok`). A reader of the SSOT is told the most valuable state has no offsite copy when it demonstrably does. Comment predates #1236 and was never updated; nothing flags the contradiction. | `git blame` puts the comment at #1112 (2026-08-15), unchanged; authelia declared at common.yaml:1169–1172; verification.md 2026-08-22 restore transcript | UNTESTED — `test_the_retired_and_deferred_pvcs_stay_out` checks postgres/grafana/crowdsec/minio/loki absence but not the stale prose | spec (common.yaml comment) |
| Minor | THEORETICAL | SSOT duplication | The restic repository URL is expressed twice in the SSOT: the role writes `backup.r2.repo_prefix/<inventory_hostname>` (defaults/main.yml), the coverage/verify-restic readers derive `s3:{endpoint}/{bucket}/<hostname>` (backup_destination.repo_url). Any bucket/endpoint edit that misses `repo_prefix` makes writer and reader disagree. Both failure directions are loud (coverage reports UNCOVERED), never silent, which is why this is Minor — but nothing pins the two expressions equal. | common.yaml:1102–1107 (endpoint/bucket vs repo_prefix literal); `repo_url()`; no test asserts `repo_prefix == f"s3:{endpoint}/{bucket}"` | UNTESTED — add an equality assertion to test_backup_destination.py | tests (or derive repo_prefix from endpoint+bucket) |
| Minor | THEORETICAL | AC6 anti-omission half | The live "present on disk but absent from the SSOT" direction enumerates only Docker volumes (`docker volume ls`). New bind-mount state — exactly Gitea's own shape, the defect this spec exists to fix — is invisible to it. PVCs are covered by declaration; the blind spot is future bind mounts. Documented in the test docstring rather than silent. | tests/infra/test_backup_coverage.py `test_no_undeclared_docker_volume` queries volumes only; beelink's gitea is a `path:` source invisible to that query | named test covers volumes; UNTESTED for bind mounts | tests |
| Minor | THEORETICAL | robustness | `backup.sources` service keys are interpolated into bash variable names (`SRC_DIR_<key>`) and staging paths. A key containing characters outside `[A-Za-z0-9_]` (e.g. `uptime-kuma`) renders a capture script that only breaks at runtime, loudly (set -e), rather than at apply time. All current keys are clean identifiers; no schema or naming invariant guards the charset. Mutation-checked: a key `"authelia x"` renders without error. | my render mutation (key with a space) produced no StrictUndefined error; test_backup_sources has no identifier invariant | UNTESTED — add an identifier assertion to test_backup_sources.py | tests |
| Question | SPECULATIVE | AC5 evidence | "a snapshot exists from before the shutdown" is supported inferentially (hourly-while-up cadence) — verification.md quotes only the post-boot snapshots (beelink 06:51Z, rpi4 06:50Z, read 06:54Z). Boot-ordering (capture before docker.service), the receipt read-back and the real power cycle are all evidenced; a pre-cut R2 listing for beelink is not quoted. Almost certainly true (the node was up for hours before the 04:47Z cut), but the criterion's first half rests on inference rather than a printed snapshot. | verification.md AC9/AC5 sections: coverage output shows post-boot times only; no pre-04:47Z snapshot listed anywhere | — | spec (verification.md one-line pre-cut listing, or operator confirmation) |
| Minor | THEORETICAL | capacity | rpi3 `MemoryMax=128M` has ~1.4x headroom at current repository size (90M peak measured 2026-08-21), not the >5x the R-B floor implied; a grown rpi3 repository pushes restic into an OOM kill on the monitoring-of-record node. Fully disclosed in defaults/main.yml and verification.md, and the failure is loud (OnFailure fires) with restore unaffected — hence Minor and non-gating, but the margin decay is a standing operator follow-up. | defaults/main.yml memory-cap comment; verification.md "Measured against a real (if still small) repository" | UNTESTED — an offline regression test is not feasible; this is an operational re-measure item | vault (ops follow-up; re-measure as the repo grows) |
| Minor | REAL | spec bookkeeping | proposal.md AC1–AC9 checkboxes are all `- [ ]` (grep: 9 unchecked, 0 checked) while the verification index and dated evidence tick all nine. Repo convention (archived specs — AI-007, ANSIBLE-033/035, SEC-004, etc.) ticks ACs in proposal.md. Contract-files rule forbids editing them in this review; flagged for the archiving session. | proposal.md AC list vs verification.md index; `grep -l '\- \[x\]' specs/archive/*/proposal.md` | — | spec (tick ACs at archive time) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All nine criteria demonstrated, negative paths unusually well covered (injections, negative-control power cycle, mutation checks), two Minor gaps (bind-mount blind spot, AC5 pre-cut evidence inferential) |
| Verification       | B | Timestamped transcripts, reproducible commands and real artifacts; live demonstrations need the fleet + R2 credentials to re-run, so not independently executable here |
| Scope              | A | Diff matches the proposal; out-of-scope honoured by mechanism (PVC deferral is explicit and tracked); no creep |
| Reliability        | B | Sentinel guard, fail-loud capture/ship, bounded retries, notifier; residual disclosed items (rpi3 headroom, ship-invocation concurrency fails loud) |
| Maintainability    | A | Single-purpose scripts, WHY-comment dense, SSOT-driven paths, strong invariants enforced by tests; retired role deleted |
| Handoff-readiness  | A | Runbook (`docs/runbooks/offsite-backup-restore.md`), five lessons captured this series, follow-ups tracked, teardown verb (`make backup-schedule`) added |

### Verdict
PASS (adversarial)

No Blocker or Major findings. Rubric all B or above (no C, no D), so the mechanical aggregation rule also yields PASS. The two REAL findings are content/bookkeeping Minors that cannot move the verdict; the remaining findings are THEORETICAL or SPECULATIVE and explicitly do not gate.

### Recommended next steps (before archive)
1. Fix the stale "DEFERRED … authelia" comment in `common.yaml` (Minor/REAL) — one sentence, and it removes a genuine misdirection about where the fleet's most valuable state lives. Do this in a tiny follow-up PR, before or with the archive, and note it in the commit.
2. Tick AC1–AC9 in `proposal.md` during the archive session (repo convention; forbidden here by the contract-files rule).
3. Optional, non-gating: pin `repo_prefix == s3:{endpoint}/{bucket}` in `tests/test_backup_destination.py`; add an identifier-charset invariant for `backup.sources` keys in `tests/test_backup_sources.py`; add a one-line pre-cut snapshot listing to `verification.md` to close AC5's first half to the letter.
4. `dotf spec archive BACKUP-044-critical-subset-pipeline` is **advisable** in the current state: a fresh, passing review.md with the correct pool id and non-stale `reviewed_sha` is in place, and no contract file (`proposal.md` / `tasks.md` / `features.json`) has changed since `eb34e6059`.
