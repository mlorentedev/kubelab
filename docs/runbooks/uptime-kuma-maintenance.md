---
id: uptime-kuma-maintenance
type: runbook
status: active
created: "2026-05-24"
---

# Uptime Kuma maintenance — operational runbook

> External prod-monitoring instance (`status.kubelab.live`) running on
> rpi3 (Headscale `100.64.0.6`, LAN `10.0.0.157` per SSOT-003) as a
> standalone Docker Compose service. Always-on per ADR-028 — it is the
> only node that watches prod from outside the VPS, so its health is
> a tier-0 concern even though the box itself is the smallest (1 GB RAM,
> SD card, RPi 3 hardware).
>
> Source of truth: `infra/ansible/roles/rpi3_services/`. Compose lives
> on rpi3 at `~/uptime-kuma/compose.yml`, deployed via
> `make deploy TARGET=rpi3 ENV=prod`. **Never** SSH and edit by hand —
> regenerate via the role and redeploy.

## Affected services inventory

Monitors exported from Uptime Kuma group these external probes (see
backup JSON for the live list):

- All prod public ingresses behind VPS Traefik (`*.kubelab.live`):
  api, web, grafana, authelia, gitea, n8n, argocd, vpn (Headscale UI),
  homepage.
- TLS certificate expiry notifications (`expiryNotification: true`)
  for the 20 HTTPS monitors registered in OPS-005.
- `vpn.kubelab.live` reachability (public-IP path, not Tailscale, per
  bootstrap rule — see CLAUDE.md gotcha #20).
- Argo CD hub on aws1 (`argocd.kubelab.live`).

Staging is **not** monitored from rpi3 — staging is VPN-only and rpi3
should not depend on Tailscale being up to do its job. Staging
self-monitoring is deferred to Stream D3 Prometheus inside the
homelab cluster.

## Backup & export

The Uptime Kuma SQLite DB lives in the `uptime_kuma_data` Docker
volume (mount `/app/data`). Two artefacts must be backed up together:

1. **DB snapshot** (`kuma.db` + WAL files) — captures monitors,
   probe history, notification config, status pages.
2. **Settings export JSON** — captures monitor definitions in a
   human-readable form for fast re-import into a fresh instance.

### Manual backup (one-off, before risky change)

```bash
# Cold-consistent snapshot via SQLite .backup (no downtime).
ssh manu@100.64.0.6 \
  "docker exec uptime-kuma sqlite3 /app/data/kuma.db \
     \".backup '/app/data/backup-\$(date +%Y%m%d-%H%M).db'\""

# Copy snapshot off the SD card.
scp manu@100.64.0.6:/var/lib/docker/volumes/uptime_kuma_data/_data/backup-*.db \
  ~/Projects/kubelab/.local/uptime-kuma-backups/
```

`sqlite3 .backup` is the right primitive here — `cp` of a live DB
risks half-written pages because SQLite uses WAL.

### Settings export (re-importable JSON)

Uptime Kuma UI → `Settings → Backup → Export`. Save the JSON to
`~/Projects/kubelab/.local/uptime-kuma-backups/settings-YYYYMMDD.json`.

Do this whenever monitors are added/removed or notification config
changes — at minimum monthly.

### Scheduled automation (TODO — tracked as MON-010-AUTO)

A `systemd timer` on rpi3 that runs the `sqlite3 .backup` command nightly
and rotates 7 daily / 4 weekly copies inside the data volume is not yet
implemented. Until then the manual backup above is the only path.

## DB prune / disk pressure

Uptime Kuma's history table (`heartbeat`) grows linearly with probe
frequency × monitor count. At 60 s interval × 25 monitors ≈ 36k rows
per day. Default retention is unbounded.

**Prune schedule**: monthly, or whenever
`docker exec uptime-kuma du -sh /app/data` reports >300 MB.

Via UI: `Settings → Monitor History → Clear Data older than N days`.
Recommended retention: **90 days**.

Via SQL (fallback if UI unresponsive):

```bash
ssh manu@100.64.0.6 \
  "docker exec uptime-kuma sqlite3 /app/data/kuma.db \
     'DELETE FROM heartbeat WHERE time < datetime(\"now\", \"-90 days\"); VACUUM;'"
```

`VACUUM` reclaims free pages — important on the SD card where wear
levelling does not benefit from sparse files. Expect 30–60 s while
holding a write lock; do this off-peak.

## Monitor interval review

Once per quarter, walk the monitor list and ask:

- Does this service still exist? (Drop monitors for retired services
  — they emit alarms and pollute history.)
- Is the probe interval right? Public HTTPS is fine at 60 s; very
  noisy services (gitea webhooks during CI) can go to 120 s without
  losing useful signal.
- Are the notification thresholds reasonable? Default 2 consecutive
  failures = downtime is too sensitive for the home internet
  connection — prefer 3 for non-paging endpoints.
- TLS expiry monitors: confirm `expiryNotification: true` is still set
  on every HTTPS monitor (OPS-005 contract). Easy regression after a
  bulk import.

## SD card longevity mitigation

The RPi 3 is the most failure-prone always-on node — small RAM and SD
card both wear. Mitigations in priority order:

1. **Prune aggressively** (see DB prune above). Heartbeat writes are
   the dominant write load.
2. **`log-driver: json-file` with `max-size: 10m` + `max-file: 3`** in
   `compose.yml` — already set in the role template. Caps Docker log
   I/O.
3. **Disable Docker live-restore + persistent state if not needed** —
   not applicable here, we need persistent state.
4. **Annual SD card replacement** — schedule a recurring task and
   replace prophylactically. Cost is <$15. Cloning procedure:
   `dd if=/dev/mmcblk0 of=rpi3-backup.img bs=4M status=progress` from
   a Linux box with USB SD reader; restore to new card with
   `dd if=rpi3-backup.img of=/dev/sdX bs=4M`.
5. **Long term**: migrate Uptime Kuma to aws1 (always-on, no SD card,
   already part of the always-on fleet). Tracked as future work in
   ADR-028 follow-up; not scheduled.

## When rpi3 is unreachable

If `status.kubelab.live` returns 504 / DNS fails / monitors stop
emitting:

1. Try Tailscale: `ssh manu@100.64.0.6` (Headscale IP). If this works,
   triage container with `docker ps`, `docker logs uptime-kuma`,
   `df -h`.
2. If Tailscale is down (the failure mode that motivated SSOT-003),
   fall back to LAN: `ssh manu@10.0.0.157`. Requires being on home
   network or VPN to the home router.
3. If both fail, physical access is the only remaining path. Power
   cycle is a last resort — it loses dmesg / SD card error context
   that is critical for diagnosing whether the card is dying.
4. Capture pre-reboot evidence with `dmesg | tail -200`,
   `journalctl -u docker -b --no-pager | tail -100`,
   `cat /var/log/syslog | grep -i mmc | tail -50` before power cycling.

## References

- ADR-028 — Operational Topology (always-on vs on-demand).
- OPS-005 — TLS certificate expiry notifications.
- SSOT-003 — rpi3 LAN IP fallback (related forensic-loss incident).
- MON-010 — vault `11-tasks.md` (this runbook is its deliverable).
