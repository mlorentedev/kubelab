---
id: non-admin-workstation-access
type: runbook
status: active
created: "2026-06-20"
owner: manu
---

# Access the KubeLab fleet from a non-admin workstation

> Reach every fleet node over SSH (and selected services over RDP/HTTP) from a
> **corporate, non-admin** Windows box that **cannot install native Tailscale**
> (no admin, no TUN device). Three access paths, in order of preference for SSH.
> Validated 2026-06-20 from `EGW-LEN029`.

## TL;DR — pick a path

| Path | Use when | Reaches | New software |
|------|----------|---------|--------------|
| **LAN direct** (`ssh <node>-lan`) | On the home network | homelab nodes via `rpi4-lan` jump | none |
| **Bastion** (`ssh <node>-ext`) | **Anywhere — the default for SSH** | the whole mesh, one jump via the VPS | none |
| **ts-bridge** | RDP / web UI / a single service by mesh IP | one target per bridge instance | the `ts-bridge` binary |

For SSH the **bastion** wins: one jump, all nodes, no daemon. `ts-bridge` is for
non-SSH protocols where a jump host doesn't help (RDP to a desktop, a web UI on a
mesh IP). They coexist.

## The constraint

This box is non-admin, so native Tailscale is off the table (it needs admin + a
persistent TUN interface). Without a mesh interface there is **no local route for
`100.64.0.0/10`**, so the `~/.ssh/config` *primary* host blocks (`Host rpi4 →
100.64.0.10`) — which assume a native mesh node like `msi` — do **not** resolve
from here. The two workarounds below avoid needing a local route.

## Prerequisites

