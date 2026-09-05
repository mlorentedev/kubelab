---
spec: "OPS-024-node-disk-isolation-and-watch"
verdict: "FAIL"
reviewed_sha: "991d8aaf775f74c73be6123b801239909c781a27"
reviewer: "nan/deepseek-v4-flash"
date: "2026-09-05"
---

## Adversarial review

**Scope**: OPS-024-node-disk-isolation-and-watch (draft spec, pre-implementation)
**Sources**: `specs/OPS-024-node-disk-isolation-and-watch/{proposal,tasks,verification,features}.json`; HEAD `991d8aaf` (the only commit touching this spec, 4 files, all docs); verified against `infra/k8s/base/services/grafana-alerting/disk-rules.yaml`, `infra/k8s/base/services/disk-watcher.yaml`, `infra/config/values/common.yaml`, `infra/ansible/playbooks/provision-bee.yml`, `infra/ansible/roles/node_maintenance/`, `Makefile`, `toolkit/cli/infra.py`, `toolkit/cli/observability.py`, `toolkit/features/docker_reclaim.py`, `tests/test_docker_reclaim.py`.

**Phase note (off-label, stated as a decision):** this review was requested *before* implementation. The `adversarial-review` skill is written for the verification window (after implementation, before archive). The spec is `status: draft`; every AC box is `[ ]`, `verification.md` is an untouched template, `features.json` is all `"state": "pending"`, and `tasks.md` declares the two open questions are deferred to the reviewer. I reviewed it as a **spec-readiness gate**, not an archive gate. The verdict below therefore grades the *spec*, and "FAIL" here means **this draft spec needs these gaps resolved before implementation** — not that an implementation is broken. `dotf spec archive` is not advisable in the current state regardless of this verdict, because the draft status, all-`pending` feature states, and empty `verification.md` each independently refuse it.

### Spec and task alignment

