---
spec: "BACKUP-046-postgres-dump"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "a5adf85898149831d7eeadb591a6f057eb9bb68c"
reviewer: "nan/mimo-v2.6-flash"
date: "2026-10-01"
---

## Adversarial review

**Scope**: BACKUP-046-postgres-dump — full change `git diff 82a8cb91e1435c5d8cc2df987cc3acc98c117539...HEAD` (a5adf858)

**Sources**: `specs/BACKUP-046-postgres-dump/{proposal,tasks,verification,features}.md|json`;
implementation in `infra/config/values/common.yaml`, `infra/ansible/roles/node_backup/templates/node-backup-capture.sh.j2`,
`toolkit/features/postgres_drill.py`, `toolkit/features/backup_destination.py`, `toolkit/cli/backup.py`, `Makefile`,
`docs/runbooks/offsite-backup-restore.md`, `docs/lessons/storage-backup/lesson-495-…`, tests
`test_backup_pvc_coverage / test_backup_sources / test_node_backup_capture_postgres / test_backup_live_claims / test_postgres_drill`.

### Spec and task alignment

Everything below was **run this session**, not read off `verification.md`:

- **AC1 (capture)** — live: `make backup-drill-postgres ENV=prod` (15:41 MDT) read
  `/opt/node-backup/staging/postgres/pg_dumpall.sql` from snapshot `024a9582` (73875 bytes, completion trailer).
  The capture stages only `pg_dumpall.sql` for the claim — `test_a_complete_dump_is_staged_and_the_capture_completes`
  asserts exactly that, and `test_the_dump_runs_inside_the_declared_workload_as_its_own_user` asserts `get pv`
  never runs, so the data directory cannot be copied. Prod deployment re-checked live: `1` replica,
  `strategy=Recreate`, `postgres:16-alpine` — the proposal's rollout-risk claim holds.
- **AC2 (failed/truncated dump fails)** — `test_a_truncated_dump_fails_the_capture_and_names_the_source` and
  `test_a_failed_exec_fails_the_capture_and_names_the_source` pass against the *rendered* script with a fake kubectl.
  **Mutation**: replaced the trailer check with `if false` → the truncated test went red (1 failed, 3 passed);
  reverted, tree clean.
- **AC3 (static guard)** — `kubectl kustomize infra/k8s/overlays/prod` renders 7 PVCs; all 7 are ruled
  (`kubelab/{authelia,crowdsec-config,crowdsec-db,grafana,loki,n8n,postgres}-…`).
  **Mutations**: deleted the `backup.sources.vps.postgres` block → `test_every_prod_claim_has_a_backup_ruling`
  red; changed the loki exclusion to `tier: 2` → `test_every_exclusion_is_tier_3_with_a_reason` red. Both reverted.
- **AC4 (live guard)** — `make backup-coverage ENV=prod` rc=0 this session: 4 nodes covered,
  `claims: all 8 live claims on 'vps' have a backup ruling` (7 rendered + `kube-system/traefik`).
  CANNOT CHECK paths fail closed (`test_a_missing_kubeconfig_is_cannot_check_not_a_pass`,
  `test_an_unreadable_cluster_is_cannot_check_not_a_pass`, `test_an_empty_answer_is_cannot_check_not_a_pass`).
- **AC5 (restore drill)** — the same live run passed end-to-end: trailer, `34 tables`, rc 0. I verified the
  teardown independently: no `pgdrill*` container and **no dangling volume dated 2026-10-01** afterwards.
  Failure paths are pinned and were mutation-checked: emptied-table comparison → red; `-v` dropped from
  `docker rm` → 3 tests red. Both reverted.
- **AC6 (docs)** — runbook has `### Postgres` (drill, whole-cluster loss, one damaged database) and
  `## Adding a stateful service`; `lesson-495-a-backup-exclusion-with-a-trigger-is-a-promise-nobody-keeps.md`
  exists with the storage-backup index updated.