- **SSH key** `~/.ssh/id_ed25519` — the `manu@msi` identity, already authorized on
  every node (`docs/runbooks/ssh-keys.md`). It is **passphrase-protected**, so
  every connection prompts unless an agent is loaded (see [Passphrase ergonomics](#passphrase-ergonomics)).
- **`~/.ssh/config`** — deployed from the `dotfiles` repo (`ssh/config`, block
  `KUBELAB-SSH`). Provides the `*-lan`, `*-ext`, and `vps-pub` host aliases used below.
- Outbound reachability to the VPS public IP `162.55.57.175` (ports 22 / 443 / 6443).

### Node reference (Headscale mesh)

| Node | Mesh IP | SSH user | Notes |
|------|---------|----------|-------|
| vps  | 100.64.0.2  | deployer | also `vps-pub` = 162.55.57.175 (public, always reachable) |
| aws1 | 100.64.0.7  | deployer | ArgoCD hub — **mesh-only**, no LAN fallback |
| rpi4 | 100.64.0.10 | manu | home-LAN jump host (`rpi4-lan` = 10.0.0.131) |
| rpi3 | 100.64.0.6  | manu | |
| ace1 | 100.64.0.11 | manu | K3s staging |
| ace2 | 100.64.0.5  | manu | Ollama |
| bee  | 100.64.0.3  | manu | |
| jet1 | 100.64.0.8  | manu | |

On-demand homelab nodes (ace1/ace2/bee/rpi4/rpi3/jet1) are only up when powered.
vps / aws1 are always-on.

## Path 1 — LAN direct (at home)

When physically on the home network, the `*-lan` aliases reach the homelab without
any VPN. `rpi4-lan` is a direct host; the rest jump through it.

```bash
ssh rpi4-lan 'hostname'          # direct (10.0.0.131)
ssh ace1-lan 'hostname'          # via ProxyJump rpi4-lan
```

## Path 2 — Bastion (anywhere) — preferred for SSH

The VPS is reachable by public IP from anywhere and is itself on the mesh, so it
works as a jump host to every node. The `*-ext` aliases bake this in:

```bash
ssh rpi4-ext 'hostname'          # laptop -> vps-pub -> mesh -> rpi4
ssh ace1-ext 'hostname'
ssh aws1-ext 'hostname'          # the mesh-only hub, no LAN path ever
```

Equivalent one-off without the alias: `ssh -J vps-pub rpi4`.

> **Why not just `ssh rpi4`?** The primary blocks point at mesh IPs with no jump, so
> they only work from a native-Tailscale machine (e.g. `msi`). The `*-ext` aliases
> are the non-admin equivalent. (The shared `ssh/config` keeps the primaries
> jump-free so `msi` still routes directly.)

## Path 3 — ts-bridge (RDP / web UI / single service)

`ts-bridge` (own project) runs a **userspace** Tailscale node (`tsnet`, no admin, no
TUN) and forwards **one local port → one mesh target**. Use it when a jump host
doesn't help — e.g. RDP to a desktop, or a web UI you want at `127.0.0.1:<port>`.

### 3.1 Install (as an external user would)

Download the release artifact, verify the checksum, extract. No build toolchain
needed.

```powershell
$dest = "$env:USERPROFILE\Apps\ts-bridge"    # stable location (NOT %TEMP%)
New-Item -ItemType Directory -Force $dest | Out-Null
gh release download --repo mlorentedev/ts-bridge `
  --pattern 'ts-bridge-*-windows-amd64.zip' --pattern 'checksums.txt' --dir $dest
# verify SHA256 against checksums.txt before extracting, then:
Expand-Archive "$dest\ts-bridge-*-windows-amd64.zip" "$dest\bin" -Force
& "$dest\bin\ts-bridge-windows-amd64\ts-bridge.exe" version
```

### 3.2 Mint a Headscale pre-auth key

Personal devices live under the **`kubelab`** Headscale user (ID **2**) — same as
`msi` and all infra nodes. (`manu`/ID 1 only holds a stale `localhost`; don't use it.)

```bash
ssh vps-pub 'docker exec headscale headscale preauthkeys create \
  --user 2 --reusable --ephemeral --expiration 8760h'
```

- `--ephemeral` is **required** — Headscale (not the client) controls ephemerality;
  without it the node persists as an offline entry forever.
- `--reusable` + `8760h` (1 year): one key serves restarts and survives travel.

### 3.3 Configure `.env`

In the binary's directory:

```env
TS_AUTHKEY=hskey-...                  # the key from 3.2 — keep it here, not in shell history
TS_TARGET=100.64.0.11:22              # target = <mesh IP>:<port>, e.g. ace1 SSH
TS_CONTROL_URL=https://vpn.kubelab.live   # REQUIRED — without it the key hits Tailscale SaaS and fails
TS_LOCAL_ADDR=127.0.0.1:33389         # pin the local port (auto-mode randomizes it in 33389-34388)
```

### 3.4 Connect and use

```bash
./ts-bridge.exe connect               # foreground; prints the Local: bind address
# in another terminal, against the pinned port:
ssh -p 33389 -o StrictHostKeyChecking=accept-new manu@127.0.0.1 'hostname'
```

`Ctrl-C` stops the bridge; the ephemeral node auto-removes from Headscale.

## Gotchas

- **`Server accepts key` then `Permission denied (publickey)` = passphrase/agent, not
  authorization.** SSH offers the public key (read from `.pub`, no secret needed) and
  the server accepts it, but signing the challenge needs the *decrypted private key*.
  With `BatchMode=yes` and no agent, signing fails silently. Diagnose with `ssh -v`,
  not by assuming the key was revoked.
- **A connectivity sweep with `BatchMode=yes` shows false "DOWN" for every node** if
  the key is locked and no agent is loaded — it can't tell "key locked" from "host
  unreachable". Load an agent first, or read the `-v` output.
- **ts-bridge is a per-target proxy, not a route.** It cannot give you `ssh rpi4`
  (mesh IP) the way native Tailscale does — that needs a TUN device. Use the bastion
  for whole-fleet SSH; use ts-bridge for one service at a time.
- **`TS_CONTROL_URL` is what selects Headscale.** The `hskey-`/`tskey-` prefix does
  not route; an `hskey` sent without `TS_CONTROL_URL=https://vpn.kubelab.live` hits
  Tailscale SaaS and fails with `invalid key`.
- **Headscale user for a personal device = `kubelab` (2)**, matching `msi` and infra —
  not `manu` (1). Keeps inventory and (future VPNACL-001) ACLs coherent.
- **ts-bridge auto-mode randomizes the local port** (`TS_PORT_RANGE` 33389-34388) and
  the node name, to allow multiple concurrent bridges. Pin with `TS_LOCAL_ADDR` (hard
  port) or `TS_INSTANCE_NAME` (deterministic port) for a stable SSH alias.

## Passphrase ergonomics

`~/.ssh/id_ed25519` has a passphrase and the Windows `ssh-agent` **service is Disabled
(enabling it needs admin)**. To avoid retyping per hop, load a **userspace** agent in
Git Bash (no admin) and work from that shell:

```bash
eval "$(ssh-agent -s)" && ssh-add ~/.ssh/id_ed25519   # one prompt per shell session
```

Note this serves Git Bash's `ssh`; the Windows `ssh.exe` (PowerShell) uses the
disabled service and will keep prompting.

## Cluster access (kubectl)

TOOL-015 (ADR-052) codifies `kubectl` access from a non-admin box into two toolkit commands. No manual ts-bridge setup required — the toolkit handles the tunnel internally.

### Prerequisites

- Git Bash shell with the ssh-agent loaded (see [Passphrase ergonomics](#passphrase-ergonomics) above — **this is mandatory**; running from PowerShell without the Windows SSH Agent service will fail silently with "Connection closed" rather than a passphrase prompt).
- `ts-bridge` installed at `~/Apps/ts-bridge/ts-bridge.exe` with a valid `.env` (see [Path 3](#path-3--ts-bridge-rdp--web-ui--single-service) §3.1–§3.3 for install + key; the `.env` only needs `TS_AUTHKEY` and `TS_CONTROL_URL` for the toolkit-managed tunnel — `TS_TARGET` and `TS_LOCAL_ADDR` are ignored when the toolkit spawns the bridge).
- `KUBECONFIG` not set (or set to `~/.kube/kubelab-staging-config`) — the toolkit writes there.

### Step 1 — Fetch the kubeconfig

```bash
# In Git Bash, after loading ssh-agent:
eval "$(ssh-agent -s)" && ssh-add ~/.ssh/id_ed25519

make fetch-kubeconfig ENV=staging
```

What happens internally:
1. Tries `ssh ace1 sudo cat /etc/rancher/k3s/k3s.yaml` (direct mesh alias).
2. If that returns exit 255 + a connect-error (unreachable mesh IP from non-admin box) → automatically spawns a transient ts-bridge SSH tunnel to `ace1:22`.
3. Re-reads `k3s.yaml` through the tunnel, rewrites the server URL to `https://127.0.0.1:16443`, writes `~/.kube/kubelab-staging-config` at `0600`.

On success: `~/.kube/kubelab-staging-config` is ready. The transient tunnel is torn down immediately after the read.

### Step 2 — Bring up the persistent apiserver tunnel

```bash
make connect ENV=staging
```

This starts ts-bridge in the background, forwarding `127.0.0.1:16443` → `ace1:6443` (the K3s apiserver). The pid is recorded in `~/.kube/.kubelab-transport-staging.json`.

### Step 3 — Use kubectl

```bash
kubectl --kubeconfig ~/.kube/kubelab-staging-config get ns
# or export it:
export KUBECONFIG=~/.kube/kubelab-staging-config
kubectl get ns
```

Expected output (staging): `agent-sandbox-system  default  kube-node-lease  kube-public  kube-system  kubelab`

### Step 4 — Tear down when done

```bash
make disconnect ENV=staging
```

### Quick reference

```bash
# Full session from scratch (Git Bash):
eval "$(ssh-agent -s)" && ssh-add ~/.ssh/id_ed25519
make fetch-kubeconfig ENV=staging     # one-time or after cluster cert rotation
make connect ENV=staging
export KUBECONFIG=~/.kube/kubelab-staging-config
kubectl get ns
# ... work ...
make disconnect ENV=staging
```

### Gotchas for cluster access

- **Run from Git Bash, not PowerShell.** PowerShell's `ssh` uses the Windows SSH Agent Service (Disabled on non-admin). Without an agent, the passphrase prompt is swallowed by `subprocess.run(capture_output=True)` and the connection closes silently, triggering the tunnel fallback, which also closes silently — the root cause (missing agent) is invisible. See the 2026-06-22 lesson in `docs/lessons.md`.
- **`make fetch-kubeconfig` and `make connect` are independent.** Fetch writes the kubeconfig; connect starts the apiserver tunnel. Both are needed, in order. Fetch can be re-run at any time (idempotent overwrite); connect is a no-op if the tunnel is already up.
- **The ts-bridge `.env` only needs two keys for toolkit-managed tunnels.** The toolkit ignores `TS_TARGET` / `TS_LOCAL_ADDR` (it sets those itself). Only `TS_AUTHKEY` and `TS_CONTROL_URL` are read from the `.env` in the binary's directory.
- **If `make connect` shows "ts-bridge exited early"**, check `~/Apps/ts-bridge/.env` — a stale or expired `TS_AUTHKEY` causes an immediate exit. Re-mint a key (§3.2) and update the `.env`.

## Verify

```bash
ssh vps-pub  'echo OK $(hostname)'    # outside path (public IP)        -> OK kubelab-vps
ssh rpi4-lan 'echo OK $(hostname)'    # LAN path (at home)              -> OK rpi4
ssh ace1-ext 'echo OK $(hostname)'    # bastion path (anywhere)         -> OK ace1
ssh aws1-ext 'echo OK $(hostname)'    # mesh-only hub via bastion       -> OK aws1
```

Cluster access verify:

```bash
make fetch-kubeconfig ENV=staging && make connect ENV=staging
kubectl --kubeconfig ~/.kube/kubelab-staging-config get ns
# expected: agent-sandbox-system  default  kube-node-lease  kube-public  kube-system  kubelab
```

## References

- `docs/runbooks/headscale-setup.md` — Headscale operations, pre-auth keys, §7 ts-bridge
- `docs/runbooks/ssh-keys.md` — the authorized key identity
- `docs/runbooks/onboard-vpn-fleet-agent.md` — tagged agent onboarding (ADR-041)
- `docs/runbooks/operate-from-new-workstation.md` — Step 1 has the TOOL-015 auto-fallback note
- [ADR-013](../adr/adr-013-vpn-consolidation.md), [ADR-015] — Headscale outside K3s, VPN consolidation
- [ADR-052](../adr/adr-052-cluster-access-transport.md) — cluster access transport doctrine (TOOL-014/015)
- ts-bridge repo: `mlorentedev/ts-bridge` (README, `docs/adr/adr-005-headscale-compat.md`)
- `docs/lessons.md` §2026-06-22 — ssh-agent mandatory for toolkit SSH on non-admin Windows
