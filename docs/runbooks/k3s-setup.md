---
id: "kubelab-runbook-k3s-setup"
type: runbook
status: active
tags: [runbook, kubelab, k3s, kubernetes]
created: "2026-02-20"
last_tested: 2026-02-20
owner: manu
---
# K3s Cluster Setup

Install and configure a 3-node K3s cluster on KubeLab homelab Proxmox VMs.

## Prerequisites

- Proxmox VMs provisioned (see [hardware-setup](hardware-setup.md) and [proxmox-setup](proxmox-setup.md))
  - `k3s-server` (172.16.1.10) — Acemagic-1, 5GB RAM
  - `k3s-agent-1` (172.16.1.11) — Acemagic-1, 5GB RAM
  - `k3s-agent-2` (172.16.1.12) — Acemagic-2, ~10GB RAM
- SSH access to all VMs via ProxyJump through RPi 4 (see `~/.ssh/config`)
- RPi 4 gateway operational (bridge/NAT between 10.0.0.x and 172.16.1.0/24)

## Network Topology

```
Workstation (10.0.0.x)
    │
    ├─ WiFi ─→ Home Router (10.0.0.1)
    │                │
    │           RPi 4 Gateway (10.0.0.131 / 172.16.1.1)
    │                │
    │           TP-Link Switch
    │                ├── k3s-server  (172.16.1.10)  ← K3s server
    │                ├── k3s-agent-1 (172.16.1.11)  ← K3s agent
    │                └── k3s-agent-2 (172.16.1.12)  ← K3s agent (heavy)
```

## Phase 1: Install K3s Server

SSH into `k3s-server` and configure TLS SAN + install K3s:

```bash
ssh k3s-server

# Configure TLS SAN BEFORE install (includes Tailscale IP for VPN access)
sudo mkdir -p /etc/rancher/k3s
printf 'tls-san:\n  - "100.64.0.4"\n' | sudo tee /etc/rancher/k3s/config.yaml

# Install K3s (reads config.yaml automatically)
curl -sfL https://get.k3s.io | sh -
```

> **Why `tls-san`?** K3s generates a TLS cert for the API server. By default it only includes
> the LAN IP (172.16.1.10) and localhost. Adding the Tailscale IP (100.64.0.4) allows
> `kubectl` from workstation via VPN without `insecure-skip-tls-verify`.
> Must be set BEFORE first start (or requires restart to regenerate certs).

Verify installation:

```bash
sudo kubectl get nodes
# NAME         STATUS   ROLES                  AGE   VERSION
# k3s-server   Ready    control-plane,master   Xs    v1.34.4+k3s1
```

Retrieve the node token (needed for agents):

```bash
sudo cat /var/lib/rancher/k3s/server/node-token
```

Save the token — it's needed for all agent joins.

## Phase 2: Join Agent Nodes

On each agent node, run the install script with the server URL and token:

### k3s-agent-1 (Acemagic-1)

```bash
ssh k3s-agent-1
curl -sfL https://get.k3s.io | K3S_URL=https://172.16.1.10:6443 K3S_TOKEN=<token> sh -
```

### k3s-agent-2 (Acemagic-2)

```bash
ssh k3s-agent-2
curl -sfL https://get.k3s.io | K3S_URL=https://172.16.1.10:6443 K3S_TOKEN=<token> sh -
```

Verify from the server:

```bash
ssh k3s-server
sudo kubectl get nodes
# NAME           STATUS   ROLES                  AGE   VERSION
# k3s-server     Ready    control-plane,master   Xm    v1.34.4+k3s1
# k3s-agent-1    Ready    <none>                 Xm    v1.34.4+k3s1
# k3s-agent-2    Ready    <none>                 Xm    v1.34.4+k3s1
```

## Phase 3: Create Namespace

```bash
ssh k3s-server
sudo kubectl create namespace kubelab
```

## Phase 4: Configure Workstation Access

### Copy kubeconfig

K3s kubeconfig is at `/etc/rancher/k3s/k3s.yaml` (root-only). Copy it to workstation:

```bash
# On k3s-server: copy to accessible location
ssh k3s-server "sudo cp /etc/rancher/k3s/k3s.yaml /tmp/k3s.yaml && sudo chmod 644 /tmp/k3s.yaml"

# On workstation: download and fix server address
scp k3s-server:/tmp/k3s.yaml ~/.kube/kubelab-config

# Clean up
ssh k3s-server "rm /tmp/k3s.yaml"
```

