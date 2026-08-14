---
tags: [spec, verification, templates]
created: "2026-08-11"
---

# Verification - ADR028-004-classify-stateful-service-placement

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] Criterion 1 -> commit `<hash>` / test `<name>`
- [ ] Criterion 2 -> commit `<hash>` / test `<name>`
- [ ] Criterion 3 -> commit `<hash>` / test `<name>`

## R1 — Beelink headroom (measured 2026-08-11/12)

Glances (`nicolargo/glances:4.5.2-full`) was not running on Beelink when this measurement started — the API refused the connection rather than timing out. Started it via the existing role: `poetry run toolkit infra ansible run -p provision-bee -e staging --tags glances` (idempotent, only started the container; no other Beelink service touched). Then queried its read-only API directly (`curl http://100.64.0.3:61208/api/4/...`).

**Host totals** (`/api/4/mem`, `/api/4/fs`, `/api/4/load`):

| | value |
|---|---|
| RAM total | 8,090,955,776 B (8.09 GB) |
| RAM used | 911,065,088 B (911 MB, 11.3%) |
| RAM available | 7,179,890,688 B (7.18 GB) |
| Disk total (root) | 105,089,261,568 B (105 GB) |
| Disk used | 42,505,207,808 B (42.6%) |
| Disk free | 57,198,567,424 B (57.2 GB) |
| Load avg (1/5/15 min) | 0.28 / 0.11 / 0.03 on 4 cores — idle |

**Running containers** (`/api/4/containers`) at measurement time:

| container | mem used | mem limit |
|---|---|---|
| glances | 75 MB | 256 MB |
| minio | 185 MB | 512 MB |
| github-runner | 60 MB (idle) | 6,144 MB (6 GB) |
| 4× buildx builder | ~30 MB each | none (inherits host) |

Sum of **declared** memory limits already on this host: 256 + 512 + 6,144 = 6,912 MB. Gitea's K8s manifest (`infra/k8s/base/services/gitea.yaml`) declares `limits: {memory: 256Mi, cpu: "0.5"}`. Adding it: 6,912 + 256 = 7,168 MB against an 8,090 MB host — **~1.1 GB headroom in the worst case where the GH runner simultaneously peaks at its full 6 GB limit**. That worst case is mitigated, not eliminated: ADR-030 (amended 2026-06-26) made self-hosted CI opt-in and idle-by-default (`RUNNER_DOCKER` defaults to `ubuntu-latest`), so the runner sitting at 60 MB idle is the common case, not the exception.

**Conclusion: R1 is resolved.** Gitea fits on Beelink both under current idle usage (7.18 GB free) and under the declared-limits worst case (~1.1 GB free). Headroom is not a blocker for R1's location question.

## R3 — prod backup CronJob (re-examined 2026-08-11/12, correcting the original framing)

The proposal's original R3 text framed this as MinIO losing its destination. That is wrong: MinIO's migration is explicitly out of scope for this spec (proposal.md "Out of scope"), so `http://minio:9000` keeps resolving in prod for this spec's entire life. **The actual break is on the source side, and it happens inside this spec's own scope, not MinIO's.**

`infra/k8s/overlays/prod/backup.yaml` mounts three PVCs read-only: `gitea-data`, `authelia-data`, `n8n-data` (lines 107-138), and runs `sqlite3 .backup` against each before shipping to in-cluster MinIO. R1 concludes Gitea moves to Beelink as a Docker Compose service — which means the prod `gitea-data` **K8s PVC gets deleted** as part of that move. The same applies to `n8n-data` pending R2's node choice. When either PVC is gone, its `volumes:` entry in `backup.yaml` references a claim that no longer exists.

**AC3's safety net does not catch this.** `kubectl kustomize` renders a CronJob with a dangling PVC claim without error — Kustomize doesn't validate that a referenced PVC exists. `kubectl apply` accepts it the same way. Staging e2e never exercises it either, because `backup.yaml` is prod-only by design ("staging data is disposable"). The failure surfaces exactly the way the current R3 text already worried about: silently, at 03:00, when the job tries to mount a claim that isn't there.

