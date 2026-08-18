---
id: lesson-311-nine-stateful-services-were-duplicated-across
type: lesson
status: active
created: "2026-08-11"
owner: manu
tags: [kubelab, lesson, kustomize, topology, stateful, gitea, minio, n8n, adr-028, adr-037, circular-dependency, ssot-drift, adr028-004]
---

# Nine stateful services were duplicated across environments by a packaging choice, not a decision

**Context:** A question about whether Gitea should run in both staging and prod — a git host duplicated across environments has no obvious meaning — generalised into an audit of every stateful service.

**Problem:** Nine PVCs run in both overlays: `gitea`, `n8n`, `minio`, `postgres`, `loki`, `grafana`, `authelia`, `crowdsec-db`, `crowdsec-config`. No ADR decided that. They are all in `infra/k8s/base/`, and both overlays inherit base, so the topology was set as a side effect of where a file was filed.

Three of them turned out to be inert. Staging `gitea`, `n8n` and `minio` are empty and unused — the operator tests directly in prod — and staging `minio` has no consumer whatsoever, because the only writer is the PVC backup CronJob in `overlays/prod/backup.yaml`, which exists solely in the prod overlay.

Two premises that felt solid were wrong. The vault's `context.md` hardware inventory said Gitea runs on Beelink; the manifests say it is in `base/` and serving on both `gitea.staging.kubelab.live` and `gitea.kubelab.live`, and it appears nowhere in `beelink_services`. A prod e2e run confirmed it live (`TestAPIJsonKeys::test_api_json_contains_keys[gitea]` green against `/api/v1/version`). So #507 — "Deploy Gitea on VPS prod K3s", open and untouched since 2026-06-11 — describes work whose headline was already done.

**Solution:** Two independent axes, not one, recorded as ADR028-004 (#988):

- **Axis 1, environment:** does the state have a promotion path in git? Grafana dashboards and Authelia config do (they are ConfigMaps in git), so staging validates and prod receives the same thing. Gitea repos, n8n workflows and MinIO objects do not.
- **Axis 2, location:** ADR-028's 3 AM test. Independent of axis 1 — "prod" is an environment, not a machine.

A reference audit found no counter-example: `khuedoan/homelab` declares multi-environment support for workloads but defines `platform/gitea` once; `onedr0p/home-ops` runs one cluster; GitLab's own docs prescribe testing upgrades on a *clone* of production and name "automating production-to-staging restores"; a Gitea mirror is read-only by design to preserve one canonical instance; and the Argo CD management/workload split exists specifically to avoid duplicating platform services per environment.

**Rule:**
- **If the state has no promotion path, a second instance is not a test bed — it is a fork.** That single question sorts the platform tier from the workload tier, and it is mechanisable, unlike "which services feel like they should be duplicated".
- **`base/` in Kustomize is a silent multiplier.** Putting a stateful service there is a topology decision wearing a packaging decision's clothes. It duplicates the PVC per overlay with nothing recording that anyone chose it.
- **The cheapest moment to place a stateful service is before it has state.** Empty means "delete and redeploy"; six months of repos later the same move is a migration with a downtime window and metadata (issues, PRs, webhooks) that git clones do not replicate.
- **Do not host your control plane's source of truth behind the infrastructure that control plane rebuilds.** Argo CD keeps reconciling from GitHub rather than from the self-hosted Gitea, for the same reason ADR-015 keeps Headscale outside K3s and the Ansible inventory addresses the VPS by public IP — third instance of one doctrine, in three layers.
- **Trust order held, and it is worth re-stating because the stale source was the vault:** code > repo ADRs > `context.md` > auto-memory. Verify placement against manifests, then against a live probe; never against a hardware inventory in prose.

**Tags:** `#kustomize` `#topology` `#stateful` `#gitea` `#minio` `#n8n` `#adr-028` `#adr-037` `#circular-dependency` `#ssot-drift` `#adr028-004`
