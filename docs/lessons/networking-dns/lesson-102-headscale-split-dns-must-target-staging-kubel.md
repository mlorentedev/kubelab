---
id: lesson-102-headscale-split-dns-must-target-staging-kubel
type: lesson
status: active
created: "2026-03-03"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Headscale Split DNS Must Target `staging.kubelab.live`, Not `kubelab.live`

**Context**: Uptime Kuma on RPi3 (`status.kubelab.live`) unreachable from workstation browser. K3s cluster and RPi4 were intentionally off. `nslookup status.kubelab.live` timed out — DNS resolver was `100.100.100.100` (Tailscale MagicDNS) routing to RPi4 which was down.

**Problem**: Headscale split DNS was configured as `kubelab.live → 100.64.0.5` (RPi4). This captured ALL `*.kubelab.live` queries, including prod domains that have public Cloudflare A records (`status.kubelab.live → 162.55.57.175`). When RPi4 is off, Tailscale's MagicDNS has no fallback for split DNS routes — queries simply timeout. Prod domains become unreachable from any VPN client despite having valid public DNS records.

**Impact**: Any VPN client cannot reach prod services (`status.kubelab.live`, `grafana.kubelab.live`, etc.) when RPi4 is down. The external monitoring page (Uptime Kuma) — whose entire purpose is to work when the lab is off — was unreachable from the primary workstation.

**Solution**: Narrowed split DNS from `kubelab.live` to `staging.kubelab.live` in Headscale config (both VPS live config and repo IaC at `infra/stacks/services/core/headscale/config/config.yaml`). Now:
- `*.staging.kubelab.live` → RPi4 CoreDNS (requires RPi4 up — expected for staging)
- `*.kubelab.live` (prod) → global resolvers (1.1.1.1) → Cloudflare → VPS (works always)

**Rule**: Headscale split DNS routes have NO fallback — if the target DNS server is unreachable, queries timeout with no retry to global resolvers. Only route domains that genuinely need internal resolution (staging). Prod domains with public Cloudflare records must NOT be captured by split DNS. For VPN-only bare-metal services without public DNS (ollama, jetson), use Headscale `extra_records` instead of split DNS — they inject A records directly into MagicDNS without depending on any external DNS server.

---
