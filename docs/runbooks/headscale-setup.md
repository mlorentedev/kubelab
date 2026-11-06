---
id: "kubelab-runbook-headscale-setup"
type: runbook
status: active
tags: [runbook, kubelab]
created: "2026-02-18"
owner: manu
---

# Headscale Setup — B1 VPN Mesh

Set up Headscale (self-hosted Tailscale control plane) on the VPS and connect all homelab nodes via Tailscale clients. The result is a WireGuard mesh VPN with self-owned coordination.

See [adr-010-headscale-over-tailscale-cloud](../adr/adr-010-headscale-over-tailscale-cloud.md) for the decision rationale.

## Prerequisites

- VPS deployed and accessible via SSH (`ssh vps-pub`: the public-IP alias of Phase 5, user `networking.ssh_users.cloud` in `common.yaml`, `deployer`). Headscale is the bootstrap, so reach it by the public address, never through the mesh it serves
- Docker installed on the VPS (the `headscale` role creates the `kubelab` network and starts the stack)
- B0 hardware provisioning complete (all homelab nodes reachable via LAN)
- Domain `vpn.kubelab.live` → VPS IP (Cloudflare A record, **DNS-only / grey cloud**)
- Cloudflare API token with access to **both** zones: `mlorente.dev` + `kubelab.live`

---

## Phase 1: Deploy Headscale on VPS

The `headscale` Ansible role (`infra/ansible/roles/headscale/`, run by `infra/ansible/playbooks/deploy-vps.yml`) does all of Phase 1 except 1.7. Nothing is created, copied or started by hand on the VPS:

```bash
make deploy TARGET=vps ENV=prod              # the whole VPS play
make deploy TARGET=vps ENV=prod TAGS=headscale   # only this role
make deploy TARGET=vps ENV=prod CHECK=1      # dry run
```

### 1.1 Directory and config (rendered)

The role creates `/opt/headscale` and `/opt/headscale/config`, then renders `config/config.yaml` from `infra/ansible/roles/headscale/templates/config.yaml.j2`. The values come from `common.yaml` through `deploy-vps.yml`: the domain, the listen and STUN ports, `networking.tailscale_cidr`, split DNS from `networking.staging_zones` (6.1) and the ACL policy path (Phase 8). Headscale reads `config.yaml` only at startup, so the role restarts the stack whenever the rendered file changes. Do not edit it on the VPS: the next deploy overwrites the edit. Change the value in `common.yaml` (or the template) and deploy.

### 1.2 docker-compose.yml on the VPS (rendered)

The `headscale` role renders `/opt/headscale/docker-compose.yml` from
`infra/ansible/roles/headscale/templates/docker-compose.yml.j2` on every
`make deploy TARGET=vps ENV=prod`. That template is the source of truth: do not write the
file by hand, an edit on the VPS is overwritten by the next deploy. The values come from
`common.yaml`, and the VPS network is `kubelab` (ADR-020 Phase 2b; the old `proxy` network
is gone). `tests/test_headscale_runbook_compose.py` fails when this snippet stops matching
what the template renders.

```yaml
services:
  headscale:
    container_name: headscale
    image: <apps.services.core.headscale.image>
    restart: unless-stopped
    command: serve
    ports:
      - "<networking.vps.public_ip>:8080:8080"
      - "3478:3478/udp"
    volumes:
      - ./config:/etc/headscale:ro
      - headscale_data:/var/lib/headscale
    dns:
      - 1.1.1.1
      - 8.8.8.8
    networks:
      - kubelab
    healthcheck:
      test: ["CMD", "headscale", "version"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 10s

volumes:
  headscale_data:

networks:
  kubelab:
    external: true
```

Port 8080 is published on the VPS public IP only: that is the address the K3s Traefik
EndpointSlice points at (1.4), so Headscale's control port is not reachable on any other
interface. STUN (`3478/udp`) is published on all addresses.

### 1.3 TLS certificate (certbot superseded)

