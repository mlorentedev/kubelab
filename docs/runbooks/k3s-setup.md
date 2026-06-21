---
id: "kubelab-runbook-k3s-setup"
type: runbook
status: active
tags: [runbook, kubelab, k3s, kubernetes]
created: "2026-02-20"
last_tested: 2026-06-20
owner: manu
---
# K3s Cluster Setup

Install and configure a **single-node K3s cluster** on a KubeLab node. Since
ADR-023 Phase 1, KubeLab runs bare-metal all-in-one nodes (the old 3-VM Proxmox
topology — `k3s-server` + two agents — was retired). The server schedules
workloads directly; there are no separate agent nodes.

This runbook is **IaC-driven**: K3s is installed and configured by the
`k3s_server` Ansible role, never by hand. For upgrading an existing cluster, see
[k3s-upgrade](k3s-upgrade.md).

## Cluster inventory

| Cluster | Node | Identity | Traefik | Datastore | Notes |
|---------|------|----------|---------|-----------|-------|
| staging | `ace1` (Acemagic-1) | `172.16.1.2` / `100.64.0.11` (MagicDNS) | bundled + ACME | kine/SQLite | all-in-one; on-demand homelab |
| prod | VPS Hetzner | `162.55.57.175` / `100.64.0.2` | bundled + ACME | kine/SQLite | always-on |
| hub | `aws1` (t4g.small Spot) | `aws1.kubelab.internal` (MagicDNS) | **disabled** (Argo CD only) | kine/SQLite | cattle (Terraform cloud-init) |

All clusters run **single-server mode without `--cluster-init`**, so cluster
state lives in **kine (SQLite)** at `/var/lib/rancher/k3s/server/db/state.db`,
not embedded etcd. Namespace for workloads: `kubelab`. K3s version SSOT:
`infra/config/values/common.yaml` → `k3s.version`.

## Prerequisites

- Node reachable over SSH with NOPASSWD sudo (all nodes hardened, 2026-03-20).
  For a brand-new node, bootstrap NOPASSWD manually first, then provision with
  `ASK_PASS=1`.
- Headscale VPN mesh operational (`vpn.kubelab.live`) — the node joins the mesh
  during provisioning. See [headscale-setup](headscale-setup.md).
- Controller (workstation) has the repo, Poetry env (`make setup`), SOPS age key,
  and the SSH key authorized on the node.
- Cloudflare API token in SOPS (`cloudflare.api_token`) for Traefik ACME DNS-01.

## Install: full node provisioning

The `provision-<node>` playbook provisions everything end-to-end — base system,
SSH hardening, Docker, Tailscale (Headscale join), the K3s server, and Glances.
K3s is one tagged role inside it.

```bash
# staging (ace1)
make provision NODE=ace1 ENV=staging

# First run, before the node is on the VPN — uses the LAN IP from common.yaml
make provision NODE=ace1 ENV=staging BOOTSTRAP=1

# prod (VPS) / hub (aws1)
make provision NODE=vps  ENV=prod
make provision NODE=aws1 ENV=hub
```

To run **only** the K3s role on an already-provisioned node (e.g. to apply a
config change), filter by tag — or use the dedicated deploy playbook:

```bash
make provision NODE=ace1 ENV=staging TAGS=k3s
# equivalent K3s-only deploy across the env's k3s_servers group:
make deploy TARGET=k3s ENV=staging
```

## What the `k3s_server` role does

Defined in `infra/ansible/roles/k3s_server/`, driven by SSOT values from
`common.yaml`/`<env>.yaml`:

1. **Asserts** `k3s_version` and `k3s_tls_san` are provided (no silent defaults).
2. **Detects** the installed version; only (re)installs when missing or when the
   target version differs — the role is idempotent.
3. **Templates** `/etc/rancher/k3s/config.yaml`:
   - `tls-san` — API cert SANs, built from the inventory: Tailscale IP + LAN IP
     (and **public IP** on the VPS). Prod must cover both `162.55.57.175` and
     `100.64.0.2`.
   - `resolv-conf: /run/systemd/resolve/resolv.conf` — required on
     systemd-resolved hosts so pods can resolve external names (the default
     `/etc/resolv.conf` points at the `127.0.0.53` stub, unreachable from pods).
4. **Installs** K3s via `get.k3s.io` with `INSTALL_K3S_VERSION`, then ensures the
   `k3s` systemd unit is started + enabled and waits for the API to be ready.
5. **Bootstraps cluster manifests** by templating into
   `/var/lib/rancher/k3s/server/manifests/` (K3s auto-applies this directory):
   - the Cloudflare API-token Secret (when ACME is enabled), and
   - the Traefik `HelmChartConfig` (ports + ACME + plugins, ADR-015) — skipped on
     the hub, where `configure_traefik: false`.
