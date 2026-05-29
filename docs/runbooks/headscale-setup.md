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

- VPS deployed and accessible via SSH (`ssh deployer@kubelab-vps`)
- Docker Compose running on VPS
- B0 hardware provisioning complete (all homelab nodes reachable via LAN)
- Domain `vpn.kubelab.live` → VPS IP (Cloudflare A record, **DNS-only / grey cloud**)
- Cloudflare API token with access to **both** zones: `mlorente.dev` + `kubelab.live`

---

## Phase 1: Deploy Headscale on VPS

### 1.1 Create directory and config

```bash
ssh deployer@kubelab-vps "sudo mkdir -p /opt/headscale/config && sudo chown -R deployer:deployer /opt/headscale"
```

Copy config from repo:

```bash
scp infra/stacks/services/core/headscale/config/config.yaml deployer@kubelab-vps:/opt/headscale/config/
```

### 1.2 Create docker-compose.yml on VPS

> **IMPORTANT**: VPS uses Docker network `proxy` (not `kubelab`). The repo compose uses
> `${NETWORK_NAME}` which resolves to `kubelab` — this won't work on VPS.

`/opt/headscale/docker-compose.yml`:

```yaml
services:
  headscale:
    container_name: headscale
    image: headscale/headscale:v0.28.0
    restart: unless-stopped
    command: serve
    ports:
      - "3478:3478/udp"
    volumes:
      - ./config:/etc/headscale:ro
      - headscale_data:/var/lib/headscale
      - /etc/letsencrypt:/etc/letsencrypt:ro
    networks:
      - proxy
    healthcheck:
      test: ["CMD", "headscale", "version"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 10s

volumes:
  headscale_data:

networks:
  proxy:
    external: true
```

### 1.3 Obtain TLS certificate (certbot + Cloudflare DNS-01)

Headscale handles TLS itself (not Traefik — see below). Get a cert via certbot:

```bash
sudo apt install certbot python3-certbot-dns-cloudflare

# Create Cloudflare credentials (use same API token as Traefik)
echo "dns_cloudflare_api_token = YOUR_CF_TOKEN" | sudo tee /etc/letsencrypt/cloudflare.ini
sudo chmod 600 /etc/letsencrypt/cloudflare.ini

sudo certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials /etc/letsencrypt/cloudflare.ini \
  -d vpn.kubelab.live \
  --non-interactive --agree-tos -m mlorentedev@gmail.com
```

Certbot auto-renews via systemd timer. After renewal, restart Headscale to pick up new cert:
```bash
# /etc/letsencrypt/renewal-hooks/deploy/restart-headscale.sh
#!/bin/sh
docker restart headscale
```

### 1.4 Add Traefik route (TCP passthrough)