> **Superseded.** This section used to obtain a certificate with certbot (Cloudflare
> DNS-01) because Headscale terminated TLS itself behind a Traefik TCP passthrough
> (2026-02-26, [lesson-075](../lessons/networking-dns/lesson-075-2026-02-26-traefik-cannot-proxy-headscale-cus.md)).
> Since the K3s cutover ([lesson-173](../lessons/kubernetes/lesson-173-k3s-ingressroute-needed-for-vpn-kubelab-live-.md))
> **K3s Traefik terminates TLS** for `vpn.kubelab.live` and Headscale listens on plain
> HTTP (`listen_addr: 0.0.0.0:8080`; `config.yaml.j2` has no `tls_*` keys). Nothing mounts
> `/etc/letsencrypt`. The `headscale` role purges certbot, nginx and `/etc/letsencrypt`
> from the VPS (OPS-047, #2701; `make deploy TARGET=vps ENV=prod` applies it): do not
> reinstall them, and do not follow the old steps.

There is nothing to obtain by hand. The certificate comes from K3s Traefik's
`letsencrypt` resolver (ACME DNS-01, stored on Traefik's persistent volume), named by
`tls.certResolver` on the `headscale` IngressRoute in
`infra/k8s/overlays/prod/headscale.yaml`. To see which certificate clients get:

```bash
openssl s_client -connect vpn.kubelab.live:443 -servername vpn.kubelab.live </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -enddate
# → subject=CN=vpn.kubelab.live, issuer=Let's Encrypt (Traefik's certificate, auto-renewed)
```

### 1.4 Traefik route (TCP passthrough superseded)

> **Superseded.** The first working route (2026-02-26) was a Traefik TCP passthrough
> (`HostSNI(...)` + `tls.passthrough: true`) with Headscale terminating TLS, because,
> per lesson-075, Traefik v3.0 did not carry `Upgrade: tailscale-control-protocol`
> ([traefik#12609](https://github.com/traefik/traefik/issues/12609), still open). The
> dynamic config file it created, and the reasoning, are in
> lesson-075. It no longer applies.

Current route (prod): `infra/k8s/overlays/prod/headscale.yaml` defines an IngressRoute
`headscale` (rule ``Host(`vpn.kubelab.live`)``, entry point `websecure`,
`tls.certResolver: letsencrypt`) that forwards plain HTTP to Service `headscale:8080`,
whose EndpointSlice points at the VPS public IP (`networking.vps.public_ip`). Headscale
publishes 8080 on that address only (`docker-compose.yml.j2`). The route references the TLSOption
`headscale-http11` (`alpnProtocols: [http/1.1]`, TLS 1.2 minimum), so clients negotiate
HTTP/1.1, which is where the Noise `Upgrade` request exists. Details and the history:
[error-headscale-noise-http2](../troubleshooting/error-headscale-noise-http2.md).

### 1.5 Deploy

`make deploy TARGET=vps ENV=prod` (see the top of Phase 1). In order, the role:

1. creates the `kubelab` Docker network if it is missing;
2. renders `docker-compose.yml` (1.2) and `config.yaml` (1.1);
3. pulls the image and runs `docker compose up -d`;
4. restarts the stack if the compose file or `config.yaml` changed;
5. waits until the container reports `healthy` (up to 12 tries, 5 s apart);
6. renders the ACL policy and hot-reloads it, then probes the mesh and reverts the policy if the probe fails (Phase 8);
7. installs the audit SSH identities declared in `common.yaml`, and purges the retired certbot and nginx packages (OPS-047).

A second run with nothing changed reports `changed=0` for the Headscale tasks.

### 1.6 Verify

Headscale v0.28 answers `/health` with its own handler (measured 2026-11-06, #3010; this section said the opposite until then). The errors service also has a `/health`, but it answers plain `OK`, so the media type tells the two apart:

```bash
curl -s -w ' %{content_type}\n' https://vpn.kubelab.live/health
# → {"status":"pass"} application/health+json; charset=utf-8
```

`make test-e2e ENV=prod` asserts the `status` key on every run. The container's health state is a weaker check: its healthcheck runs `headscale version` (1.2), which passes without a running server (#3164 moves it to `headscale health`):

```bash
# On VPS (ssh vps-pub)
docker inspect --format '{{.State.Health.Status}}' headscale
# → healthy
docker logs headscale --tail 20
```

From workstation:
```bash
# Verify the certificate is Traefik's (Let's Encrypt, auto-renewed) and that
# HTTP/1.1 is negotiated even when the client offers HTTP/2 (TLSOption headscale-http11):
openssl s_client -connect vpn.kubelab.live:443 -servername vpn.kubelab.live \
  -alpn h2,http/1.1 </dev/null 2>&1 | grep -E "subject=|issuer=|ALPN protocol"
# → subject=CN=vpn.kubelab.live
# → issuer=C=US, O=Let's Encrypt, CN=<intermediate>
# → ALPN protocol: http/1.1

# Verify Noise protocol endpoint is reachable:
curl --http1.1 -s -X POST https://vpn.kubelab.live/ts2021 \
  -H "Upgrade: tailscale-control-protocol" -H "Connection: Upgrade"
# → Should NOT return "missing Tailscale handshake header"
# → (the Upgrade header reaches Headscale through K3s Traefik)
```

### 1.7 Create user and pre-auth key

```bash
# Headscale v0.28 CLI syntax (uses positional args and numeric user IDs)
docker exec headscale headscale users create kubelab
docker exec headscale headscale users list
# Note the ID (e.g., 2)

# Generate reusable pre-auth key (24h expiry, for registering multiple nodes)
docker exec headscale headscale preauthkeys create --user 2 --reusable --expiration 24h
```

> **v0.28 gotchas:**
> - `users create` takes NAME as positional arg (not `--name`)
> - `preauthkeys create --user` takes numeric ID (not username)

---

## Phase 2: Connect All Nodes

### 2.1 Install Tailscale and register

Same command on every node:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --login-server=https://vpn.kubelab.live --authkey=<KEY>
```

Nodes to register: the entries of `networking.vps`, `networking.nodes.*` and `networking.operator_workstations` in `common.yaml`, which is the SSOT for names and addresses (Phase 4 mirrors it):

1. Operator workstation (`mac`, `networking.operator_workstations`)
2. VPS (`kubelab-vps`)
3. Beelink (`beelink`)
4. ace1 (`ace1`, K3s staging)
5. ace2 (`ace2`)
6. RPi 4 (`rpi4`)
7. RPi 3 (`rpi3`)
8. gcp1 (`gcp1`, Argo CD hub; `common.yaml` declares no address for it, see Phase 4)
9. Jetson Nano (`jetson`; `retired: true` in `common.yaml`, register it again only when it returns to the lab)

The name Headscale shows for a node is its given name, which can differ from the `hostname` above. `headscale nodes list` is the live answer.

### 2.2 Verify mesh

```bash
tailscale status
```

Every node of 2.1 that is powered on must appear, at the `tailscale_ip` Phase 4 lists for it. On-demand nodes (ADR-028) are offline while the homelab is off.

```bash
tailscale ping 100.64.0.2    # VPS (networking.vps.tailscale_ip)
tailscale ping 100.64.0.10   # RPi 4 (networking.nodes.rpi4.tailscale_ip)
tailscale ping 100.64.0.11   # ace1 (networking.nodes.ace1.tailscale_ip)
# → pong from <node> (<address>) via <endpoint>
```

---

## Phase 3: Configure RPi 4 as Subnet Router

> **Completed 2026-02-21** (TS-003/TS-004).

RPi 4 advertises the KubeLab LAN subnet (`172.16.1.0/24`) so external Headscale nodes can reach devices behind the switch (e.g., Proxmox hosts that don't have Tailscale).

### 3.1 Advertise subnet route (on RPi 4)

```bash
sysctl net.ipv4.ip_forward  # Should be 1 (already set for NAT gateway)

sudo tailscale up \
  --login-server=https://vpn.kubelab.live \
  --advertise-routes=172.16.1.0/24 \
  --accept-dns=false
```

> **`--accept-dns=false` is critical on RPi 4.** Without it, Tailscale overwrites
> `/etc/resolv.conf` with `100.100.100.100` (Tailscale magic DNS). Since RPi 4 runs
> Pi-hole (systemd-resolved disabled), this creates a chicken-and-egg: Tailscale can't
> connect because it can't resolve `vpn.kubelab.live`, and its own DNS won't work until
> connected. The `--accept-dns=false` flag prevents Tailscale from touching DNS.

### 3.2 Fix DNS persistence (on RPi 4)

RPi 4 is the only node without `systemd-resolved` (disabled for Pi-hole). This makes it
vulnerable to DNS failures during boot — `tailscaled` starts before Docker (Pi-hole) is ready.

**Two fixes applied** (both required for reboot resilience):

```bash
# 1. Dual nameserver: Pi-hole primary, public DNS fallback for boot ordering
sudo chattr -i /etc/resolv.conf
printf "nameserver 127.0.0.1\nnameserver 8.8.8.8\n" | sudo tee /etc/resolv.conf
sudo chattr +i /etc/resolv.conf

# 2. Boot ordering: tailscaled waits for Docker (Pi-hole) to start
sudo mkdir -p /etc/systemd/system/tailscaled.service.d
printf "[Unit]\nAfter=docker.service\nWants=docker.service\n" | \
  sudo tee /etc/systemd/system/tailscaled.service.d/after-docker.conf
sudo systemctl daemon-reload
```

To undo the resolv.conf protection if you ever need to edit:
```bash
sudo chattr -i /etc/resolv.conf
```

> **Why only RPi 4?** All other nodes use `systemd-resolved`, which provides its own DNS
> resolution independent of Tailscale. RPi 4 is unique: `systemd-resolved` is disabled
> (Pi-hole replaces it), Docker manages Pi-hole, and `tailscaled` can start before Docker.
> No other node has this boot ordering dependency.
>
> **Applied**: 2026-02-21. Verified: dual nameserver + systemd drop-in in place.

### 3.3 Approve route in Headscale (on VPS)

```bash
# List routes to find the node ID
sudo docker exec headscale headscale nodes list-routes

# Approve routes for RPi 4 (node ID 5)
sudo docker exec headscale headscale nodes approve-routes -i 5 --routes 172.16.1.0/24

# Verify: Approved + Serving columns should show the subnet
sudo docker exec headscale headscale nodes list-routes -i 5
# ID | Hostname     | Approved      | Available     | Serving (Primary)
# 5  | kubelab-rpi4 | 172.16.1.0/24 | 172.16.1.0/24 | 172.16.1.0/24
```

> **v0.28 CLI gotcha**: There is no top-level `routes` command. Routes are managed
> under `nodes`: `nodes list-routes`, `nodes approve-routes`. The `approve-routes`
> flag `--routes` is a SET operation (replaces all approved routes, not additive).

### 3.4 Verify subnet routing

From any Tailscale node (e.g., workstation), reach a device on 172.16.1.0/24 that does NOT have Tailscale:

```bash
# Proxmox ace1 web UI (no Tailscale on host)
curl -k https://172.16.1.2:8006

# Proxmox ace2 web UI
curl -k https://172.16.1.5:8006

# Pi-hole admin on RPi 4 (via LAN IP, not Tailscale IP)
curl -s http://172.16.1.1/admin/ | head -5
```

---

## Phase 4: Tailscale IPs

A reading of `networking.*` in `common.yaml`, which is the SSOT: when a value there changes, this table is the copy that is wrong.

| Device | `hostname` | Tailscale IP | LAN / public IP |
|--------|------------|--------------|-----------------|
| Operator workstation | mac | 100.64.0.15 | — |
| VPS | kubelab-vps | 100.64.0.2 | 162.55.57.175 (public) |
| Beelink | beelink | 100.64.0.3 | 172.16.1.3 |
| ace1 | ace1 | 100.64.0.11 | 172.16.1.2 |
| ace2 | ace2 | 100.64.0.5 | 172.16.1.5 |
| RPi 4 | rpi4 | 100.64.0.10 | 172.16.1.1 (LAN), 10.0.0.1 (lab Wi-Fi) |
| RPi 3 | rpi3 | 100.64.0.6 | 10.0.0.157 (lab Wi-Fi) |
| gcp1 | gcp1 | none declared: MagicDNS `gcp1.kubelab.internal` | — |
| Jetson Nano (retired) | jetson | 100.64.0.8 | 172.16.1.4 |

gcp1 has no address in `common.yaml` on purpose: it rotates on every re-registration, so use its MagicDNS name.

---

## Phase 5: SSH Config Update

Update `~/.ssh/config` with dual-path access: VPN primary, LAN fallback.

**Pattern**: `ssh <host>` uses VPN (works from anywhere). `ssh <host>-lan` uses LAN (fallback when VPN down, local network only). `ssh vps-pub` uses public IP directly (VPS has no LAN).

> **This block is hand-copied, and parts of it are stale — see #1289.** It is the
> only consumer of `networking.*` that is not generated, so it drifts silently
> while every other consumer (Ansible inventory, Headscale policy, CoreDNS zones,
> EndpointSlices) stays correct. Known-stale entries below: `k3s-server`,
> `k3s-agent-1` and `k3s-agent-2` are Proxmox VMs removed by ADR-023 Phase 1, and
> `100.64.0.7` is aws1 today; `rpi4-lan` predates the move to `172.16.1.0/24`.
> They are left rather than hand-corrected because #1289 replaces this section
> with a generator, and a second hand-written copy would age the same way.
>
> **`networking.*` in `common.yaml` is the SSOT.** Prefer MagicDNS names over
> Tailscale IPs when adding a host here: a Spot node's address rotates on every
> preemption (aws1 did, gcp1 has twice), so a literal is a lie waiting for the
> next one.
>
> **The existing entries below contradict that advice, and are left alone on
> purpose** (raised in review of #1299). Most predate MagicDNS and address stable
> homelab nodes by Tailscale IP, where a literal is merely redundant rather than
> wrong — those addresses do not rotate. The rule bites only for nodes whose
> *machine* is replaced, which today means the cloud hubs, and those two are the
> ones written by name. Read it as "MagicDNS for anything recreatable", not as a
> pending rewrite of the block; the rewrite is #1289's, done by generating it.

```sshconfig
# --- KUBELAB-SSH-START ---
# Primary: Headscale VPN (works from anywhere)
# Fallback: LAN aliases (*-lan) for when VPN is down and on local network

# --- VPN access (Headscale mesh) ---
Host rpi4
  Hostname 100.64.0.10
  User manu
  IdentityFile ~/.ssh/id_ed25519

Host rpi3
  Hostname 100.64.0.6
  User manu
  IdentityFile ~/.ssh/id_ed25519

Host ace1
  Hostname 172.16.1.2
  User manu
  IdentityFile ~/.ssh/id_ed25519
  ProxyJump rpi4

Host ace2
  Hostname 172.16.1.5
  User manu
  IdentityFile ~/.ssh/id_ed25519
  ProxyJump rpi4

Host bee
  Hostname 100.64.0.3
  User manu
  IdentityFile ~/.ssh/id_ed25519

Host jet1
  Hostname 100.64.0.8
  User manu
  IdentityFile ~/.ssh/id_ed25519

Host k3s-server
  Hostname 100.64.0.4
  User manu
  IdentityFile ~/.ssh/id_ed25519

Host k3s-agent-1
  Hostname 100.64.0.7
  User manu
  IdentityFile ~/.ssh/id_ed25519

Host k3s-agent-2
  Hostname 100.64.0.9
  User manu
  IdentityFile ~/.ssh/id_ed25519

Host vps
  Hostname 100.64.0.2
  User deployer
  IdentityFile ~/.ssh/id_ed25519

# Public-IP path to the VPS (networking.vps.public_ip): Headscale runs there, so
# the way in when the mesh is down cannot go through the mesh.
Host vps-pub
  Hostname 162.55.57.175
  User deployer
  IdentityFile ~/.ssh/id_ed25519

# --- Argo CD hubs (cloud, mesh-only: no LAN and no public fallback) ---
# By MagicDNS name, never by Tailscale IP: both are Spot instances whose address
# rotates on every preemption. `clusters.hub.ssh_alias` in common.yaml selects
# which one `fetch-kubeconfig ENV=hub` reads, and the fetch is SSH regardless of
# `--direct`, so an alias missing here is a fetch that silently reroutes.
Host aws1
  Hostname aws1.kubelab.internal
  User deployer
  IdentityFile ~/.ssh/id_ed25519

Host gcp1
  Hostname gcp1.kubelab.internal
  User deployer
  IdentityFile ~/.ssh/id_ed25519

# --- LAN fallback (no VPN needed, local network only) ---
Host rpi4-lan
  Hostname 10.0.0.131
  User manu
  IdentityFile ~/.ssh/id_ed25519

# (repeat pattern for all nodes: <host>-lan with LAN IP + ProxyJump rpi4-lan)
# Full config at ~/.ssh/config on workstation
# --- KUBELAB-SSH-END ---
```

> **Do NOT commit this file** — contains local paths to private keys.
> This documentation serves as reference to recreate the config on a new workstation.

**Note**: `ace1`/`ace2` keep ProxyJump even in VPN mode — they are Proxmox hosts without
Tailscale. VPN goes to the K3s VMs running inside them, not to Proxmox directly.

---

## Phase 6: Split DNS for Staging Domain

> **Completed 2026-02-21** (TS-006 + B2 DNS-001/002/003).

Headscale routes `*.staging.kubelab.live` queries to RPi 4 (100.64.0.10), where Pi-hole forwards to CoreDNS.

Full setup documented in [dns-homelab](dns-homelab.md).

### 6.1 Headscale config (rendered)

The role renders split DNS from `networking.staging_zones` in `common.yaml`: `deploy-vps.yml` points every zone in that list at `networking.nodes.rpi4.tailscale_ip` and `config.yaml.j2` writes the result under `dns.nameservers.split`. `tests/test_headscale_runbook_compose.py` fails when this snippet stops matching what the template renders.

```yaml
dns:
  nameservers:
    split:
      staging.kubelab.live:
        - 100.64.0.10
      staging.mlorente.dev:
        - 100.64.0.10
```

`100.64.0.10` is RPi4 (Pi-hole on port 53, forwarding to CoreDNS). To add or remove a zone, edit `networking.staging_zones` and run `make deploy TARGET=vps ENV=prod`; the role restarts Headscale because `config.yaml` changed. Do not edit `/opt/headscale/config/config.yaml` on the VPS. Keep zones under `staging.`: a broad `kubelab.live` zone sends prod lookups to RPi4 (2026-03-03 entry in "Last tested").

### 6.2 Client config

Workstation and other clients need `--accept-routes` to use the subnet router:

```bash
sudo tailscale up --login-server=https://vpn.kubelab.live --accept-routes
```

Applied on: workstation ✓, RPi 3 ✓ (2026-02-21).

### 6.3 Verification

```bash
# From any Tailscale node
dig api.staging.kubelab.live +short
# → 100.64.0.11 (ace1's Tailscale IP, networking.nodes.ace1.tailscale_ip: K3s Traefik Ingress)
```

---

## Troubleshooting

### TLS cert not issued for vpn.kubelab.live

**Symptoms**: `curl` returns a certificate error (Traefik's default self-signed certificate) or `000`.

K3s Traefik issues this certificate (1.3), not a container on the VPS: there is no Traefik container and no Traefik directory on the VPS. Read the ACME error first, then match it against the table in [acme-alerting](acme-alerting.md):

```bash
kubectl --kubeconfig ~/.kube/kubelab-prod-config \
  logs -n kube-system -l app.kubernetes.io/name=traefik --tail=400 \
  | sed 's/\x1b\[[0-9;]*m//g' | grep -iE 'acme.*(err|unable|fail)'
```

**Root causes (in order of likelihood)**:
1. **Cloudflare API token missing zone access**: the DNS-01 challenge uses the token the Traefik pod reads as `CF_DNS_API_TOKEN`. It must have access to the `kubelab.live` zone (not just `mlorente.dev`); the log shows `unauthorized` or `403` from Cloudflare. Fix the token in the Cloudflare dashboard (add the zone), or rotate it in SOPS and run `make apply-secrets ENV=prod`, then restart Traefik.

2. **ACME storage not persistent**: the resolver stores certificates in `/data/acme.json`, which must be on the persistent volume (`persistence.enabled: true` in `traefik-helmconfig.yaml.j2`). On an `emptyDir`, every pod restart discards them and requests new ones until Let's Encrypt's rate limit (5 certificates per domain set per 168h) refuses. The HelmChartConfig is rendered by the `k3s_server` role: `make deploy TARGET=k3s ENV=prod` re-applies it. Never create one by hand.

3. **Cloudflare proxy enabled**: `vpn.kubelab.live` MUST be DNS-only (grey cloud). WireGuard/DERP cannot traverse Cloudflare proxy.

### Router uses a non-existent certificate resolver

**Symptom**: a router shows `non-existent certificate resolver` in Traefik's log.

**Root cause**: the route names `certResolver: letsencrypt` but the Traefik that is running has no such resolver. The resolver is defined by the HelmChartConfig the `k3s_server` role renders when ACME is enabled (`--certificatesresolvers.letsencrypt.*`), so the resolver is missing when that config was not applied or the ACME block rendered disabled.

**Fix**: `make deploy TARGET=k3s ENV=prod` (the `deploy-k3s.yml` play sets `k3s_traefik_acme_enabled: true`), then check the Traefik pod's arguments for `--certificatesresolvers.letsencrypt.acme.storage=/data/acme.json`. The name is `letsencrypt`, not `cloudflare`: Cloudflare is the DNS challenge provider.

### jet1 (Jetson Nano) — tailscale logged out after reboot {#incident-jet1-dns-boot}

**Incident**: 2026-02-22 — After integrating jet1 into the kubelab mesh and rebooting,
`tailscale status` showed `NoState` / "You are logged out". Could not SSH via `ssh jet1`
(100.64.0.8 unreachable). `ssh jet1-lan` worked (LAN route via ProxyJump).

**Root cause**: jet1 uses `systemd-resolved` (Ubuntu 18.04 / JetPack 4.6). Tailscale's
split DNS config (pushed via headscale) sets `100.100.100.100` as upstream in
systemd-resolved. When tailscale disconnects, systemd-resolved has no fallback upstream
→ cannot resolve `vpn.kubelab.live` → cannot reconnect. Circular dependency.

**Different from RPi 4**: RPi 4 has Pi-hole/Docker boot ordering. jet1 has
systemd-resolved active and no Pi-hole — the fix is a `FallbackDNS` directive, not
`chattr` or boot ordering.

**Fix** (when it happens — connect via jet1-lan first):

```bash
ssh jet1-lan

# 1. Add FallbackDNS to systemd-resolved (persists across reboots)
sudo mkdir -p /etc/systemd/resolved.conf.d/
sudo tee /etc/systemd/resolved.conf.d/fallback-dns.conf << 'EOF'
[Resolve]
FallbackDNS=1.1.1.1 8.8.8.8
EOF

sudo systemctl restart systemd-resolved

# 2. Re-login to headscale
sudo tailscale up --login-server https://vpn.kubelab.live

# 3. Verify
tailscale status
# → should show kubelab-jet1 at 100.64.0.8
```

**Prevention**: The `FallbackDNS` config in `/etc/systemd/resolved.conf.d/fallback-dns.conf`
is now in place on jet1. systemd-resolved will use 1.1.1.1 when its primary upstream
(tailscale DNS) is unavailable → tailscale can always reconnect on boot.

**Note on `--accept-routes`**: jet1 does not run `--accept-routes`. It can reach all
headscale peers directly (100.64.0.x). The warning "some peers advertising routes" refers
to RPi4's 172.16.1.0/24 subnet route — not needed on jet1 for current workloads.

### Node shows as offline

```bash
sudo systemctl status tailscaled
sudo journalctl -u tailscaled -f
```

### Headscale v0.28 CLI reference

```bash
# Users
docker exec headscale headscale users create USERNAME
docker exec headscale headscale users list

# Pre-auth keys (use numeric user ID)
docker exec headscale headscale preauthkeys create --user <ID> --reusable --expiration 24h

# Nodes
docker exec headscale headscale nodes list

# Routes (under "nodes", NOT top-level)
docker exec headscale headscale nodes list-routes              # All routes
docker exec headscale headscale nodes list-routes -i <NODE_ID> # Routes for one node
docker exec headscale headscale nodes approve-routes -i <NODE_ID> --routes <CIDR1>,<CIDR2>
# NOTE: --routes is a SET operation (replaces all approved routes for that node)
```

### RPi 4 DNS chicken-and-egg after reboot

**Symptom**: `tailscaled` running but can't connect. Logs show `trying bootstrapDNS` and `failed to resolve vpn.kubelab.live`. VPN mesh is down, `ssh rpi4` fails (uses VPN IP). `ssh rpi4-lan` works (uses home network WiFi IP).

**Root cause (two variants)**:

1. **Tailscale overwrites resolv.conf** with `100.100.100.100` (MagicDNS). Without `--accept-dns=false`, this creates a circular dependency: Tailscale needs DNS to connect, but DNS only works through Tailscale.

2. **Boot ordering** (even with `--accept-dns=false`): `tailscaled.service` starts before Docker → Pi-hole isn't ready → `nameserver 127.0.0.1` fails → Tailscale enters broken retry loop. Even after Pi-hole comes up, Tailscale may remain stuck.

**Fix** (when it happens):
```bash
# Connect via LAN fallback
ssh rpi4-lan

# Unlock and add public DNS fallback
sudo chattr -i /etc/resolv.conf
printf "nameserver 8.8.8.8\nnameserver 127.0.0.1\n" | sudo tee /etc/resolv.conf

# Reconnect Tailscale (must include ALL non-default flags)
sudo tailscale up --login-server=https://vpn.kubelab.live --accept-dns=false --advertise-routes=172.16.1.0/24

# Restore Pi-hole as primary with public fallback, then lock
printf "nameserver 127.0.0.1\nnameserver 8.8.8.8\n" | sudo tee /etc/resolv.conf
sudo chattr +i /etc/resolv.conf
```

**Prevention**:
- Always use `--accept-dns=false` on RPi 4 (the only node with Pi-hole / no systemd-resolved)
- Use dual nameservers: `127.0.0.1` (Pi-hole) + `8.8.8.8` (fallback for boot ordering)
- Lock with `chattr +i` to prevent Tailscale/dhclient overwrites
- Tailscale locks resolv.conf with `chattr +i` too — you must `chattr -i` before editing

> **Incident 2026-02-21**: Occurred after RPi 4 reboot. `--accept-dns=false` was set, but resolv.conf had only `nameserver 127.0.0.1` without fallback. Pi-hole Docker started after tailscaled → DNS failed at boot → VPN mesh down. Also affected workstation (resolv.conf overwritten to `100.100.100.100` because workstation uses `--accept-routes` without `--accept-dns=false`).

---

## What the prod VPS runs

The VPS is a `k3s_server` in prod, so ingress there is **K3s Traefik**, configured by the `k3s_server` role (`make deploy TARGET=k3s ENV=prod`). The Docker Compose Traefik (`traefik_vps` role) and the Docker Compose error pages (`errors` role) are skipped by `deploy-vps.yml` (`when: "'k3s_servers' not in group_names"`). So the VPS has no `traefik.yml`, no ACME file and no dynamic configs to edit or overwrite. Only Headscale stays in Docker Compose (ADR-015).

| Setting | Prod VPS |
|---------|----------|
| Docker network | `kubelab` (renamed from `proxy`, ADR-020 Phase 2b) |
| Headscale TLS | K3s Traefik terminates it (certbot was the pre-K3s setup; the `headscale` role purges it, OPS-047) |
| Headscale routing | K3s Traefik IngressRoute, plain HTTP `:8080`, HTTP/1.1 ALPN (the TCP passthrough is superseded) |
| Certificates | K3s Traefik's `letsencrypt` resolver (ACME DNS-01), stored in `/data/acme.json` on its persistent volume |
| Headscale files | Rendered under `/opt/headscale` by the `headscale` role; an edit on the VPS is overwritten by the next deploy |

---

## Last tested

Dated history, kept as written. Node names in the older entries (`k3s-server`, `kubelab-rpi4`, `jet1`) are the names of the day, and the current roster is Phase 2 and Phase 4. Nothing below is a test of the current system.

2026-02-21: All phases complete (1-6). 9 nodes registered, mesh connectivity verified.
Subnet router active (RPi 4 → 172.16.1.0/24). Split DNS operational (staging.kubelab.live → CoreDNS).
DNS fix applied on RPi4 (`--accept-dns=false` + `chattr +i`).
2026-02-21 (post-reboot incident): RPi4 VPN down after reboot — boot ordering issue.
Tailscale started before Pi-hole (Docker). Fix: dual nameserver in resolv.conf
(`127.0.0.1` + `8.8.8.8`) + systemd drop-in to order tailscaled after docker.service.
2026-02-22: RPi4 nftables NAT rule had hardcoded USB interface name (`enx<MAC>`)
that no longer existed (MAC changed). K3s nodes lost internet → image pulls failed.
Fix: wildcard `oifname "enx*"` in `/etc/nftables.conf`. See [networking-dns](../troubleshooting/networking-dns.md#rpi4-nat-broken).
2026-02-22 (jet1 incident): After kubelab mesh integration + reboot, jet1 tailscale showed
`NoState` — could not resolve `vpn.kubelab.live`. Root cause: systemd-resolved had no
FallbackDNS configured, and tailscale split DNS left it without an upstream when disconnected.
Fix: `/etc/systemd/resolved.conf.d/fallback-dns.conf` with `FallbackDNS=1.1.1.1 8.8.8.8`.
See [[#incident-jet1-dns-boot]] for full procedure.
2026-02-22: DNS resilience playbook deployed — all 7 homelab nodes now have `162.55.57.175 vpn.kubelab.live`
in `/etc/hosts` via Ansible. Tailscale reconnection no longer depends on Pi-hole/RPi4 DNS chain.
See [dns-homelab](dns-homelab.md#DNS Resilience — /etc/hosts Fallback via Ansible).
2026-02-26: Traefik routing changed from HTTP reverse proxy to TCP passthrough with SNI.
Root cause: Traefik strips `Upgrade: tailscale-control-protocol` header (only supports WebSocket).
Headscale then terminated TLS itself (certbot DNS-01 via Cloudflare). **Superseded** by the K3s cutover,
where K3s Traefik terminates TLS (see 1.3); the `headscale` role removes certbot (OPS-047).
See [error-headscale-noise-http2](../troubleshooting/error-headscale-noise-http2.md).
2026-02-27: tsnet upgraded v1.60.0 → v1.80.0. Headscale v0.28.0 requires minimum_version=v1.74;
older tsnet failed silently with EOF during Noise handshake. Native clients worked because they
were already >= v1.74. Re-test SUCCESSFUL: ts-bridge registered as 100.64.0.11 (user=work),
10 peers visible, DERP#13 connected, UPnP portmap active. 5 stacked issues resolved over 2 days.
2026-03-03: Narrowed split DNS from `kubelab.live` → `staging.kubelab.live` on VPS config.
Previous broad scope caused total DNS failure for prod domains (status.kubelab.live etc.)
when RPi4 was off — Tailscale MagicDNS sent all `*.kubelab.live` queries to RPi4 instead of
public Cloudflare DNS. Now only staging domains require RPi4; prod resolves via 1.1.1.1.
The repo IaC was updated the same day (today it is `networking.staging_zones` rendered by the `headscale` role).
2026-10-26: OPS-047 (#2701) makes the `headscale` role purge certbot and nginx and remove `/etc/letsencrypt` from
the VPS. What it retires: three expired certificates, a `certbot.service` failing every 12 hours and a refused
Cloudflare token on disk. The live certificate for `vpn.kubelab.live` is K3s Traefik's (Let's Encrypt, valid to
2026-12-19 when measured). Measured in a booted Ubuntu 24.04 container: first run `changed=2`, second `changed=0`.
To apply on prod: `make deploy TARGET=vps ENV=prod`, then `systemctl list-units --failed` on the VPS must no
longer list `certbot.service` or `certbot.timer`.

---

## Phase 7: Adding Work Devices (ts-bridge via Headscale)

> **Added 2026-02-25.** Ref: [ADR-013](../adr/adr-013-vpn-consolidation.md).

Migrate Windows mini PCs running ts-bridge from Tailscale SaaS to Headscale. These devices run ts-bridge as a **server** (accepting inbound RDP connections from admin devices).

### 7.1 Create `work` user

```bash
docker exec headscale headscale users create work
docker exec headscale headscale users list
# Note numeric ID for work user
```

### 7.2 Generate pre-auth key for work devices

```bash
# IMPORTANT: --ephemeral is REQUIRED for ts-bridge nodes.
# Without it, tsnet.Server.Ephemeral=true is ignored by Headscale — nodes will persist
# as offline entries and never auto-cleanup. The ephemeral behavior is controlled by the
# KEY, not the client setting.
docker exec headscale headscale preauthkeys create --user <WORK_USER_ID> --reusable --expiration 8760h --ephemeral
```

> **Key strategy:** For device fleets < 50, a single long-lived reusable + ephemeral key
> (8760h = 1 year) is industry standard. API-based key rotation (`/api/v1/preauthkey`) is
> only justified for contractor onboarding or compliance (SOC2/ISO 27001).

### 7.3 Update ts-bridge on each Windows PC

Requires ts-bridge v1.3.0+ (with `TS_CONTROL_URL` support and tsnet >= v1.80.0).

> **Version compatibility:** Headscale v0.28.0 requires client `minimum_version=v1.74`.
> ts-bridge must use `tailscale.com` Go module >= v1.74 (currently v1.80.0).
> Older tsnet versions (e.g., v1.60.0) fail silently during the Noise handshake — the
> error is `reading response header: EOF`, not a clear version rejection.
> See [error-headscale-noise-http2](../troubleshooting/error-headscale-noise-http2.md#5) for full diagnosis.

In `.env` on each Windows PC:

```bash
TS_CONTROL_URL=https://vpn.kubelab.live
TS_AUTHKEY=<HEADSCALE_PREAUTH_KEY>
```

Restart ts-bridge. Verify node appears in `headscale nodes list`.

### 7.4 Verify RDP connectivity

From workstation (Headscale admin):

```bash
# Get the Windows PC's Headscale IP from:
docker exec headscale headscale nodes list

# Test RDP via Headscale mesh
xfreerdp /v:<HEADSCALE_IP> /u:user /p:pass
```

---

## Phase 8: ACL Policy Management

> **Added 2026-02-25.** Ref: [ADR-013](../adr/adr-013-vpn-consolidation.md), ADR-041.

Headscale ACLs control which nodes can communicate. kubelab uses a **file-mode policy rendered from the repo**, so every change is reviewed in Git and applied by the `headscale` role.

### 8.1 Where the policy comes from

The source is the template `infra/ansible/roles/headscale/templates/policy.hujson.j2`. The role renders it to `/opt/headscale/config/policy.hujson` on the VPS, which is `/etc/headscale/policy.hujson` inside the container (`headscale_policy_path` in `deploy-vps.yml`). The host aliases (`vps`, `lan-rpi4`, one per node) are built from the Tailscale IPs and `networking.lan_cidr` in `common.yaml`, so no address is written in the template. Tenant segments (VPN-ACL-014) come from SOPS at `apps.services.core.headscale.segments`, never from this repo.

### 8.2 Identity model

| Headscale User | ID | Purpose | Devices |
|----------------|----|---------|---------|
| `manu` | 1 | Personal | Holds only a stale `localhost` |
| `kubelab` | 2 | Admin and infrastructure nodes (full mesh access) | workstation, corporate workstation (ts-bridge), phone (future), fleet nodes |
| `work` | 3 | Windows PCs (RDP targets, implicit deny outbound) | 3+ Windows mini PCs (ts-bridge server) |
| `agents` | 4 | Owns the preauth keys of tagged agent nodes (ADR-041); Headscale lists those nodes under `tagged-devices`, not under this user | Agent hosts carrying `tag:hermes` |

The IDs are the ones in `common.yaml` (`apps.services.core.headscale`); `users list` is the live answer. **Key:** the human user (manu) always authenticates as `kubelab`. The `work` user represents a device class, not a person.

The policy names no `contractors` user or group (ADR-013 designed them and was never deployed, per ADR-041). Access for another organisation is a tenant segment, with its own owner user, created by the role (Phase 9).

### 8.3 ACL rules summary

The template renders these rules; it is the source, this table is a reading of it.

| Source | Destination | Action | Notes |
|--------|-------------|--------|-------|
| `kubelab@`, `manu@`, `work@` | `kubelab@`, `manu@`, `work@`, `agents@`, `tag:hermes`, `lan-rpi4` (every port) | Accept | Rule 1: named destinations, never a wildcard, so tenant segments stay out of reach |
| `tag:hermes` | `vps:443` | Accept | Rule 2: agent egress to Gitea through the prod ingress. Nothing grants `vps:8080`, `*:6443` or peer `:22` |
| each segment's clients tag | its hosts tag, declared ports | Accept | Rule 3: one per tenant segment from SOPS; its hosts originate nothing |

Anything not accepted is denied.

### 8.4 Applying ACL changes

Edit the template (or the `common.yaml` values it reads), validate, then deploy:

```bash
make check-headscale-policy                    # render + `headscale policy check` via Docker
make deploy TARGET=vps ENV=prod                # render, SIGHUP reload, probe
```

On a changed policy the role does, in order: keep the last-applied file as `policy.hujson.prev`, render the new one, hot-reload it with `docker kill --signal=HUP headscale` (no restart, existing sessions are untouched), run `toolkit infra headscale probe` from the controller and, if the probe fails, restore the previous policy (or a segment-free one) and fail the play. Nothing is copied to the VPS by hand, and there is no `headscale policy reload` step.

### 8.5 File-mode ACLs in the Headscale config

Already on. `config.yaml.j2` renders `policy.mode: file` and `policy.path` from `headscale_policy_path`, and `docker-compose.yml.j2` mounts `./config` at `/etc/headscale` (1.2). Neither is written by hand; with `headscale_policy_path` empty Headscale would run allow-all, which prod does not.

---

## Phase 9: External Access (Tenant Segments)

> **Replaces the contractor design of ADR-013** (a `contractors` user, `group:contractors` and one ACL per contractor). The policy has none of those. The mechanism is the tenant segment of VPN-ACL-014, in `infra/ansible/roles/headscale/templates/policy.hujson.j2`; its spec is `specs/VPN-ACL-014-tenant-segments/`.

Another organisation's nodes share this Headscale without seeing the private inventory. A segment is data, never a rule written in the template.

### 9.1 What a segment is

One entry under `apps.services.core.headscale.segments` in SOPS, each under a neutral key because key names are plaintext in SOPS:

```yaml
<neutral-key>:
  owner: <headscale user>      # created by the role if Headscale lacks it
  hosts_tag: tag:<name>        # the nodes being reached
  clients_tag: tag:<name>      # the nodes doing the reaching
  ports: [<int>, ...]
```

The tenant's name stays in the values, never in this repository. The template renders exactly one grant per segment, `clients_tag` to `hosts_tag` on those ports (rule 3 in 8.3), and both tags are owned by `owner@`. The segment's hosts originate nothing, nothing reaches its clients, and rule 1 names its destinations so no private user reaches a segment tag.

### 9.2 Declare or change a segment

1. Edit the segment in `prod.enc.yaml` (the entry is `apps.services.core.headscale.segments` in `SECRET_CATALOG`, `toolkit/features/secrets_manager.py`), e.g. `toolkit secrets set apps.services.core.headscale.segments.<neutral-key> --env prod --json '{...}'`.
2. `make check-headscale-policy` validates the template on the pinned image, segment-free and with a synthetic segment. It never reads the segment in SOPS, so a malformed real one is caught by the role's refusals below, at deploy.
3. `make deploy TARGET=vps ENV=prod`, which behaves as in 8.4.

Before it renders, the role refuses a segment that is malformed, owned by a private identity (`kubelab`, `manu`, `work`), reuses a private tag or shares a tag with another segment, and it stops if a node Headscale holds would be reached by neither rule 1 nor a segment. While segments are declared, a failed probe restores only a policy this template rendered, never one with a wildcard grant.

### 9.3 Not covered here

How a tenant node is issued its key and tag, and what the tenant runs on its side, are not documented in this repository: there is no runbook for onboarding a tenant node, so do not infer one from the contractor steps this phase used to carry. For the tagged-key mechanics Headscale requires, see [onboard-vpn-fleet-agent](onboard-vpn-fleet-agent.md) (agents, not tenants).

### 9.4 Revoke access

```bash
# Remove a node
docker exec headscale headscale nodes delete -i <NODE_ID>
```

---

## Phase 10: Control-Plane Bootstrap over SSH

> **Added 2026-11-02.** Ref: VPN-ACL-015 (#2862), `specs/VPN-ACL-015-ssh-bootstrap-path/`.

Some networks sinkhole or TLS-inspect `vpn.kubelab.live` (measured on the office network: Palo Alto DNS Security answers `sinkhole.paloaltonetworks.com` even when the client uses a public resolver). Clients there reach Headscale with `ts-bridge connect --bootstrap-ssh hs-bootstrap@<networking.vps.public_ip>`: an `ssh -N -D` SOCKS forward through the VPS to the control plane.

### 10.1 What is declared

| Piece | Where | Owner |
|---|---|---|
| Account name, port, `narrow_ssh_user` | `networking.vps.ssh_bootstrap` in `common.yaml` | both roles read it |
| `Match User hs-bootstrap`: `AllowTcpForwarding local`, `PermitOpen <headscale domain>:<port>`, no TTY, agent, X11, tunnel or stream-local forwarding, `ForceCommand /usr/sbin/nologin` | `ssh_hardening` template, handed to the VPS by `provision.yml` | `toolkit infra ansible run -p provision -e prod -l kubelab-vps -t ssh --require-fresh` (base `provision.yml`; `make provision NODE=vps` is K3s and never touches sshd) |
| The account (`/usr/sbin/nologin`, no password) and its root-owned `authorized_keys`, one `restrict,port-forwarding,permitopen="<same destination>"` line per key | `headscale` role (`tasks/bootstrap_identity.yml`) | `make deploy TARGET=vps ENV=prod` |
| The public keys, one per machine under a neutral key | `apps.services.core.headscale.bootstrap_ssh_keys.<client-N>` in `prod.enc.yaml` | operator |

Setting `narrow_ssh_user: true` gives the VPS's SSH user (`networking.ssh_users.cloud`) a block with the same single destination, for clients that still connect as that user while they move. It is unset since 2026-11-02, when the last client moved, so that user forwards nothing, like every other account.

### 10.2 Enrol a machine

1. On the machine, generate a key used for nothing else: `ssh-keygen -t ed25519 -f ~/.ssh/hs-bootstrap -C "hs-bootstrap <machine>"`. Never copy or escrow the private half: one key per machine is what makes revocation per machine.
2. Store the public line: `toolkit secrets set apps.services.core.headscale.bootstrap_ssh_keys.client-<N> --env prod --stdin`. The deploy refuses a line carrying options or more than one key.
3. `make deploy TARGET=vps ENV=prod`.
4. Point the machine's OpenSSH at that key, since ts-bridge runs plain `ssh` and OpenSSH does not try a non-default filename on its own. On the operator's machines this entry belongs in the dotfiles generator of `~/.ssh/config`; elsewhere add it by hand:

   ```text
   Host hs-bootstrap
       HostName <networking.vps.public_ip>
       User hs-bootstrap
       IdentityFile ~/.ssh/hs-bootstrap
       IdentitiesOnly yes
   ```

5. From the machine: `ts-bridge connect --bootstrap-ssh hs-bootstrap` reaches `READY`. `ssh hs-bootstrap` gets no shell, and a forward to any other destination is refused (`administratively prohibited`).

### 10.3 Revoke a machine

Remove its entry (`toolkit secrets` or `sops`) and `make deploy TARGET=vps ENV=prod`. The role writes the whole `authorized_keys` from SOPS, so the line is gone after that deploy; an empty mapping revokes every machine. A refused attempt shows in the VPS's `auth.log`.

The deploy stops new logins only: sshd does not re-check a session that already authenticated, so a running `ssh -N -D` tunnel keeps forwarding. End the account's sessions on the VPS, then confirm none is left:

```bash
sudo pkill -u hs-bootstrap sshd        # drops every bootstrap tunnel; machines still enrolled reconnect
pgrep -u hs-bootstrap sshd || echo none
```

Then prove the revoked machine is refused on a new connection (`Permission denied (publickey)`).
