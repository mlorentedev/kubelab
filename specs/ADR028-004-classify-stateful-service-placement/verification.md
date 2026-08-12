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

Asked directly, since this is a doctrine call that cascades into R1's deployment task and into R3's backup.yaml edit, and standing practice on this project is not to make that call unilaterally. **Decision: deliberate, not a regression.** Gitea (and n8n, on the same footing) moving to Docker Compose on an Ansible-managed node is the intended shape, not a GitOps gap to be closed. It is the same pattern already in the repo twice — Headscale staying outside K3s (ADR-015) and the Argo CD hub living outside both K3s clusters — for the same structural reason: a platform component cannot be reconciled by the GitOps system that depends on it being reachable to do the reconciling. Gitea hosting private repos that Argo CD would need to fetch from is exactly that shape, which is also why the proposal already commits Argo CD to reconciling from GitHub, never from Gitea.

**Consequence for R1's task and R3's backup.yaml edit:** both proceed as scoped — Gitea's move task deploys via the `beelink_services`-style Ansible role (Docker Compose), not a Kustomize resource, and the same task drops `gitea-data` from `backup.yaml`. No revision to R1's node choice is needed.

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