- **Tasks / gates** — all boxes ticked except the final review box (this artifact). Fresh runs:
  `make test` → **3399 passed, 16 skipped, 154 deselected, 2 xfailed, exit 0** (5:04; tasks.md's "3147" is stale
  but the direction is green), `make lint` → clean, `make type` → 0 issues in 114 files,
  `make validate-sync` → all generated files in sync. No `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags in the spec files.
  Contract digests recomputed with dotf's own `normaliseContract` (CRLF fold, list-checkbox fold, features
  `state`/`evidence` blanked, frontmatter `status` folded) **match** all three recorded digests in
  `review-request.json` — this review will read as fresh at archive.
- **Range note** — `base...HEAD` also carries sibling merged PRs (#1976–#2010: AI-009, BACKUP-040/067/068
  drills, Ansible `--check`, lessons-index, secrets refactor). Each is separately spec'd inside the range and
  all are covered by the full-suite/lint/type runs above; their own ACs were **not** individually red-teamed in
  this round (owned by their specs, not this one).

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|----------|---------|------|---------|----------|---------------------------|--------------|
| Major | THEORETICAL | security / drill isolation | The scratch Postgres runs with `POSTGRES_HOST_AUTH_METHOD=trust` **on the default bridge** (no `--network none`): during the drill's ~1 min window any other container — and host processes — can reach it as superuser and read restored prod rows plus role password hashes. The three sibling drills deliberately use `--network none`, and the runbook's own mitigation for this class of leak is "no published port" | `toolkit/features/postgres_drill.py` `docker run -d --name name -e POSTGRES_HOST_AUTH_METHOD=trust image` (no network flag) vs `gitea_drill.py:321`, `headscale_drill.py:337`, `app_drill.py:220`. Reachability not reproduced | UNTESTED — `test_the_restore_uses_the_image_live_runs` pins the image only, nothing pins the network mode | code + tests (add `--network none`; loopback still serves `docker exec pg_isready -h 127.0.0.1`) |
| Minor | REAL | tests / deletion retention | The deleted `test_the_retired_and_deferred_pvcs_stay_out` guarded grafana/crowdsec/loki staying out of `backup.sources.vps`; only the postgres half got an exact replacement. Mutation: moving the grafana exclusion into `backup.sources.vps` (as a `pvc` + `sqlite` source) leaves the suite **green** — the only red in that run was the tier mutation run alongside it | my mutation run: 20 passed, 1 failed (tier only); tasks.md scoped the replacement to "postgres half" | UNTESTED for the non-postgres half; postgres half pinned by `test_postgres_is_captured_by_logical_dump` | tests (one assertion, or an explicit acceptance recorded in `verification.md`) |
| Minor | REAL | quality | `_load_and_check` is **118 lines** (repo law: <40) and `run_drill` 49; branching puts `_load_and_check` well over CC 10. No gate catches it: ruff `select = ["E","W","F","I","B"]` has no C901 and no length test exists | AST line counts measured; `pyproject.toml` lint config | UNTESTED (no complexity/length gate in the suite) | code (split the orchestration) |
| Minor | SPECULATIVE | resilience | `check_claim_rulings` returns **True** (warning only) when the cluster node declares no backups at all, so a config loss that empties `backup.sources/excluded.vps` would pass the live guard with "declares no backups". The static guard fails in the same scenario, which is the mitigating control | `toolkit/features/backup_destination.py` early return; behavior pinned by `test_a_cluster_node_with_no_backups_declared_is_reported_and_skipped` | `test_a_cluster_node_with_no_backups_declared_is_reported_and_skipped` (pins the pass; config-loss path itself UNTESTED) | code/tests — disposition, not a gate |
| Minor | SPECULATIVE | injection / templating | `src.pg_dumpall.deployment` / `.container` are interpolated raw into the rendered shell script; a config value like `x; …` would execute at capture time. Config is repo-controlled SSOT and this matches every pre-existing field (`volume`, `sqlite`, `path`), so the risk is low | template render site; `test_pg_dumpall_is_a_capture_method_for_a_claim` validates the *keys* (`{deployment, container}`) but not value shape | UNTESTED | tests (assert identifier-shaped values in the schema test) |
| Question | — | spec / harness | All five `features.json` entries carry `state: "pending"` although `evidence` is filled; confirm the harness (not the reviewer) flips these, so the archive gate does not read the spec as unverified | `specs/BACKUP-046-postgres-dump/features.json` | n/a | spec — question only; **no contract edit requested with this verdict** |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All six ACs verified live or by red/green mutation; residual negative-path gaps are the network-mode isolation and the non-postgres deletion half |
| Verification       | A | Evidence is reproducible: I reran AC1/AC4/AC5 against prod and R2 and reproduced AC2/AC3 by mutation in this session |
| Scope              | B | BACKUP-046's own files match the proposal exactly; the range also carries sibling merged PRs from other specs, each separately spec'd, none authored by this change |
| Reliability        | B | Fail-closed everywhere I probed (CANNOT CHECK, trailer, sentinel, teardown read-back); residual is the pass-on-empty-declarations early return |
| Maintainability    | C | 118-line function against the repo's <40-line law, CC >10, and no gate in ruff or the suite to hold it |
| Handoff-readiness  | A | proposal/tasks/verification/features, runbook, and lesson-495 all updated in-session; #1111 still OPEN, correct until archive |

### Verdict

**PASS WITH GAPS.** No Blocker; the single Major is **THEORETICAL** (argued from code, not reproduced), and
the rubric carries one **C** (Maintainability) with no D — both routes land on PASS WITH GAPS.

### Recommended next steps

Contract set (`proposal.md`, `tasks.md`, `features.json`) is **closed** — nothing below asks for a contract
edit; disposition each item in `verification.md` (applied / ticketed / declined with a reason) or carry it
into a follow-up ticket:

1. **F1 (code + tests, the one to do first):** add `--network none` to the drill's `docker run` and pin the
   network mode beside `test_the_restore_uses_the_image_live_runs`. Loopback inside the container still serves
   the `pg_isready`/`psql` calls, so nothing in the drill needs the bridge.
2. **F2 (tests or accept):** one assertion that grafana/crowdsec/loki stay out of `backup.sources.vps`, or an
   explicit line in `verification.md` that the loss is accepted because adding sources is the safe direction.
3. **F3 (code):** split `_load_and_check`; if this shape repeats across the four drills, consider a repo-level
   length/CC gate (a vault pattern decision, not a contract edit).
4. **F4/F5/F6:** dispositions as written; F6 is a question to the harness/operator, not a request.

**Archive is advisable now**: `dotf spec archive` should accept this — verdict is passing, no draft tags,
and all three contract digests match the recorded ones under the gate's own normalization. The `tasks.md`
final box ("Independent adversarial review…") may be ticked on the strength of this file; checkbox ticks are
folded by the digest, so doing so does not stale the review.