**Resolution for this spec:** the move task for Gitea (and n8n, once R2 lands) must edit `backup.yaml` in the same change — drop the `gitea-data` (and `n8n-data`) mount and backup step, keep `authelia-data` (Authelia stays dual/in-cluster per the proposal). This is now a MUST for R6's blast-radius sweep, called out by name rather than left implicit in "cross-cutting consumers."

**What this does NOT resolve, and isn't meant to:** the in-cluster MinIO destination was never a real offsite copy — same-cluster storage doesn't survive a cluster or node loss, which is exactly why ADR-049 D3 already routes the real offsite tiers to Hetzner Storage Box (Borg, bulk) and Cloudflare R2 (restic, critical subset — tracked as BACKUP-043 #596, open). Neither a primary Borg pipeline nor #596 exists yet; today's CronJob is ADR-024's known-interim state, and this spec's job is only to stop it from silently mounting a deleted PVC, not to build the real offsite path. That stays out of scope (#479, #487, #596), same as originally stated.

## AC4 gap found while resolving R3

AC4 as written (proposal.md line 68) requires emptiness evidence only for the **staging** instances of gitea/n8n/minio before deletion. But R1's own conclusion deletes the **prod** `gitea-data` PVC too (prod currently has nothing in it per the operator, but that claim has no captured evidence, unlike staging where #479/#487 being open was already flagged as the reason to require proof). Same irreversibility, same open recovery-path gap, no AC currently requires proof for it. Proposed one-line amendment to AC4: emptiness evidence is required for any **prod** instance immediately before its move task runs, not staging only.

Both the R3 amendment and the AC4 amendment are proposal.md changes — `proposal.md` is already on master via #1003, so landing them needs a new branch/PR with the user's sign-off, not a direct edit here. Drafted, not applied, pending that sign-off and pending R2 (which decides whether n8n's mount even needs to move, and shapes what the move task actually does).

## R2 — Ansible-managed platform plane (decided 2026-08-12)

Asked directly, since this is a doctrine call that cascades into R1's deployment task and into R3's backup.yaml edit, and standing practice on this project is not to make that call unilaterally. **Decision: deliberate, not a regression.** Gitea moving to Docker Compose on an Ansible-managed node is the intended shape, not a GitOps gap to be closed. It is the same pattern already in the repo twice — Headscale staying outside K3s (ADR-015) and the Argo CD hub living outside both K3s clusters — for the same structural reason: a platform component cannot be reconciled by the GitOps system that depends on it being reachable to do the reconciling. Gitea hosting private repos that Argo CD would need to fetch from is exactly that shape, which is also why the proposal already commits Argo CD to reconciling from GitHub, never from Gitea.

**Consequence for R1's task and R3's backup.yaml edit:** both proceed as scoped — Gitea's move task deploys via the `beelink_services`-style Ansible role (Docker Compose), not a Kustomize resource, and the same task drops `gitea-data` from `backup.yaml`. No revision to R1's node choice is needed.

**Correction, written after R5 (below):** this section originally said "Gitea (and n8n, on the same footing)" — that generalization was wrong and unexamined. n8n has no circular-dependency problem (it isn't a GitOps source Argo CD depends on) and its prod instance is the live alerting path, which by ADR-028's own 3 AM test has to stay on the always-on K3s tier, not follow Gitea to on-demand Beelink. n8n needed no R2-style doctrine call at all — it simply never moves. See the R5 write-up for the full reasoning.

## R5 — Per-instance emptiness proof (staging, 2026-08-12)

`AC4-EVIDENCE staging/gitea pre-deletion`

**Gitea — confirmed empty.** Unauthenticated `/api/v1/repos/search` structurally cannot see private repos, and private-only is Gitea's settled role — a 0 there can't distinguish "empty" from "invisible." Re-ran authenticated (admin credentials via `toolkit secrets show apps.services.core.gitea.admin_password --env staging`, live username read from the `gitea-secrets` K8s Secret): `X-Total-Count: 0` with `private=true`, 0 repos including private. Clean.

Re-verified 2026-08-14 immediately before the move, unconditionally rather than trusting the entry above — see the prod capture below for the shared method and the full transcript of both instances.

**MinIO — confirmed empty.** `/data` inside the pod contains only `.minio.sys` (MinIO's own internal metadata dir). No buckets.

**n8n — NOT empty, and the proposal's "Why" section overclaims.** `proposal.md`'s Why section states "gitea, n8n and minio... are verified empty and unused" — that was always operator-reported, not verified (R5 exists precisely because the report might be wrong for one of the three). It was wrong for n8n. Copied `database.sqlite` + `-wal` + `-shm` out via `kubectl cp` (bytes-out, zero cgroup cost — no exec inside the pod, unlike the CLI attempt below) and queried locally:

| table | count |
|---|---|
| workflow_entity | 1 — `notify-router`, `active=1` |
| credentials_entity | 1 — `notify-webhook` |
| execution_entity | 0 |

This is not stray test data — it's the notification-fabric workflow (NOTIFY-001), reconstructable by name from git+SOPS: `toolkit/features/n8n_import.py` targets `infra/n8n/workflows/notify-router.json` + credential `notify-webhook` explicitly. `toolkit infra n8n import` (TOOL-009, #691 closed) exists for exactly this workflow — the proposal's "no export/import route" claim in Out of Scope was always about the *general* case (arbitrary user workflows, the APP-CONFIG-003 gap), not this one bootstrapped workflow, and that reading is already in the proposal's own text.

**Consequence for the spec — n8n's classification changed, not just its emptiness bar.** The initial read was "singleton survives, strengthened" (state is reconstructable, so deleting the PVC loses nothing). That's true but incomplete: it only asks whether it's *safe* to delete the staging twin, not whether there's a *reason* to keep it. Two facts, both already in evidence, argue for keeping it:

1. The workflow is `active=1`, and `toolkit/features/notify_smoke.py` (`make notify-smoke ENV=staging`) drives the real `/webhook/notify` endpoint against the domain resolved for that env — confirmed by reading the module, which explicitly handles `n8n.staging.kubelab.live`'s cert quirk. Staging n8n is the pre-prod validation leg for notification-fabric changes, the same shape ADR-028's observability amendment already established for Grafana/Loki/Vector.
2. n8n's prod instance is the live alerting path — the thing that has to work at 3 AM — which by ADR-028's own test means it stays on the always-on K3s tier. It was never a candidate to follow Gitea to on-demand Beelink in the first place; R2's generalization to n8n (corrected above) was wrong on this point too.

### Decision: n8n stays dual, in place (decided 2026-08-12, with industry research)

Asked the user directly, then researched rather than asserting an opinion — this changes the spec's own classification, not an implementation detail.

**The framing that resolves it: "staging vs. test-in-prod" is a false dichotomy for alerting pipelines, because they validate two different failure modes.**

- **Staging n8n + git-based promotion validates *changes*** — did a routing edit break something, checked before it reaches prod. This is n8n's own vendor-documented pattern: n8n's official docs describe a git-backed "Environments" model (dev/staging → production, promoted via git branches) as the recommended way to run multiple instances — [Environments in n8n](https://docs.n8n.io/source-control-environments/understand/environments/), [Git and n8n](https://docs.n8n.io/source-control-environments/understand/git/). `toolkit infra n8n import` (TOOL-009) is a hand-built, single-workflow version of that same pattern on community edition (no native multi-environment feature there). That's the honest CV framing: replicated the vendor's enterprise pattern's *shape*, not the feature itself.
- **A watchdog/dead-man's-switch validates *runtime*** — is the live prod pipeline actually alive right now. Standard SRE pattern: an always-firing check routed through the real pipeline, watched by something external that pages on the check's *absence* — [How to Set Up a Dead Man's Switch in Prometheus](https://blog.ediri.io/how-to-set-up-a-dead-mans-switch-in-prometheus), [End-to-End Watchdog Alerts, PromLabs](https://training.promlabs.com/training/monitoring-and-debugging-prometheus/metrics-based-meta-monitoring/end-to-end-watchdog-alerts/). Professionals run both — one doesn't substitute for the other, since a passing staging test says nothing about whether prod is currently up, and a healthy prod heartbeat says nothing about whether an untested change will route correctly.

**Verified this repo has neither redundancy nor the second half:** the staging leg exists as described. The watchdog does not — checked `infra/config/uptime-kuma/monitors.json`, 0 of 31 monitors are type `push` (heartbeat). Searched the tracker before concluding it was a gap (`gh issue list --search "watchdog OR heartbeat OR dead man"` — zero hits); `NOTIFY-007` (#686)'s n8n Error Trigger only reports a failed *execution*, requiring n8n to already be up and receiving the webhook — it does nothing for the exact failure mode #1009 already demonstrated (pod unresponsive under CPU throttling). Filed as **NOTIFY-009 (#1021)**, out of scope for this spec (monitoring configuration, not a placement decision), noted as the monitoring lane's territory to coordinate with (seed-key migration in progress there per #963's chain).

**Decision: n8n stays dual, exactly where it is — no R1/R2-style move, no new machinery.** Condition, which must land in the ADR row, not stay implicit: legal only while git + `toolkit infra n8n import` remains the sole write path for its state. A workflow authored by hand in either instance's UI forks it instantly, and the general-case fix for that (#501/#688, `APP-CONFIG-003`) is still open — this is the same "declared doctrine, not yet enforced" shape the spec already accepted for Gitea's restore-from-backup test path, applied to n8n's git-promotion path instead.

**0 executions, reported neutrally:** n8n prunes execution history by default, so this cannot distinguish "never fired" from "fired and pruned." Not claimed as evidence the workflow is unused — and moot to the decision either way, since the case for dual rests on the promotion path and the always-on requirement, not on usage volume.

## Incident: kubectl exec into the n8n pod, and the confirmed root cause (2026-08-12)

Attempting to count workflows via `kubectl exec ... -- n8n list:workflow` (the official n8n CLI) coincided with the pod failing its liveness probe and restarting. Sequence from `kubectl get events`: the exec'd process exited 137 (SIGKILL) after the command ran past its interactive timeout; the pod's liveness probe then timed out (`context deadline exceeded`) and kubelet killed and restarted the container.

**Root cause, confirmed — not by this session.** The `dns-cleanup` lane (running `make deploy-k8s ENV=staging` + `make import-n8n ENV=staging` against the same pod concurrently, for unrelated OPS-022 work) measured the container's own `cpu.stat` directly: `nr_throttled=211/554` periods, `throttled_usec` (30.9s) exceeding `usage_usec` (27.5s) — the container is **CPU-throttled under its 1-core limit**, and the 5s `healthz` timeout doesn't survive that throttling. Filed with full evidence as **#1009** (open). This pod already carried 4 restarts in 45h before either session touched it today. My `kubectl exec` most likely added contention on top of an already-throttled container rather than causing the instability from scratch — consistent with, not contradicted by, the CPU-cgroup evidence.

**Durable lesson, independent of #1009's specific fix:** `kubectl exec` runs inside the target container's own cgroup (CPU and memory both). Any command whose CLI boots a second copy of the app runtime (n8n CLI here; `gitea admin <cmd>` would hit the same shape against Gitea's 256Mi/0.5-CPU limit) competes with the already-running server process for the same ceiling — and will make a marginal container measurably worse, as it did here. The repo already contains the correct pattern for exactly this: the backup CronJob (`overlays/prod/backup.yaml`) runs its tooling — including `sqlite3` reading the same class of PVC — in a **separate pod with its own resource limits**, never via exec into the live service pod. This is the piece worth a `docs/lessons.md` entry (not yet written, pending the user's call) — it's a methodology point that outlives #1009's specific CPU-limit fix, and applies to any resource-constrained stateful pod, not just this one.

**Mystery resolved, not by this session:** the second pod replacement (new ReplicaSet `n8n-85bcc9fcb4`, only the `kubectl.kubernetes.io/restartedAt` annotation differed) was `make import-n8n ENV=staging` from the `dns-cleanup` lane — that target explicitly restarts the n8n Deployment after importing the workflow. Not an unexplained `kubectl rollout restart`; confirmed directly by that session. This also explains `notify-router`'s very recent `updatedAt`: the peer's `import-n8n` run re-imported it minutes before I copied the DB.

## R4 — Where the classification is asserted from (resolved 2026-08-12)

Confirmed the nine stateful PVCs in `infra/k8s/base/` map to eight distinct services (`crowdsec` owns two PVCs — `crowdsec-db`, `crowdsec-config`): `loki`, `n8n`, `minio`, `crowdsec`, `grafana`, `authelia`, `postgres`, `gitea`.

**Nothing blocks fields under `common.yaml`** — confirmed by checking each service resolves to a config block there. Seven of eight live under `apps.services.<category>.<name>`, a free-form dict already carrying many attributes (`name`, `image`, `domain`, `resources`, ...) — adding `state_promotion`/`location` keys is no different from any other attribute already there.

**The eighth, `postgres`, does not live there — and that's deliberate, not a gap.** It's at `infra.postgres.*`, not `apps.services.data.postgres`. Its own comment names why: "Shared data-service (ADR-051, implements ADR-050 D7)... pgvector/memory (ADR-027/043) is the planned second consumer — hence `infra.*`, not a per-app namespace" — the same `infra.*` pattern ADR-036 established for SMTP, for services with more than one consumer. **Consequence for the static test's design:** it cannot assume a single tree to walk. The correct shape is: enumerate stateful services from the K8s manifests (ground truth — PVC-bearing files in `base/`), then for each, resolve its classification by checking wherever that service's config block actually lives (`apps.services.*` for seven, `infra.postgres` for the eighth) — not by walking `apps.services.*` alone and assuming coverage.

**Test blueprint, mirroring the one existing precedent for this exact shape** (`tests/test_spoke_rbac_covers_manifests.py`, TOOL-029 — chosen deliberately because it already solved "discover shipped resources from manifest files with no cluster, cross-reference against a declared SSOT, fail loudly and specifically, never silently skip"):
1. `_stateful_services()` — walk `infra/k8s/base/*.yaml` for `kind: PersistentVolumeClaim`, return the owning service name per file.
2. `_declared_classification()` — load `common.yaml`, resolve each service's block from wherever it lives, return `(state_promotion, location)` or `None` if either is missing.
3. Fail listing every stateful service missing either field, by name — the same actionable-failure shape TOOL-029's test uses, not a bare assertion count.
4. A guard test proving the check can go red — mirroring `test_create_exemptions_are_still_needed`: assert the check fails when a service's block genuinely lacks the fields (not "assert True", an actual removed-field fixture), matching R4's own stated bar in `proposal.md` ("a test that cannot be shown to fail is not a gate").

Not built in this session — this is the design the ADR/task-list work will implement, once `tasks.md` unfreezes. R4 asked whether anything *prevents* this; nothing does, and the one wrinkle (`postgres`) is now a known, documented input to that implementation rather than a surprise it would hit.

## R6 — Blast-radius sweep (verified 2026-08-12)

Checked every consumer R6 names, plus the one R3 added (`backup.yaml`), against the actual repo — not re-asserting the list, verifying it.

**Confirmed exact as stated:**
- `overlays/prod/patches.yaml` — all seven targets present at the claimed identity: `gitea-config`, `gitea`, `n8n-config`, `n8n`, `minio-config`, `minio-api`, `minio-console`.
- `tests/e2e/expectations.py` — `gitea` (111), `n8n` (114), `minio` (122), all present.
- `SECRET_CATALOG` (`toolkit/features/secrets_manager.py`) — gitea and minio entries present (`apps.services.core.gitea.*`, `apps.services.data.minio.*`).
- `overlays/prod/backup.yaml` — R3's finding, mounts `gitea-data`/`n8n-data`.

**Corrected — the pointer was imprecise, the claim behind it was right:** "Homepage `services.yaml`" is not the file to edit. The committed `infra/k8s/base/services/homepage-config/services.yaml` is a static scaffold (placeholder widgets only, no service names). The actual consumer is `toolkit/scripts/sync_homepage_config.py` lines ~209-299, which hardcodes construction of Gitea/n8n/MinIO homepage tiles by reading their `apps.services.*` blocks by name — retiring a service without touching this script leaves a broken tile pointing at a domain that no longer resolves.

**Split into two, only one needs an edit:** "Authelia's staging access rules and OIDC clients" was one bullet for two different mechanisms.
- **Access rules are auto-derived**, not hardcoded — `toolkit/features/generator_authelia.py` builds `access_control` generically from each component's `enable_auth`/`auth_level`. Retiring a service here is already safe; no manual edit point.
- **OIDC client registrations are hardcoded** — `apps.services.security.authelia.oidc_clients` in `common.yaml` lists `gitea-oidc` and `minio-oidc` explicitly (n8n has none; it uses built-in auth per `expectations.py`'s own comment). These entries need manual removal on retirement — this is the real edit point the original bullet was gesturing at.

**Confirmed, distinct from Authelia's own list:** `staging.yaml` overrides `apps.services.{core.gitea,automation.n8n,data.minio}.domain` (and MinIO's `console_domain`) to the `*.staging.kubelab.live` forms — the staging-layer half of "the `apps.services.*` tree," separate from Authelia's OIDC list above.

**Net effect on the task list this unblocks, narrowed after R5 kept n8n dual:** every count above included n8n's entry alongside gitea's and minio's. Once R5 settled n8n as staying dual, in place, its entries in each of these 7 files no longer move: `overlays/prod/patches.yaml` moves 5 resources (not 7 — `n8n-config`/`n8n` stay in `base/`), `overlays/prod/backup.yaml` drops 1 mount (not 2 — `n8n-data` stays), `tests/e2e/expectations.py`'s `n8n` entry is untouched, `sync_homepage_config.py` loses 2 hardcoded tiles (not 3 — n8n's stays), `staging.yaml` loses 2 domain overrides (not 3 — n8n's stays). `SECRET_CATALOG` and the OIDC client list were already gitea+minio only, unchanged. Same 7 files, smaller diff in each. AC3 (render + `test-e2e ENV=staging` green) still stays the outcome check, since a static list can still miss something a future service adds.

## AC4 — Pre-deletion emptiness re-verification, both Gitea instances (2026-08-14)

Captured **before** any deletion and before the operator started using Gitea, which is the only window in which this evidence means anything. R5's staging capture from 2026-08-12 was not reused — `tasks.md` requires the check to run unconditionally, however recent the prior evidence looks.

**Method.** Authenticated `GET /api/v1/repos/search?private=true` plus `GET /api/v1/admin/users`. Authentication is not optional here: an unauthenticated search cannot see private repos by construction, and private-only is Gitea's settled role, so an unauthenticated `0` cannot distinguish *empty* from *invisible*.

The first run returned `HTTP 401` against both instances, authenticating as `apps.auth.admin_username` (`operator`). That is not an incidental scripting slip — Gitea's admin identity is **not** taken from that SSOT. `k8s_secrets.py` maps the `gitea-secrets` key `ADMIN_USER` to `BASIC_AUTH_USER`, which resolves to `manu`, the OS-level user. This is the drift already tracked as **#1013** (AUTH-004), observed here independently; no new ticket, and the rename is deliberately not performed in passing.

```
Captured: 2026-08-14T00:44:06Z

### AC4-EVIDENCE prod/gitea pre-deletion — https://gitea.kubelab.live
version:        {"version":"1.25.5"}
repos (private=true, authenticated as manu):
  HTTP status:  HTTP/2 200
  X-Total-Count: 0
  data[] length: 0
  users:
    count: 1
    user: manu admin= True

### AC4-EVIDENCE staging/gitea pre-deletion — https://gitea.staging.kubelab.live
version:        {"version":"1.25.5"}
repos (private=true, authenticated as manu):
  HTTP status:  HTTP/2 200
  X-Total-Count: 0
  data[] length: 0
  users:
    count: 1
    user: manu admin= True
```

**Both instances are empty**: authenticated `200`, `X-Total-Count: 0`, no repos including private ones, and a single user which is the bootstrap admin itself. The singleton can be stood up on the Beelink without migrating anything.

## AC2 — Classification gate transcript (captured 2026-08-14)

Owed by PR 2, which merged without it. This is an unmet acceptance criterion, not tidying: AC2 requires the gate be *demonstrated* to fail, and a suite that only ever reports green proves nothing about whether it can go red.

**Full suite, green against the real repo:**

```
$ poetry run pytest tests/test_stateful_service_classification.py -v --no-cov
test_manifests_actually_yield_stateful_services                              PASSED
test_every_stateful_service_declares_a_classification                        PASSED
test_fixture_baseline_is_compliant                                           PASSED
test_gate_goes_red_on_each_violation[overrides0-missing `state_promotion`]    PASSED
test_gate_goes_red_on_each_violation[overrides1-missing `location`]           PASSED
test_gate_goes_red_on_each_violation[overrides2-is not one of]                PASSED
test_gate_goes_red_on_each_violation[overrides3-is not one of]                PASSED
test_gate_goes_red_on_each_violation[overrides4-location_deferred_to]         PASSED
test_gate_goes_red_on_each_violation[overrides5-not a ticket reference]       PASSED
test_gate_goes_red_on_each_violation[overrides6-not a ticket reference]       PASSED
test_gate_goes_red_on_each_violation[overrides7-not a ticket reference]       PASSED
test_gate_goes_red_when_the_service_has_no_config_block                       PASSED
test_undecided_location_is_accepted_when_its_deferral_is_recorded             PASSED
============================== 13 passed in 0.70s ==============================
```

**Red-then-green against the real repo**, not only against the synthetic fixture. The eight `test_gate_goes_red_*` cases above assert failure on in-memory fixtures, which proves the checking *function* rejects bad input but not that the live wiring — PVC discovery, the two config namespaces, the resolution walk — reaches `common.yaml` at all. A gate can pass all of its own negative controls and still be reading nothing. So one real classification field was removed and the main test re-run:

```
$ # gitea's `state_promotion` line temporarily removed from common.yaml
$ poetry run pytest ...::test_every_stateful_service_declares_a_classification
E       AssertionError: Stateful services with an incomplete classification:
E       assert not ['gitea (PVCs: gitea-data): missing `state_promotion`']
============================== 1 failed in 0.54s ===============================

$ # file restored from an explicit backup copy
$ poetry run pytest ...::test_every_stateful_service_declares_a_classification
============================== 1 passed in 0.52s ===============================

$ git diff --stat -- infra/config/values/common.yaml
(no output — restored byte-identical)
```

The failure names the service and the missing field rather than reporting a bare count, which is what `tasks.md` asked for.

Method note: the edit was restored from a copied backup, deliberately **not** with `git checkout -- infra/config/values/common.yaml`. That command is what #1034 was about, and reaching for it during an experiment is how this session destroyed its own uncommitted work once already. `git diff --stat` is included above as the proof of no residue.

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

-
-

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons.md`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/ADR028-004-classify-stateful-service-placement/` -> `specs/archive/ADR028-004-classify-stateful-service-placement/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