- Proposal declares 7 ACs (AC1–AC7) and 4 PRs (PR-A storage LV, PR-B prove isolation, PR-C node producer → rule, PR-D timer reaps). `tasks.md` maps tasks to ACs consistently (`[AC<n>]` markers). Structure is sound.
- AC1/AC3 (PR-A) require an Ansible role (`node_storage`) that **does not exist** — there is no `node_storage` role in `infra/ansible/roles/`, and no `storage` tag anywhere in the ansible tree. That is expected for a draft spec (PR-A introduces it), but it means the features.json f1 verification (`make provision NODE=bee ENV=prod TAGS=storage CHECK=1`) can only ever run after PR-A lands. Not a defect; a dependency to be aware of.
- AC1 also depends on an SSOT schema `networking.nodes.<node>.storage.*` that **does not exist today**. `common.yaml` has a `storage:` block only under `apps.services.data.vikunja` (line ~1193); none of the six `networking.nodes` entries (ace1, ace2, rpi4, rpi3, beelink, jetson) carries a `storage` key. PR-A must add both the schema and the role. Fine as plan, but worth naming: AC1's "sized from the SSOT" has no SSOT to size from yet.
- AC4/AC5 (PR-C) target `obs015-disk-root-saturation`. Verified the rule exists (`disk-rules.yaml` uid `obs015-disk-root-saturation`), selects `{container="disk-watcher"}`, parses `metric=disk_root_usage`/`unwrap used_pct`, groups `by (node)`, threshold `>90`. The five non-K3s nodes are correctly enumerated (beelink, rpi3, rpi4, ace2, jetson); ace1 and the VPS/gcp1 are K3s cluster nodes covered by their own in-cluster `disk-watcher`. The `networking.nodes` coverage is coherent.
- AC6 (PR-D) reuses #1665's `docker_reclaim` planner. Verified the planner (`toolkit/features/docker_reclaim.py`, `plan_reclaim`, `Created`-based age gate) exists and its 38-test suite passes on this branch — but it is **not on `master`** (see finding M-4).
- No `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tags present anywhere in the spec folder.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL | AC4/AC5 producer reliability | The node producer's log must land in the `{container="disk-watcher"}` stream for `obs015-disk-root-saturation` to evaluate it, AND the rule has `noDataState: OK`. A direct-Loki-push producer that sets `container` to anything else never fires (AC4 silently fails), and a dead producer (a systemd timer on an unmanaged non-K8s node) makes the rule go to *no-data = OK*, i.e. a watched node becomes unwatched with no signal. "Watch every node" is undermined by exactly the silent-accumulation class the incident belonged to. | Read of `disk-rules.yaml`: selector `{container="disk-watcher"}`, `noDataState: OK`, `by (node)`; the spec's open-question #1 only asks "direct push vs shipper", never naming the selector or the no-data state. | UNTESTED (no test covers a producer stream label or producer liveness) | spec + code |
| Major | THEORETICAL | AC2 destructive-test ambiguity | AC2 reads "Filling `/var/lib/docker` to 100% on the Beelink leaves Gitea accepting writes", while PR-B reads "Fill the isolated LV deliberately (small LV, `fallocate`)" and the risks section says "test with a deliberately small LV". It is never resolved whether isolation is proven on the **real production `/var/lib/docker` LV** (destructive; Gitea's writable layer and logs live there, so this can re-take the forge down — the exact incident) or on a **sacrificial LV** (safe, but then it does not prove the production path). The residual the AC promises to name depends on which is true. | Read of proposal AC2 + risks ("test with a deliberately small LV before anyone claims the failure mode moved") + PR-B task. The two halves are in tension and neither is reconciled. | UNTESTED (no test; the AC is a manual prod experiment) | spec |
| Major | THEORETICAL | verification artifact | features.json f2's verification `make gitea-reconcile ENV=prod` cannot prove AC2. `gitea-reconcile` is **plan-only** (no `--apply`) and reconciles Gitea repo state; it does not demonstrate "a real issue or push through Gitea while the LV is full" as AC2 requires. Even as a provisional plan it is the wrong verification. | Read of Makefile `gitea-reconcile` (plan-only by default, `--apply` to act) + `toolkit/cli/services.py::gitea_reconcile`; features.json f2. | UNTESTED | spec (features.json) |
| Minor | THEORETICAL | AC6 dependency | AC6 reuses #1665's planner (`toolkit/features/docker_reclaim.py`), which is **not on `master`** — it exists only on this `fix/1657-reclaim-docker-residue` branch. The proposal calls #1665 "merged or open"; it is verified *open/not merged*. A PR-D branch cut from `master` cannot reuse the planner until #1665 lands. | `git cat-file -e master:toolkit/features/docker_reclaim.py` → "NOT on master"; `tests/test_docker_reclaim.py` passes (38) only on this branch. | UNTESTED | spec |
| Minor | THEORETICAL | verification artifact | features.json f1's `make provision NODE=bee ENV=prod TAGS=storage CHECK=1` forces `deploy_env=prod` (the toolkit passes `-e deploy_env={env}`), contradicting `provision-bee.yml`'s `deploy_env: staging`; and the `storage` tag does not exist in any role yet (PR-A must add it). Also f4's `make alerts ENV=prod` is read-only and cannot by itself prove AC4's "verified by consequence on a real threshold crossing" without the crossing step. | Read of Makefile `provision`, `toolkit/cli/infra.py::ansible_run` (line ~1353 `-e deploy_env={env}`), `provision-bee.yml` (`deploy_env: staging`), no `storage` tag found; `toolkit/cli/observability.py::alerts_cmd` (lists alerts only). | UNTESTED | spec (features.json) |
| Question | — | open question #1 | Direct Loki push vs a shipper — **resolved by this review**: direct push is the smaller change and acceptable, *but* the producer must set `container="disk-watcher"` and a `node` label for the rule to select and group it, and the `noDataState: OK` silent-failure must be addressed (see M-1). The spec should record this resolution rather than leave it open. | Read of `disk-rules.yaml` + `loki.kubelab.live` Bearer assumption in the proposal. | — | spec |
| Question | — | open question #2 | Whether the `by (node)` grouping survives a node label — **resolved by this review**: it survives. The CronJob's `disk_root_usage` (no `node` label) groups under an empty `node`; a producer that emits a `node` label groups per-node. These are distinct and correct, and `disk-rules.yaml` already states the identity choice ("node, not `pod` (OBS-018 AC5)"). No conflict. | Read of `disk-rules.yaml` comment + `by (node)` expr. | — | spec |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness | C | ACs are sound on the happy path but carry substantial negative-path gaps (producer silent-failure, AC2 destructive-test ambiguity, non-vacuous f2 verification). |
| Verification | C | features.json carries a verification *plan* but several commands are non-vacuous (f2) or incomplete (f4) and no evidence exists yet (draft). |
| Scope | B | Spec scope (4 PRs, 4 files) matches the proposal; no creep; the unrelated branch content is outside the reviewed HEAD commit. |
| Reliability | C | Migration interruptibility and reserve-in-LV are addressed, but producer liveness / `noDataState: OK` is unhandled, and the AC2 test path can cause a live outage. |
| Maintainability | A | Clear ACs, well-structured risks, load-bearing WHY comments; no dead code. |
| Handoff-readiness | B | Lessons (#437, #285) and ADR-028 correctly referenced; two open questions and all-pending features remain. |

### Verdict

**FAIL** — driven by the severity axis: three **Major** findings (producer stream-label / `noDataState` reliability, AC2 destructive-test ambiguity, non-vacuous f2 verification). The rubric has no **D** (it grades at the C/B boundary, which alone would be PASS-WITH-GAPS), but the skill's aggregation rule takes the more severe path, so a Major forces FAIL. This is a *spec-readiness* FAIL on a draft, not an implementation defect.

**`dotf spec archive` advisability:** **Not advisable now.** Independently of this verdict, the spec is `status: draft`, all `features.json` entries are `"state": "pending"` with empty evidence, and `verification.md` is an unfilled template — each of those refuses the archive. The correct sequence is: resolve the Majors in the spec → implement PR-A..PR-D → run `verification.md` evidence → *then* re-review in the verification window.

### Recommended next steps (before archive)

1. **Resolve open question #1 in `proposal.md`:** declare the direct-Loki-push path, require the producer to set `container="disk-watcher"` and a `node` label, and specify how a dead producer is detected (add a liveness signal, or explicitly declare `noDataState: OK` for producers out of scope and say so).
2. **Reword AC2 / PR-B unambiguously:** state whether isolation is proven on the real production `/var/lib/docker` LV or a sacrificial LV, and how the residual is recorded; name the live-outage risk of a production full-LV test, and the planned mitigation.
3. **Fix `features.json`:** f2 to a verification that actually exercises AC2 (a real write under a full LV), f1 to the env that matches `provision-bee.yml`'s `deploy_env`, and f4 to include the induced-crossing step rather than only `make alerts`.
4. **Declare the #1665 dependency in the proposal risks** (planner is not on `master`; PR-D cannot reuse it until #1665 merges).
5. **Re-run this review in the verification window** after PR-A..PR-D land with `verification.md` evidence and feature states flipped to `pass`.

**Minimum set that would flip this FAIL to PASS:** resolve the three Majors — (a) define the producer's stream-label + liveness so "every node" is genuinely watched, (b) reconcile AC2's wording with the small-LV mechanism and name the prod-outage risk, (c) make `features.json` f2 a non-vacuous AC2 verification — and implement + verify the ACs with real evidence.