Edit `~/.kube/kubelab-config`:

```bash
# Replace server address with Tailscale IP (VPN access from anywhere)
sed -i 's|server: https://127.0.0.1:6443|server: https://100.64.0.4:6443|' ~/.kube/kubelab-config

# Replace insecure-skip-tls-verify with the CA cert (requires tls-san configured in Phase 1)
# Get the CA cert base64:
CA_DATA=$(ssh k3s-server "sudo cat /var/lib/rancher/k3s/server/tls/server-ca.crt | base64 -w0")
# Then in kubelab-config, replace:
#   insecure-skip-tls-verify: true
# with:
#   certificate-authority-data: <CA_DATA>
```

> **Important:** Use the Tailscale IP (`100.64.0.4`), not the LAN IP (`172.16.1.10`).
> Tailscale works from anywhere (home, office, mobile). LAN only works on the local network.
> The `tls-san` in Phase 1 ensures the cert is valid for this IP.

### Configure KUBECONFIG

Add to shell profile (`~/.zshrc` or `~/.bashrc`):

```bash
export KUBECONFIG=~/.kube/kubelab-config
```

Or merge with existing configs:

```bash
export KUBECONFIG=~/.kube/config:~/.kube/kubelab-config
```

### Add Static Route (Required)

The workstation needs a route to the homelab LAN (172.16.1.0/24) through the RPi 4 gateway.
Without this, `kubectl` can't reach the K3s API server directly (SSH works via ProxyJump but kubectl needs a direct route).

**NetworkManager (persistent across reboots):**

```bash
# Find your active WiFi connection name
nmcli connection show --active

# Add static route
nmcli connection modify "EcosDeSanJacinto" +ipv4.routes "172.16.1.0/24 10.0.0.131"

# Apply without disconnecting
nmcli connection up "EcosDeSanJacinto"
```

Replace `"EcosDeSanJacinto"` with your actual WiFi connection name.

**Verify route:**

```bash
ip route | grep 172.16.1
# 172.16.1.0/24 via 10.0.0.131 dev wlp1s0 ...
```

**Verify kubectl:**

```bash
kubectl get nodes
# Should show all 3 nodes
```

### Troubleshooting

#### kubectl timeout: "dial tcp 172.16.1.10:6443: i/o timeout"

**Root cause:** Workstation has no route to 172.16.1.0/24. SSH works via ProxyJump through RPi 4, but kubectl connects directly — it doesn't use SSH config.

**Fix:** Add static route via NetworkManager (see "Add Static Route" above).

**Diagnosis checklist:**

1. **Check route exists:** `ip route | grep 172.16.1`
2. **Test connectivity:** `ping 172.16.1.10`
3. **Test API port:** `curl -k https://172.16.1.10:6443/version`
4. **Check RPi 4 forwarding:** `ssh kubelab-rpi4 "sysctl net.ipv4.ip_forward"` (should be `1`)
5. **Check kubeconfig server URL:** `grep server ~/.kube/kubelab-config` (should be `https://172.16.1.10:6443`)

**Key insight:** If SSH to k3s-server works but kubectl doesn't, the issue is the missing static route. SSH uses ProxyJump (hops through RPi 4), kubectl needs a direct IP route.

#### kubeconfig copy: "a terminal is required to read the password"

**Root cause:** `sudo cat` over SSH pipe requires a TTY for the password prompt. Piping output (`ssh ... "sudo cat" > file`) strips the TTY.

**Fix:** Two-step copy instead of pipe:

```bash
# Step 1: Copy to /tmp on the server
ssh k3s-server "sudo cp /etc/rancher/k3s/k3s.yaml /tmp/k3s.yaml && sudo chmod 644 /tmp/k3s.yaml"

# Step 2: SCP to workstation
scp k3s-server:/tmp/k3s.yaml ~/.kube/kubelab-config

# Step 3: Clean up
ssh k3s-server "rm /tmp/k3s.yaml"
```

#### Route lost after WiFi reconnect

If the route disappears after WiFi disconnect/reconnect, verify it's persistent:

```bash
nmcli connection show "EcosDeSanJacinto" | grep ipv4.routes
# Should show: 172.16.1.0/24 10.0.0.131
```

If missing, re-add with `nmcli connection modify` (see Phase 4).

#### Node names show "kubelab-k3s-*" instead of "k3s-*"

K3s uses the system hostname. The Proxmox VMs are named `kubelab-k3s-server`, `kubelab-k3s-agent-1`, `kubelab-k3s-agent-2`. This is correct — the `k3s-server` in SSH config is just an alias.

