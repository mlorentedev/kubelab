---
id: "DT-014-glances-coverage"
type: spec
status: draft
created: "2026-05-18"
tags: [spec, proposal, ansible, observability]
template_version: "1.0"
---

# DT-014-glances-coverage (PR3a)

> Vault task: `DASH-DT-014a`. Folder slug uses `DT-` prefix (init-spec.sh regex).
> **Re-scoped 2026-05-18 evening** after audit invalidated original premise: VPS already had Glances `Up 7 weeks`, rpi4 had Glances `Up About an hour`. Original scope (deploy on VPS+rpi4) became redundant. New scope below.

## Why

The Homepage cockpit references Glances widgets for 7 nodes but only 4 currently have a Glances container running, deployed via 3 distinct patterns (beelink inline + tailscale_ip bind; rpi3 inline + 0.0.0.0 bind; VPS + rpi4 ad-hoc without Ansible). User goal: **homogenize all nodes onto one shared pattern before migrating to Prometheus + node_exporter** ([[DASH-DT-015]]).

This PR3a is the **first half of the homogenization initiative**: introduce a shared `glances` Ansible role and close the coverage gap on the two nodes still missing it (ace1 + ace2). PR3b ([[DASH-DT-014b]]) then migrates the four existing deployments onto the shared role.

## What

After this PR:

1. New role `infra/ansible/roles/glances/` exists with the beelink tailscale_ip-bind pattern.
2. `provision-ace1.yml` deploys Glances on ace1 via the shared role.
3. `provision-ace2.yml` deploys Glances on ace2 via the shared role.
4. `ace2_services` role no longer carries the legacy `/opt/glances` cleanup tasks (those are obsolete now that we want Glances back on ace2 via the shared role).
5. `curl http://100.64.0.11:61208/api/4/quicklook` and `curl http://100.64.0.5:61208/api/4/quicklook` both return 200.
6. Homepage cockpit renders live ace1 + ace2 tiles.

## Out of scope

- **Existing 4 Glances deployments** (beelink_services, rpi3_services, VPS ad-hoc, rpi4 ad-hoc) — tracked as [[DASH-DT-014b]] / PR3b. Touching them here would balloon scope past Atomic PR limit and create review fatigue.
- **My earlier `vps_services` and `rpi4_services` ad-hoc roles** committed earlier in this branch (commit `88cea7a`). They stay until PR3b deletes them; they are functional (binding tailscale_ip on next deploy) but ad-hoc.
- **jetson Glances** — [[DASH-DT-016]] (Ubuntu 18.04 + Python 3.6/3.7 compat investigation).
- **Migration to Prometheus + node_exporter** — [[DASH-DT-015]] (separate initiative, 500-1000 LOC, multi-PR).

## Risks / open questions

- **ace2 `legacy_glances` cleanup tasks**: currently run on every provision and delete `/opt/glances/docker-compose.yml`. The new shared role uses the SAME path `/opt/glances`. RESOLVED: remove the cleanup tasks from `ace2_services` in this PR. They were added when Glances was removed per ADR-028 (ace2 = Ollama only); we are reversing that decision for observability coverage.
- **ace1 has no `ace1_services` role** and `provision-ace1.yml` currently has no per-host services play. RESOLVED: add the shared `glances` role directly to the existing roles list in `provision-ace1.yml`.
- **PR3b interim state**: between PR3a merge and PR3b merge, the repo has two patterns coexisting (shared role on ace1/ace2; inline + ad-hoc on the other 4). Acceptable for a few days; explicitly tracked in [[DASH-DT-014b]].

## Acceptance criteria

- [ ] AC1: `infra/ansible/roles/glances/` exists with `defaults/`, `tasks/`, `templates/compose.yml.j2`, `handlers/main.yml`. Tailscale_ip bind. Image from `config.apps.services.observability.glances.image`.
- [ ] AC2: `provision-ace1.yml` invokes the shared `glances` role with tags `[services, monitoring]`.
- [ ] AC3: `provision-ace2.yml` invokes the shared `glances` role with tags `[services, monitoring]`.
- [ ] AC4: `ace2_services` no longer contains the 3 legacy `/opt/glances` cleanup tasks.
- [ ] AC5: `yamllint` clean (warnings ≤ 130 char per CLAUDE.md rule); `ansible-lint` no NEW violations (matches existing repo-wide pattern, tracked as TOOL-009).
- [ ] AC6: Live smoke: `make provision NODE=ace1 ENV=staging TAGS=monitoring` succeeds; `curl http://100.64.0.11:61208/api/4/quicklook` returns 200.
- [ ] AC7: Live smoke: `make provision NODE=ace2 ENV=staging TAGS=monitoring` succeeds; `curl http://100.64.0.5:61208/api/4/quicklook` returns 200.
- [ ] AC8: Homepage cockpit ace1 + ace2 tiles render live metrics (manual browser check).

## References

- Vault: `10_projects/kubelab/11-tasks.md` (DASH-DT-014a, DASH-DT-014b, DASH-DT-015, DASH-DT-016).
- Pattern source: `infra/ansible/roles/beelink_services/templates/compose.yml.j2` — tailscale-bind pattern.
- Dashboard wiring: `infra/k8s/base/services/homepage-config/services.yaml`.
- ADR-028: Operational Topology.
- Related memory: `feedback_verify_before_acting.md` (drove the audit that re-scoped this ticket), `feedback_collaborative_style.md`.
