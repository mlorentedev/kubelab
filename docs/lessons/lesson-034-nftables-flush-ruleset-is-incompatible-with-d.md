---
id: lesson-034-nftables-flush-ruleset-is-incompatible-with-d
type: lesson
status: active
created: "2026-03-19"
owner: manu
tags: [kubelab, lesson]
---

# nftables `flush ruleset` is incompatible with Docker/UFW/Tailscale

**Context**: RPi4 gateway role uses nftables for NAT masquerade. Template had `flush ruleset`.

**Problem**: `systemctl restart nftables` triggers ExecStop which runs `flush ruleset`, destroying ALL iptables-nft rules from Docker, UFW, and Tailscale. CoreDNS containers lose port mappings, LAN nodes lose internet, VPN routing breaks. Even removing `flush ruleset` from our template doesn't help — the systemd unit's ExecStop still flushes.

**Solution**: (1) Use a named table (`inet kubelab`) instead of generic `inet nat`/`inet filter` — avoids collision with Docker's `ip nat`. (2) Use `systemctl reload` (ExecReload = `nft -f`), NEVER `restart` (ExecStop = `flush ruleset`). (3) Atomic idempotent pattern in nftables.conf: `table inet kubelab` (create if missing) → `delete table inet kubelab` → `table inet kubelab { ... }` (recreate fresh).

**Rule**: Never use `flush ruleset` in nftables configs on hosts running Docker. Never `restart` nftables — always `reload`. Use named tables to isolate your rules from other services.