6. **Fetches the kubeconfig** to the controller at
   `~/.kube/kubelab-<env>-config`, rewriting the server URL from `127.0.0.1` to
   the node's reachable address (Tailscale IP, or MagicDNS name on the hub).

> **Why `tls-san` must be right before first start:** K3s generates the API TLS
> cert at install time. If the Tailscale IP / public IP isn't in the SAN list,
> `kubectl` over the VPN fails cert validation. Changing SANs later requires
> regenerating the cert (remove `/var/lib/rancher/k3s/server/tls/` and restart).

## Workstation access (VPN + MagicDNS)

Cluster access is over the **Headscale VPN mesh** — not a static LAN route. The
role already wrote `~/.kube/kubelab-<env>-config` with the correct server URL and
embedded CA, so once your workstation is on the mesh:

```bash
export KUBECONFIG=~/.kube/kubelab-staging-config   # or -prod / -hub
kubectl get nodes -o wide
```

Merge multiple cluster configs if you switch often:

```bash
export KUBECONFIG=~/.kube/config:~/.kube/kubelab-staging-config:~/.kube/kubelab-prod-config
```

If `kubectl` can't reach the API:

1. Confirm you're on the mesh: `tailscale status` (or `tailscale ping ace1`).
2. Confirm the server URL: `grep server ~/.kube/kubelab-staging-config` — should
   be the node's Tailscale IP / MagicDNS name, not `127.0.0.1`.
3. Re-fetch a stale kubeconfig by re-running the role (`make provision NODE=…
   TAGS=k3s`) — it overwrites the file with the current address + CA.

## Verify the cluster

```bash
kubectl get nodes -o wide        # node Ready, expected K3s version
kubectl get ns kubelab           # workload namespace exists
kubectl get pods -A              # kube-system + workloads healthy
kubectl cluster-info
```

## Traefik TLS (Let's Encrypt DNS-01)

Spoke clusters ship the bundled Traefik as the ingress controller, configured by
the role's `HelmChartConfig` for ACME via **Cloudflare DNS-01**. Key facts:

- The cert resolver is named **`letsencrypt`** (Cloudflare is the DNS challenge
  *provider*, not the resolver name).
- The Cloudflare token Secret lives in **`kube-system`** (where Traefik runs).
- ACME storage **must be persisted** (`persistence.enabled: true`) — an
  `emptyDir` loses certs on every pod restart and re-hits the Let's Encrypt rate
  limit (5 certs / domain set / 168h).

Verify issuance after deploying an IngressRoute:

```bash
kubectl logs -n kube-system -l app.kubernetes.io/name=traefik | grep -i acme
curl -vk https://web.staging.kubelab.live 2>&1 | grep -E 'subject|issuer'
```

The HelmChartConfig is **managed by Ansible** (template
`infra/ansible/roles/k3s_server/templates/traefik-helmconfig.yaml.j2`) — do not
create a static `HelmChartConfig` in `infra/k8s/`.

## Maintenance

### Restart K3s

```bash
ssh ace1 "sudo systemctl restart k3s"
```

A restart is non-destructive (kine/SQLite persists) and is the correct fix when
the server wedges after a bulk delete (`futex` deadlock — see `lessons.md`,
2026-05-10). It costs ~1–2 min of API downtime.

### Upgrade K3s

Do **not** re-run `curl | sh` by hand. Single-node upgrades require a maintenance
window and a datastore backup — follow [k3s-upgrade](k3s-upgrade.md).

### Uninstall K3s (destroys the cluster)

```bash
ssh ace1 "sudo /usr/local/bin/k3s-uninstall.sh"
```

## Reference

| Item | Value |
|------|-------|
| K3s version (SSOT) | `common.yaml` → `k3s.version` (`v1.34.4+k3s1`) |
| Staging node | `ace1` — `172.16.1.2` / `100.64.0.11` |
| Prod node | VPS — `162.55.57.175` / `100.64.0.2` |
| Hub node | `aws1` — `aws1.kubelab.internal` (MagicDNS) |
| Datastore | kine / SQLite (`/var/lib/rancher/k3s/server/db/state.db`) |
| Namespace | `kubelab` |
| API port | `6443` |
| Kubeconfig | `~/.kube/kubelab-<env>-config` |
| Cert resolver | `letsencrypt` (Cloudflare DNS-01) |
| Ansible role | `infra/ansible/roles/k3s_server` |
| Install playbooks | `provision-ace1.yml` / `provision-vps.yml` / `provision-aws1.yml`, `deploy-k3s.yml` |

## Related

- [k3s-upgrade](k3s-upgrade.md) — version upgrade procedure (maintenance window)
- [headscale-setup](headscale-setup.md) — VPN mesh (cluster access transport)
- [dns-homelab](dns-homelab.md) — CoreDNS for staging domain resolution
- [operations](operations.md) — master deploy flows
- [hardware-setup](hardware-setup.md) — node hardware allocation