## Phase 5: Verify Full Cluster

```bash
# All nodes ready
kubectl get nodes -o wide

# Namespace exists
kubectl get ns kubelab

# System pods healthy
kubectl get pods -A

# Cluster info
kubectl cluster-info
```

## Maintenance

### Restart K3s

```bash
# Server
ssh k3s-server "sudo systemctl restart k3s"

# Agents
ssh k3s-agent-1 "sudo systemctl restart k3s-agent"
ssh k3s-agent-2 "sudo systemctl restart k3s-agent"
```

### Uninstall K3s

```bash
# Server (destroys cluster!)
ssh k3s-server "sudo /usr/local/bin/k3s-uninstall.sh"

# Agents
ssh k3s-agent-1 "sudo /usr/local/bin/k3s-agent-uninstall.sh"
ssh k3s-agent-2 "sudo /usr/local/bin/k3s-agent-uninstall.sh"
```

### Upgrade K3s

```bash
# Server first, then agents
ssh k3s-server "curl -sfL https://get.k3s.io | sh -"
ssh k3s-agent-1 "curl -sfL https://get.k3s.io | K3S_URL=https://172.16.1.10:6443 K3S_TOKEN=<token> sh -"
ssh k3s-agent-2 "curl -sfL https://get.k3s.io | K3S_URL=https://172.16.1.10:6443 K3S_TOKEN=<token> sh -"
```

## Phase 6: Traefik TLS (Let's Encrypt DNS-01)

K3s ships Traefik as the default ingress controller. Configure ACME cert provisioning via Cloudflare DNS-01.

### Prerequisites

- Cloudflare API token with `Zone:DNS:Edit` for `kubelab.live`
- Secret created on cluster:
  ```bash
  kubectl --kubeconfig ~/.kube/kubelab-config create secret generic cloudflare-api-token \
    --from-literal=api-token=<TOKEN> -n kube-system
  ```

### Apply HelmChartConfig

K3s uses `HelmChartConfig` CRD to override Traefik Helm values:

```bash
kubectl --kubeconfig ~/.kube/kubelab-config apply -f infra/k8s/base/traefik-config.yaml
```

File `infra/k8s/base/traefik-config.yaml`:
```yaml
apiVersion: helm.cattle.io/v1
kind: HelmChartConfig
metadata:
  name: traefik
  namespace: kube-system
spec:
  valuesContent: |-
    additionalArguments:
      - "--certificatesresolvers.letsencrypt.acme.dnschallenge=true"
      - "--certificatesresolvers.letsencrypt.acme.dnschallenge.provider=cloudflare"
      - "--certificatesresolvers.letsencrypt.acme.email=mlorentedev@gmail.com"
      - "--certificatesresolvers.letsencrypt.acme.storage=/data/acme.json"
      - "--certificatesresolvers.letsencrypt.acme.dnschallenge.resolvers=1.1.1.1:53,8.8.8.8:53"
    env:
      - name: CF_DNS_API_TOKEN
        valueFrom:
          secretKeyRef:
            name: cloudflare-api-token
            key: api-token
```

### Verify

```bash
# Check Traefik restarted with ACME args
kubectl --kubeconfig ~/.kube/kubelab-config logs -n kube-system -l app.kubernetes.io/name=traefik | grep -i acme

# After deploying an IngressRoute, check cert issuance (1-2 min)
curl -vk https://web.staging.kubelab.live 2>&1 | grep -E "subject|issuer"
```

> **Note:** The Cloudflare secret MUST be in `kube-system` (where Traefik runs), not in `kubelab`.

## Reference

| Item | Value |
|------|-------|
| K3s version | v1.34.4+k3s1 |
| Server IP | 172.16.1.10 |
| Agent-1 IP | 172.16.1.11 |
| Agent-2 IP | 172.16.1.12 |
| Gateway | 10.0.0.131 (RPi 4) |
| Kubeconfig | `~/.kube/kubelab-config` |
| Namespace | `kubelab` |
| API endpoint | `https://172.16.1.10:6443` |
| Install date | 2026-02-20 |

## Related

- [hardware-setup](hardware-setup.md) — VM provisioning on Proxmox
- [proxmox-setup](proxmox-setup.md) — Proxmox VE configuration
- [headscale-setup](headscale-setup.md) — VPN mesh (replaces static route for remote access)
- [dns-homelab](dns-homelab.md) — CoreDNS for staging domain resolution
