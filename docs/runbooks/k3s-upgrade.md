---
id: "kubelab-runbook-k3s-upgrade"
type: runbook
status: active
tags: [runbook, kubelab, k3s, kubernetes, upgrade, maintenance]
created: "2026-06-20"
last_tested: null
owner: manu
---
# K3s Single-Node Cluster Upgrade

> Upgrade the K3s version on KubeLab's single-node clusters. Because every
> cluster is a **single node**, there is no drain target — upgrades require a
> short **maintenance window** with control-plane and ingress downtime. This is
> the planned, idempotent procedure; do not run `curl | sh` by hand.

> **Not yet exercised against a live cluster** (`last_tested: null`). Empirical
> validation in staging is tracked in OPS-011 (#722).

## The core constraint: no drain target

On a multi-node cluster you `kubectl drain` a node to reschedule its pods
elsewhere, then upgrade it with zero user impact. **KubeLab clusters have one
node each** (ADR-023 Phase 1 collapsed the old 3-VM topology into all-in-one
nodes), so:

- `kubectl drain` has nowhere to move pods to — it just evicts workloads that
  cannot be rescheduled. **Do not drain.**
- `kubectl cordon` is pointless for the same reason (nothing else to schedule on).
- The upgrade is an **in-place binary swap + `systemctl restart k3s`**. Running
  workload containers (managed by containerd) generally survive the restart, but
  a Kubernetes **minor** bump rolls the `kube-system` components (Traefik,
  CoreDNS, metrics-server) — so expect a **DNS + ingress blip of ~1–3 minutes**
  and an API-server outage for ~30–60 s.

> **Conclusion:** schedule a maintenance window, do staging first, and accept the
> blip. There is no rolling, zero-downtime path on a one-node cluster.

## Cluster inventory

| Cluster | Node | Identity | K3s flavour | Managed by | Upgrade route |
|---------|------|----------|-------------|------------|---------------|
| staging | `ace1` (Acemagic-1) | `172.16.1.2` / `100.64.0.11` (MagicDNS) | server + Traefik (all-in-one) | Ansible `k3s_server` role | Procedure A |
| prod | VPS Hetzner | `162.55.57.175` / `100.64.0.2` | server + Traefik | Ansible `k3s_server` role | Procedure A |
| hub | `aws1` (t4g.small Spot) | `aws1.kubelab.internal` (MagicDNS) | server, **no Traefik/servicelb** (Argo CD only) | Terraform cloud-init (cattle) | Procedure B |

All three run **single-server mode without `--cluster-init`**, so the datastore
is **kine/SQLite**, not embedded etcd (see next section).

## The datastore reality: kine/SQLite, not etcd

K3s only enables embedded etcd when started with `--cluster-init` (or an external
datastore is configured). None of our clusters do, so each one stores cluster
state in **kine — a shim that presents an etcd API over a local SQLite file** at:

```text
/var/lib/rancher/k3s/server/db/state.db
```

Operational consequences for upgrades:

- **`k3s etcd-snapshot` does NOT work here.** The `etcd-snapshot-*` settings in
  `common.yaml`/`hub.yaml` are inert on a kine/SQLite cluster — they only take
  effect once embedded etcd exists.
- **There are no automated datastore snapshots yet** (that is the open work in
  BACKUP-012, issue #464). Until then, the pre-upgrade backup below is a
  **manual, file-level copy of the SQLite DB** — it is the only rollback safety
  net for a bad upgrade.

## Pre-flight checklist

Run every step before touching a cluster. Staging is the canary; never upgrade
prod or the hub before staging has soaked clean.

1. **Pick the target version, one minor at a time.** Kubernetes supports
   upgrading **one minor version per hop** (`n` → `n+1`, e.g. `v1.34` → `v1.35`).
   Do not skip minors. Patch bumps within a minor (`v1.34.4` → `v1.34.6`) are
   safe and can be done directly. Use the canonical K3s release tag format,
   e.g. `v1.35.2+k3s1`.
2. **Read the release notes.** Check the
   [K3s releases](https://github.com/k3s-io/k3s/releases) and the upstream
   Kubernetes changelog for the target minor: removed/deprecated APIs, the
   **bundled Traefik chart version bump** (it can change Traefik major versions —
   reconcile against our `traefik-helmconfig.yaml.j2`), and any CNI/CoreDNS notes.
3. **Scan for removed APIs.** OPS-010 (issue #701) will add a `toolkit`
   pluto/kubent gate as a required pre-flight; until it lands, run the manual
   fallback:

   ```bash
   # Manifests (rendered Kustomize) + live cluster
   pluto detect-files -d infra/k8s/
   kubent --context <env>          # live-cluster scan
   ```

   A **removed** API in the target version is a hard blocker — fix the manifest
   and merge it before upgrading.
4. **Confirm the cluster is healthy** (a sick cluster must not be upgraded):

   ```bash
   export KUBECONFIG=~/.kube/kubelab-staging-config   # or -prod / -hub
   kubectl get nodes -o wide          # Ready, expected version
   kubectl get pods -A | grep -vE 'Running|Completed'   # should be empty
   ```

   For spokes, also confirm Argo CD shows the app **Synced + Healthy** at
   `https://argo.kubelab.live`.
5. **Check disk headroom.** A K3s restart pulls new component images; a node
   above ~80% disk can trip the kubelet disk-pressure threshold (85%) mid-upgrade
   and go `NotReady` (see `lessons.md`, 2026-05-10 RELIAB-009 incidents). Free
   disk first:

   ```bash
   make maintain NODE=ace1        # or vps / aws1 — prunes logs, images, caches
   ```

6. **Back up the datastore (SQLite).** We are already in a window, so the clean
   method is stop → copy → restart:

   ```bash
   STAMP=$(date +%Y%m%d-%H%M%S)
   sudo systemctl stop k3s
   sudo tar czf /root/k3s-db-backup-$STAMP.tar.gz \
     -C / var/lib/rancher/k3s/server/db \
          var/lib/rancher/k3s/server/token \
          var/lib/rancher/k3s/server/tls \
          etc/rancher/k3s/config.yaml
   sudo systemctl start k3s
   ```

   Copy the tarball off-node. (If `sqlite3` is installed you can instead take a
   live, no-downtime snapshot: `sqlite3 /var/lib/rancher/k3s/server/db/state.db \
   ".backup /root/state-$STAMP.db"`.)
7. **Pause Argo CD self-heal on prod (optional).** Prod runs with
   `selfHeal: true` (ADR-037). An upgrade does not touch app manifests, so this
   is usually unnecessary — but if you expect to roll back, set the prod
   Application to manual sync first so Argo doesn't fight a downgrade.
8. **Announce the window.** Prod ingress and Argo CD UI will blip.

## Procedure A — Ansible-managed pets (ace1, VPS)

The `k3s_server` role is idempotent: it compares the installed binary version
against `config.k3s.version` and, only on mismatch, re-runs the install script
with `INSTALL_K3S_VERSION`, which swaps the binary and restarts the `k3s` unit.
The role then waits for the API to be ready and asserts all nodes are `Ready`.

1. **Bump the version SSOT** in `infra/config/values/common.yaml`:

   ```yaml
   k3s:
     version: "v1.35.2+k3s1"   # was v1.34.4+k3s1
   ```

2. **Upgrade staging first:**

   ```bash
   make deploy TARGET=k3s ENV=staging
   ```

   This runs `deploy-k3s.yml` against the `k3s_servers` group (ace1 in staging),
   applies the upgrade, and runs the built-in "Verify K3s cluster health" play.
3. **Soak staging.** Run the [verification](#verification) below and
   `make test-e2e ENV=staging`. Let it sit long enough to surface CrashLoops or
   ingress regressions.
4. **Upgrade prod** only after staging is green:

   ```bash
   make deploy TARGET=k3s ENV=prod
   ```

   (In prod the `k3s_servers` group is the VPS — see `prod.yaml` overrides.)
5. **Commit the bump** on a feature branch and open a PR — the version change is
   the audit record of the upgrade.

> **Re-running on a node already at the target version is a no-op** — the role
> detects the match and skips the install/restart, so `make deploy TARGET=k3s` is
> safe to re-run.

## Procedure B — aws1 hub (cattle / Terraform)

The hub is **cattle** (ADR-026): K3s is installed by Terraform **cloud-init**,
with `--disable=traefik --disable=servicelb` baked into the systemd `ExecStart`.
Its installed version is driven by a **separate declaration** from the spokes:

| What | Where | Note |
|------|-------|------|
| Spoke version SSOT | `common.yaml` → `k3s.version` | drives Procedure A |
| Hub version | `infra/terraform/aws/variables.tf` → `k3s_version` (+ `aws.tfvars`) | drives cloud-init |

> **Gotcha — bump both.** These two values are kept equal by hand
> ("match spoke versions"). A cluster upgrade must update **both** or the hub
> drifts from the spokes.

**Preferred route — replace (cattle-native, deterministic):**

1. Bump `k3s_version` in `infra/terraform/aws/variables.tf` (and `aws.tfvars` if
   set) to match `common.yaml`.
2. Replace the instance and re-bootstrap the management plane (this is the same
   flow as the operations runbook's "AWS infrastructure" section):

   ```bash
   make tf-aws-apply            # or: terraform apply -replace=<spot_instance>
   make fetch-kubeconfig-hub    # new host key + MagicDNS server URL
   make deploy-argocd           # Helm install Argo CD on the fresh node
   make deploy-apps             # re-register Applications
   make register-spoke ENV=staging
   make register-spoke ENV=prod
   ```

   Replacement loses the hub's kine state, which is acceptable: the hub holds
   only Argo CD, and Argo CD's source of truth is Git. Spoke clusters are
   untouched.

Avoid the in-place Ansible path (`make provision NODE=aws1 ENV=hub TAGS=k3s`)
for the hub: re-running the install script can regenerate the systemd unit
**without** the cloud-init `--disable=traefik --disable=servicelb` flags,
re-enabling components the hub deliberately omits. Replacement sidesteps that
entirely and matches the cattle model.

## Verification

```bash
# 1. Node is Ready and reports the new version
kubectl get nodes -o wide

# 2. No system pods stuck after the component roll
kubectl get pods -A | grep -vE 'Running|Completed'

# 3. Spokes: Argo CD app is Synced + Healthy
#    → https://argo.kubelab.live   (or: argocd app list)

# 4. Smoke an ingress + TLS (spokes only — hub has no Traefik)
curl -sI https://web.staging.kubelab.live | head -1     # expect 200
curl -vk https://web.staging.kubelab.live 2>&1 | grep -E 'subject|issuer'
```

For staging, finish with `make test-e2e ENV=staging`.

## Rollback

A Kubernetes **minor** downgrade is **not supported** — the apiserver migrates
the datastore schema on upgrade and will not cleanly read it after a downgrade.
So rollback is not "reinstall the old binary"; it is **restore the pre-upgrade
SQLite backup AND reinstall the previous binary version**:

1. Stop K3s: `sudo systemctl stop k3s`.
2. Restore the datastore from the pre-flight tarball:

   ```bash
   sudo tar xzf /root/k3s-db-backup-<STAMP>.tar.gz -C /
   ```

3. Pin the previous version in `common.yaml` (spokes) or `variables.tf` (hub)
   and re-run the matching procedure so the **previous** binary is reinstalled.
4. Start K3s and re-run [verification](#verification).

A **patch-level** rollback within the same minor is lower-risk: re-pinning the
previous patch and re-running Procedure A is usually sufficient (the schema is
unchanged), but restoring the DB backup is still the safe default.

Last-resort recovery if a node is unrecoverable:

- **VPS (prod):** [rollback-k3s-to-compose](rollback-k3s-to-compose.md) reverts
  prod to the Docker Compose Traefik stack.
- **Full rebuild:** [runbook-disaster-recovery](runbook-disaster-recovery.md).

## Post-upgrade

- Re-enable prod Argo CD self-heal if you paused it in pre-flight step 7.
- Update the `last_tested` frontmatter date in this runbook.
- Close the upgrade PR; for the tracking issue, the built-in workflow moves it to
  Done on close.

## Reference

| Item | Value |
|------|-------|
| Current version | `v1.34.4+k3s1` |
| Spoke version SSOT | `infra/config/values/common.yaml` → `k3s.version` |
| Hub version | `infra/terraform/aws/variables.tf` → `k3s_version` |
| Datastore | kine / SQLite (`/var/lib/rancher/k3s/server/db/state.db`) |
| Upgrade command (spokes) | `make deploy TARGET=k3s ENV=staging\|prod` |
| Ansible role | `infra/ansible/roles/k3s_server` |
| Playbook | `infra/ansible/playbooks/deploy-k3s.yml` |
| Disk pre-flight | `make maintain NODE=<node>` |
| E2E | `make test-e2e ENV=staging` |

## Related

- [k3s-setup](k3s-setup.md) — initial single-node cluster install
- [operations](operations.md) — master deploy flows; aws1 recreate sequence
- [rollback-k3s-to-compose](rollback-k3s-to-compose.md) — prod fallback to Compose
- [runbook-disaster-recovery](runbook-disaster-recovery.md) — full rebuild
- [pre-prod-verification](pre-prod-verification.md) — pre-change validation
- BACKUP-012 (#464) — automated datastore snapshots (pending)
- OPS-010 (#701) — pre-upgrade API-deprecation gate (pending)
- OPS-011 (#722) — empirical validation of this runbook in staging (sets `last_tested`)