> **CRITICAL: Traefik does NOT support the Tailscale Noise protocol.**
> Traefik only handles `Upgrade: websocket` — the `Upgrade: tailscale-control-protocol`
> header is stripped as a hop-by-hop header. This is a known open issue
> ([traefik#12609](https://github.com/traefik/traefik/issues/12609)).
> Headscale's own docs don't list Traefik as a supported reverse proxy.
>
> **Solution:** TCP passthrough with SNI routing. Traefik forwards raw TCP based on the
> TLS SNI. Headscale handles TLS termination and the Noise protocol directly.

Create `/opt/traefik/dynamic/app-headscale.yml`:

```yaml
tcp:
  routers:
    headscale:
      rule: "HostSNI(`vpn.kubelab.live`)"
      entryPoints:
        - websecure
      service: headscale-tcp
      tls:
        passthrough: true
  services:
    headscale-tcp:
      loadBalancer:
        servers:
          - address: "headscale:443"
```

Key differences from standard HTTP routing:
- `tcp:` not `http:` — raw TCP, not HTTP reverse proxy
- `HostSNI()` not `Host()` — matches on TLS SNI before decryption
- `tls.passthrough: true` — Traefik does NOT terminate TLS
- `address:` not `url:` — TCP service format, no scheme prefix
- No `healthCheck:` — TCP services don't support HTTP health checks
- No `middlewares:` — TCP passthrough bypasses all HTTP middlewares

Traefik auto-detects new files in `dynamic/` (file provider with `watch: true`). No restart needed.

### 1.5 Deploy

```bash
ssh deployer@kubelab-vps
cd /opt/headscale
docker compose up -d
```

### 1.6 Verify

```bash
# On VPS
docker logs headscale --tail 20
curl -s https://vpn.kubelab.live/health
# → {"status":"pass"}
```

From workstation:
```bash
# Verify TLS passthrough (cert issued by Headscale/certbot, not Traefik):
curl -sv https://vpn.kubelab.live/health 2>&1 | grep -E "subject|issuer|HTTP"
# → subject: CN=vpn.kubelab.live
# → issuer: C=US; O=Let's Encrypt; CN=R12
# → HTTP/1.1 200   (NOT HTTP/2 — Headscale serves HTTP/1.1)

# Verify Noise protocol endpoint is reachable:
curl --http1.1 -s -X POST https://vpn.kubelab.live/ts2021 \
  -H "Upgrade: tailscale-control-protocol" -H "Connection: Upgrade"
# → Should NOT return "missing Tailscale handshake header"
# → (with TCP passthrough, Headscale receives the Upgrade header)
```

### 1.6 Create user and pre-auth key

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

Nodes to register:
1. Workstation (msi)
2. VPS (kubelab-vps)
3. Beelink (kubelab-bee)
4. K3s server (kubelab-k3s-server)
5. K3s agent-1 (kubelab-k3s-agent-1)
6. K3s agent-2 (kubelab-k3s-agent-2)
7. RPi 4 (kubelab-rpi4)
8. RPi 3 (kubelab-rpi3)
9. Jetson Nano (kubelab-jet1)

### 2.2 Verify mesh

```bash
tailscale status
```

Expected:
```
100.64.0.1  msi                  kubelab  linux  -
100.64.0.2  kubelab-vps          kubelab  linux  -
100.64.0.3  kubelab-bee          kubelab  linux  -
100.64.0.4  kubelab-k3s-server   kubelab  linux  -
100.64.0.5  kubelab-rpi4         kubelab  linux  -
100.64.0.6  kubelab-rpi3         kubelab  linux  -
100.64.0.7  kubelab-k3s-agent-1  kubelab  linux  -
100.64.0.8  kubelab-jet1         kubelab  linux  -
100.64.0.9  kubelab-k3s-agent-2  kubelab  linux  -
```

```bash
tailscale ping kubelab-vps
# → pong from kubelab-vps (100.64.0.2) via 162.55.57.175:41641 in 158ms

tailscale ping kubelab-rpi4
# → pong from kubelab-rpi4 (100.64.0.5) via 172.16.1.1:41641 in 29ms

tailscale ping kubelab-k3s-server
# → pong from kubelab-k3s-server (100.64.0.4) via 172.16.1.10:41641 in 36ms
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

## Phase 4: Record Tailscale IPs

| Device | Hostname | Headscale IP | LAN IP |
|--------|----------|-------------|--------|
| Workstation | msi | 100.64.0.1 | — |
| VPS | kubelab-vps | 100.64.0.2 | 162.55.57.175 |
| Beelink | kubelab-bee | 100.64.0.3 | 10.0.0.130 |
| K3s server | kubelab-k3s-server | 100.64.0.4 | 172.16.1.10 |
| RPi 4 | kubelab-rpi4 | 100.64.0.10 | 10.0.0.131 / 172.16.1.1 |
| RPi 3 | kubelab-rpi3 | 100.64.0.6 | 10.0.0.133 |
| K3s agent-1 | kubelab-k3s-agent-1 | 100.64.0.7 | 172.16.1.11 |
| Jetson Nano | kubelab-jet1 | 100.64.0.8 | 10.0.0.134 |
| K3s agent-2 | kubelab-k3s-agent-2 | 100.64.0.9 | 172.16.1.12 |

---

## Phase 5: SSH Config Update

Update `~/.ssh/config` with dual-path access: VPN primary, LAN fallback.

**Pattern**: `ssh <host>` uses VPN (works from anywhere). `ssh <host>-lan` uses LAN (fallback when VPN down, local network only). `ssh vps-pub` uses public IP directly (VPS has no LAN).

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

### 6.1 Headscale config change (on VPS)

Edit `/opt/headscale/config/config.yaml`:

```yaml
dns:
  nameservers:
    split:
      staging.kubelab.live:
        - 100.64.0.5      # RPi4 Pi-hole (port 53) → CoreDNS (port 5353)
```

```bash
cd /opt/headscale && sudo docker compose restart headscale
```

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
# → 100.64.0.4 (k3s-server Tailscale IP, Traefik Ingress)
```

---

## Troubleshooting

### TLS cert not issued for vpn.kubelab.live

**Symptoms**: `curl` returns self-signed cert error, `000` status code.

**Root causes (in order of likelihood)**:
1. **Cloudflare API token missing zone access**: Token must have access to `kubelab.live` zone (not just `mlorente.dev`). Verify:
   ```bash
   CF_TOKEN=$(docker inspect traefik --format '{{range .Config.Env}}{{println .}}{{end}}' | grep CF_DNS_API_TOKEN | cut -d= -f2)
   curl -s -H "Authorization: Bearer $CF_TOKEN" "https://api.cloudflare.com/client/v4/zones?name=kubelab.live" | python3 -m json.tools | head -5
   ```
   Fix: Edit token in Cloudflare dashboard → add `kubelab.live` zone.

2. **ACME storage path mismatch**: VPS `traefik.yml` has `storage: /letsencrypt/acme.json` (matching the Docker volume mount). If someone overwrites with the toolkit-generated version, the path changes to `/etc/traefik/acme/acme.json` which doesn't match the mount → resolver fails silently.
   ```bash
   # Check mount
   docker inspect traefik --format '{{json .Mounts}}' | python3 -m json.tools | grep acme
   # Check config
   grep storage /opt/traefik/traefik.yml
   # These MUST match
   ```

3. **Cloudflare proxy enabled**: `vpn.kubelab.live` MUST be DNS-only (grey cloud). WireGuard/DERP cannot traverse Cloudflare proxy.

4. **Failed attempt cached**: Remove stale entry and restart:
   ```bash
   docker stop traefik
   cp /opt/traefik/certs/acme.json /opt/traefik/certs/acme.json.bak
   # Remove vpn.kubelab.live entry if present
   docker start traefik
   ```

### Router uses a non-existent certificate resolver

**Symptom**: All routers show `non-existent certificate resolver` error.

**Root cause**: ACME storage path in `traefik.yml` doesn't match Docker volume mount. Traefik can't initialize the resolver.

**Fix**: Ensure `storage` path in config matches the container mount path (`/letsencrypt/acme.json` on VPS).

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

## VPS vs Repo Differences (Critical)

| Setting | VPS (prod) | Repo (toolkit-generated) |
|---------|-----------|-------------------------|
| Docker network | `proxy` | `kubelab` |
| ACME storage | `/letsencrypt/acme.json` | `/etc/traefik/acme/acme.json` |
| Wildcard cert | `*.mlorente.dev` | `*.kubelab.live` |
| Headscale TLS | certbot DNS-01 (own cert) | Traefik terminates TLS |
| Headscale routing | TCP passthrough (SNI) | HTTP reverse proxy |
| Traefik version | v3.0 | v3.6 |
| traefik.yml path | `/opt/traefik/traefik.yml` | `edge/traefik/generated/prod/` |
| Dynamic configs | `/opt/traefik/dynamic/app-*.yml` | Single `apps.yml` |

> **DO NOT overwrite VPS traefik.yml with toolkit-generated version** until full prod migration
> (PROD-004b: Traefik upgrade, network rename, path alignment).

---

## Last tested

2026-02-21: All phases complete (1-6). 9 nodes registered, mesh connectivity verified.
Subnet router active (RPi 4 → 172.16.1.0/24). Split DNS operational (staging.kubelab.live → CoreDNS).
DNS fix applied on RPi4 (`--accept-dns=false` + `chattr +i`).
2026-02-21 (post-reboot incident): RPi4 VPN down after reboot — boot ordering issue.
Tailscale started before Pi-hole (Docker). Fix: dual nameserver in resolv.conf
(`127.0.0.1` + `8.8.8.8`) + systemd drop-in to order tailscaled after docker.service.
2026-02-22: RPi4 nftables NAT rule had hardcoded USB interface name (`enx00e04c690e15`)
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
Headscale now terminates TLS itself (certbot DNS-01 via Cloudflare). See [error-headscale-noise-http2](../troubleshooting/error-headscale-noise-http2.md).
2026-02-27: tsnet upgraded v1.60.0 → v1.80.0. Headscale v0.28.0 requires minimum_version=v1.74;
older tsnet failed silently with EOF during Noise handshake. Native clients worked because they
were already >= v1.74. Re-test SUCCESSFUL: ts-bridge registered as 100.64.0.11 (user=work),
10 peers visible, DERP#13 connected, UPnP portmap active. 5 stacked issues resolved over 2 days.
2026-03-03: Narrowed split DNS from `kubelab.live` → `staging.kubelab.live` on VPS config.
Previous broad scope caused total DNS failure for prod domains (status.kubelab.live etc.)
when RPi4 was off — Tailscale MagicDNS sent all `*.kubelab.live` queries to RPi4 instead of
public Cloudflare DNS. Now only staging domains require RPi4; prod resolves via 1.1.1.1.
Config also updated in repo IaC (`infra/stacks/services/core/headscale/config/config.yaml`).

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

> **Added 2026-02-25.** Ref: [ADR-013](../adr/adr-013-vpn-consolidation.md).

Headscale ACLs control which nodes can communicate. kubelab uses **file-based ACLs** for IaC/Git traceability.

### 8.1 ACL file location

The policy file lives in the kubelab repo and is mounted into the Headscale container:

```
kubelab/infra/stacks/services/core/headscale/config/policy.hujson
```

### 8.2 Identity model

| Headscale User | Purpose | Devices |
|----------------|---------|---------|
| `kubelab` | Admin (full mesh access) | workstation, corporate workstation (ts-bridge), phone (future) |
| `work` | Windows PCs (RDP targets, implicit deny outbound) | 3+ Windows mini PCs (ts-bridge server) |
| `contractors` | External access (future, restricted scope) | Contractor machines (ts-bridge client) |

**Key:** The human user (manu) always authenticates as `kubelab`. The `work` user represents a device class, not a person.

### 8.3 ACL rules summary

| Source | Destination | Action | Notes |
|--------|-------------|--------|-------|
| `group:admin` | `*:*` | Accept | Full mesh access |
| `group:contractors` | `group:work:3389` | Accept | RDP only to Windows PCs |
| `group:work` | (anything) | **Deny** | Implicit deny — no outbound rules |

### 8.4 Applying ACL changes

```bash
# After editing policy.hujson in the repo:
scp infra/stacks/services/core/headscale/config/policy.hujson deployer@kubelab-vps:/opt/headscale/config/
docker exec headscale headscale policy reload
# Or restart: cd /opt/headscale && docker compose restart headscale
```

### 8.5 Enable file-based ACLs in Headscale config

In `/opt/headscale/config/config.yaml`:

```yaml
policy:
  mode: file
  path: /etc/headscale/policy.hujson
```

Mount the file in `docker-compose.yml`:

```yaml
volumes:
  - ./config:/etc/headscale:ro
```

### 8.6 Headplane (admin UI)

Headplane provides a browser-based admin interface for Headscale:

- **URL:** `headplane.kubelab.live`
- **Auth:** Authelia one-factor (PROTECTED tier)
- **ACL mode:** Read-only viewer (file-based ACLs managed in Git, not editable from UI)
- **Features:** Node management, route approval, key management, real-time status

---

## Phase 9: Contractor Onboarding (Future)

> **Added 2026-02-25.** Ref: [ADR-013](../adr/adr-013-vpn-consolidation.md).

When onboarding a contractor who needs RDP access to Windows PCs:

### 9.1 Generate contractor key

```bash
# Time-limited, non-reusable key
docker exec headscale headscale preauthkeys create --user <CONTRACTORS_USER_ID> --expiration 720h
```

### 9.2 Distribute ts-bridge

Provide the contractor with:
1. ts-bridge binary (from GitHub releases)
2. `.env` file with:
   ```bash
   TS_CONTROL_URL=https://vpn.kubelab.live
   TS_AUTHKEY=<CONTRACTOR_PREAUTH_KEY>
   TS_TARGET=<WINDOWS_PC_HEADSCALE_IP>:3389
   ```

### 9.3 Verify isolation

Contractor can ONLY reach Windows PCs on port 3389 (per ACL). Cannot reach homelab, K3s, or any other service. Verify:

```bash
# From contractor's ts-bridge: RDP should work
# From contractor's ts-bridge: SSH to any homelab node should timeout/refuse
```

### 9.4 Revoke access

```bash
# Remove the node
docker exec headscale headscale nodes delete -i <CONTRACTOR_NODE_ID>
```
