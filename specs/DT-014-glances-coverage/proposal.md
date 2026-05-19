---
id: "DT-014-glances-coverage"
type: spec
status: draft
created: "2026-05-18"
tags: [spec, proposal, ansible, observability]
template_version: "1.0"
---

# DT-014-glances-coverage

> Vault task: `DASH-DT-014`. Folder slug uses `DT-` prefix because `init-spec.sh` regex (`^[A-Z]+-\d+(-[a-z0-9-]+)?$`) does not accept the `DASH-DT-` two-hyphen form.

## Why

The Homepage cockpit (`infra/k8s/base/services/homepage-config/services.yaml`) configures Glances widgets pointing at `100.64.0.2:61208` (VPS), `100.64.0.10:61208` (rpi4), `100.64.0.11:61208` (ace1), and `100.64.0.8:61208` (jetson). None of these four endpoints exist — Glances is only deployed on rpi3, beelink, and ace2. Result: 4 of 7 dashboard widgets render no metrics. This ticket closes the VPS + rpi4 gap (both always-on per ADR-028); ace1 and jetson are out of scope (ace1 on-demand, jetson has legacy Python 2026-vintage that may not run Glances 4.5).

This is a **pragmatic incremental fix** — the durable enterprise answer is [[DASH-DT-015]] (migrate to Prometheus + node_exporter + Grafana). Glances is hobbyist tier; using it here matches the existing wiring and unblocks the dashboard today without committing to a sub-enterprise pattern long-term.

## What

After this PR:

1. `curl http://100.64.0.2:61208/api/4/quicklook` returns HTTP 200 from any tailnet member.
2. `curl http://100.64.0.10:61208/api/4/quicklook` returns HTTP 200 from any tailnet member.
3. The Homepage cockpit VPS + RPi4 widgets render live CPU/memory/disk metrics.
4. `make provision NODE=vps ENV=prod TAGS=monitoring` and `make provision NODE=rpi4 ENV=prod TAGS=monitoring` deploy/restart the Glances container idempotently.

Implementation pattern: replicate the **beelink_services** approach (bind to `tailscale_ip` only, not 0.0.0.0). New Ansible roles `vps_services` and `rpi4_services` each owning a minimal `docker-compose.yml.j2` containing only the Glances service. Wired into the existing `provision-vps.yml` and `provision-rpi4.yml` playbooks.

## Out of scope

- **ace1 and jetson Glances deployment** — ace1 is on-demand (low value for monitoring); jetson runs Ubuntu 18.04 with Python that may not satisfy Glances 4.5 requirements. Both deserve a separate ticket if needed.
- **Migration to Prometheus + node_exporter** — tracked as [[DASH-DT-015]] (separate multi-PR initiative, 500-1000 LOC).
- **Aligning rpi3 to the tailscale-bind pattern** — rpi3 currently binds 0.0.0.0 (less secure than beelink's tailscale-bind). Minor inconsistency, tracked separately rather than smuggled into this PR (Atomic PRs rule).
- **Authelia / Traefik fronting for Glances** — would deviate from existing pattern (rpi3/beelink/ace2 all expose raw port via Tailscale IP). No Traefik IngressRoute, no Authelia middleware. Tailnet itself is the auth boundary.
- **Glances version bump from 4.5.2** — keep parity with the 3 nodes already running it; bumps go in a separate ticket once we decide on a uniform version policy.

## Risks / open questions

- **Atomic PR scope drift.** Estimated 170-200 LOC (2 new roles + 2 playbook updates). Above the 80 LOC the handoff anticipated, still under the 300 LOC Atomic PR limit. RESOLVED: keep both roles minimal (only Glances, no other services).
- **Idempotency on VPS** where `traefik_vps` already templates a `docker-compose.yml.j2`. RESOLVED: new role uses a separate compose file (`/opt/glances/docker-compose.yml`) with its own project name (`glances`), not the Traefik stack. No collision.
- **Rpi4 provisioning sequence.** `provision-rpi4.yml` already runs gateway/docker/tailscale/coredns roles. RESOLVED: append `rpi4_services` after `docker` (depends on Docker daemon) and after `tailscale` (depends on tailscale_ip being assigned).
- **Pre-flight: are VPS + rpi4 both reachable and powered?** Required for the live smoke test. User to confirm before running deploy.

## Acceptance criteria

- [ ] AC1: New role `infra/ansible/roles/vps_services/` exists with `defaults/`, `tasks/`, `templates/compose.yml.j2`; deploys only Glances; binds to `{{ vps.tailscale_ip }}:{{ glances_port }}:{{ glances_port }}`.
- [ ] AC2: New role `infra/ansible/roles/rpi4_services/` exists with the same minimal structure; binds to `{{ rpi4.tailscale_ip }}:{{ glances_port }}:{{ glances_port }}`.
- [ ] AC3: `infra/ansible/playbooks/provision-vps.yml` includes `vps_services` role with `tags: [services, monitoring]`.
- [ ] AC4: `infra/ansible/playbooks/provision-rpi4.yml` includes `rpi4_services` role with `tags: [services, monitoring]`.
- [ ] AC5: `yamllint` and `ansible-lint` clean on all new/modified files.
- [ ] AC6: `ansible-playbook --check` dry-run succeeds for both `provision-vps` and `provision-rpi4`.
- [ ] AC7: Live smoke: `curl -sf http://100.64.0.2:61208/api/4/quicklook | jq .cpu.total` returns a float (VPS Glances up).
- [ ] AC8: Live smoke: `curl -sf http://100.64.0.10:61208/api/4/quicklook | jq .cpu.total` returns a float (rpi4 Glances up).
- [ ] AC9: Homepage cockpit visually renders VPS + RPi4 tiles with live metrics (manual browser check).

## References

- Vault: `10_projects/kubelab/11-tasks.md` (DASH-DT-014, DASH-DT-015).
- Pattern source: `infra/ansible/roles/beelink_services/templates/compose.yml.j2` — tailscale-bind variant.
- Counter-pattern: `infra/ansible/roles/rpi3_services/templates/compose.yml.j2` — 0.0.0.0 bind (less secure, NOT replicated here).
- Dashboard wiring: `infra/k8s/base/services/homepage-config/services.yaml` lines 80-145.
- ADR-028: Operational Topology (always-on vs on-demand classification).
- Related memory: `feedback_no_guessing_infra.md`, `feedback_collaborative_style.md`.
