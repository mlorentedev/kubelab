---
id: operate-from-new-workstation
type: runbook
status: active
created: "2026-06-21"
owner: manu
---

# Operate the KubeLab clusters from a new workstation

> Run `kubectl`, `make apply-secrets`, and `make deploy-k8s` against any cluster
> (staging / prod / hub) from a fresh machine -- including a **corporate, non-admin**
> Windows box with no native Tailscale. Two steps: fetch a kubeconfig once, bring up
> the transport per session. Implements ADR-052 (`fetch-kubeconfig` + `k8s access`).

## How it works (the one idea)

Every fetched kubeconfig pins its apiserver to a **stable local endpoint**,
`https://127.0.0.1:<local_port>` -- never a mesh name or a public IP. That works on
*every* machine because the k3s server certificate's SANs include `127.0.0.1`, so TLS
still verifies. The **transport** is what maps that local port to the real apiserver,
and it is swappable per machine:

| Env | local_port | Transport | Target (derived from the SSOT) |
|-----|-----------|-----------|--------------------------------|
| staging | 16443 | ts-bridge over the mesh | `networking.nodes.ace1.tailscale_ip:6443` |
| prod | 16444 | **direct public endpoint, no tunnel** | `networking.vps.public_ip:6443` |
| hub | 16445 | ts-bridge over the mesh | `networking.aws.tailscale_ip:6443` |

The kubeconfig is stable; only the transport changes. That is what lets one
convention serve a native-Tailscale laptop, a CI runner, and a non-admin box alike.

## Prerequisites

- **ts-bridge** installed and its `.env` configured (`TS_AUTHKEY` + `TS_CONTROL_URL=https://vpn.kubelab.live`).
  Full install + Headscale pre-auth-key steps: [`non-admin-workstation-access.md`](non-admin-workstation-access.md) §3.
  The toolkit reuses **ts-bridge's own** `.env` credentials -- it never handles the Headscale key itself.
- **SSH access** to the cluster's k3s server node (for the one-time `fetch-kubeconfig`),
  with the agent loaded so the passphrase is entered once:
  `eval "$(ssh-agent -s)" && ssh-add ~/.ssh/id_ed25519` (Git Bash, no admin).
  See [`non-admin-workstation-access.md`](non-admin-workstation-access.md) for the SSH paths and passphrase ergonomics.
- The repo checked out, toolkit installed (`make setup`).

## Step 1 -- Fetch the kubeconfig (once per machine, per cluster)

This SSHes to the k3s server, reads its admin kubeconfig, rewrites the apiserver to
`https://127.0.0.1:<local_port>`, and saves `~/.kube/kubelab-<env>-config` (0600). It
needs an **interactive** shell (the SSH read prompts for the key) -- run it yourself,
not from an unattended agent.

```bash
make fetch-kubeconfig ENV=staging
```

## Step 2 -- Bring up the transport (per session)

```bash
make connect ENV=staging          # idempotent: a clean no-op if already up
```

- **staging / hub** spawn ts-bridge detached, mapping `127.0.0.1:<local_port>` to the
  node's mesh address, and wait for the local port to answer before returning.
- **prod** starts no tunnel -- it verifies the public apiserver is reachable and
  reports it. (The prod kubeconfig targets the public endpoint directly.)

Locate the ts-bridge binary via `TS_BRIDGE_BIN`, else `~/Apps/ts-bridge/`, else `PATH`.

## Step 3 -- Use the cluster

```bash
kubectl --kubeconfig ~/.kube/kubelab-staging-config get ns
make apply-secrets ENV=staging
make deploy-k8s   ENV=staging
```

## Inspect / tear down

```bash
make connect-status ENV=staging   # up/down + the resolved transport
make disconnect     ENV=staging   # terminates ts-bridge, removes the statefile
```

State for `disconnect` lives in `~/.kube/.kubelab-transport-<env>.json` (pid + port + target).

## Gotchas

- **One transport at a time.** v1 keeps a single ts-bridge instance up; switching env
  means `disconnect` then `connect`. Simultaneous multi-cluster tunnels are tracked as
  ts-bridge#186.
- **`fetch-kubeconfig` / `connect` need your interactive shell.** Passphrase SSH and
  ts-bridge bring-up cannot run non-interactively -- the toolkit is the deliverable, you
  run the bootstrap (ADR-052).
- **ts-bridge must have `TS_CONTROL_URL=https://vpn.kubelab.live` in its `.env`.** Without
  it the `hskey-` auth key hits Tailscale SaaS and fails -- the transport never comes up
  and `connect` times out waiting for the local port.
- **prod is the public path.** `make connect ENV=prod` is a reachability check, not a
  tunnel; if prod's apiserver is firewalled from your network, it reports UNREACHABLE.
- **No hardcoded addresses.** Targets are derived from `clusters.<env>.node` against
  `networking.*` in `common.yaml`; change a node's `tailscale_ip` there and the
  transport follows. Nothing to edit in code or kubeconfig.

## Verify

```bash
make connect ENV=staging && kubectl --kubeconfig ~/.kube/kubelab-staging-config get ns
make connect ENV=staging                       # second run is a clean no-op (exit 0)
make connect-status ENV=staging                # reports UP
make disconnect ENV=staging                    # tears it down
```

## References

- [ADR-052](../adr/adr-052-cluster-access-transport.md) -- cluster access transport (this is its `connect` step)
- [`non-admin-workstation-access.md`](non-admin-workstation-access.md) -- ts-bridge install, Headscale pre-auth key, SSH paths, passphrase agent
- [`headscale-setup.md`](headscale-setup.md) -- Headscale operations, §7 ts-bridge
- `specs/TOOL-014-k8s-connect/` -- the spec behind these commands; tracking issue kubelab#731
