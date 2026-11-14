---
id: "AI-013-hermes-liveness"
type: spec
status: implementing
created: "2026-11-14"
issue: "mlorentedev/kubelab#2175"
tags: [spec, proposal]
template_version: "1.0"
owner: manu
wip_override: "Operator authorized AI-013 after AI-016 archive PR #3543; the other active specs belong to separate lanes and are not modified here. (17 active, limit 10, 2026-11-14)"
---

# AI-013-hermes-liveness

## Why

hermes-kubelab can die while ace2 remains powered without notifying the operator: the retired hermes-nan watchdog has no successor, the Hermes API is not externally probeable, and no local gateway watcher feeds the notification fabric. The replacement must distinguish a failed agent on a running node from the normal, silent state of an on-demand node that is powered off. Bitácora: mlorentedev/kubelab#2175.

## What

Compose will mark the gateway healthy only while its unauthenticated, bounded `/health` endpoint answers. A root-owned systemd oneshot on ace2 will read that health through the agent's rootless Docker daemon every two minutes, after a ten-minute boot/activation grace period. A failed probe will use the existing `kubelab-notify@` failure path and its incident deduplication/spool; a subsequent healthy probe will use the existing recovery path. The watcher exists and runs only while Hermes is configured. No external monitor or persistent/catch-up timer is added, so a powered-off ace2 generates no page.

## Out of scope

- No Uptime Kuma push monitor, external HTTP probe, Headscale ACL change or inbound port.
- No gateway restart/policy change, Slack direct delivery, new notification channel or new dependency.
- No audit of every transient Docker restart: the contract is sustained loss of health, not an event log.
- No model, Telegram, email, curator, fallback-probe or image-quota work.
- No always-on watchdog moved to another host; the detector deliberately runs on ace2.

## Risks / open questions

- Boot and container startup can make an initially healthy service look unavailable. Mitigated by Compose `start_period`, a ten-minute timer grace period and no `Persistent` catch-up run.
- Docker may restart a briefly killed gateway between polls. That transient is intentionally not paged; live acceptance uses a stopped gateway to prove sustained loss.
- The notification fabric can be unreachable during an agent outage. The existing node-notify spool preserves the page for ordered later delivery; this spec does not weaken that path.
- The intentional egress kill switch stops the gateway too. The watcher remains independent so an unexpected daemon/egress death cannot disable its own detector; an operator seeking a planned silent stop stops the watcher timer first, as the runbook specifies.
- The simple `/health` route exposes only status, platform and version and requires no credential. Slack/provider readiness remains the existing authenticated `/health/detailed` provisioning check, not a reason to page on a third-party outage.

## Acceptance criteria

- [ ] **AC1 — detection and delivery:** with ace2 running, a stopped or unhealthy gateway fails the local health contract and the two-minute watcher emits one deduplicated incident through `kubelab-notify@` within the next probe/delivery interval, after the declared boot grace period.
- [ ] **AC2 — recovery and semantics:** a healthy probe exits successfully, failed/missing/starting health fails closed, and recovery uses `kubelab-notify-recovered@`; transient provider/Slack state is not part of the liveness verdict.
- [ ] **AC3 — on-demand silence:** powering ace2 off cannot page: there is no external monitor, no `Persistent` timer and no always-on dependency on the gateway.
- [ ] **AC4 — configuration lifecycle:** disabling Hermes disables the watcher and removes its units; enabling Hermes installs and starts the watcher only after the existing gateway health verification succeeds.
- [ ] **AC5 — reproducible evidence:** provisioning is idempotent (`changed=0` on a second run), focused tests fail if the wiring is removed, and an operator-approved live stop/start exercise records the resulting notification evidence without exposing credentials.

## References

- Bitácora: mlorentedev/kubelab#2175.
- [ADR-028](../../docs/adr/adr-028-operational-topology.md), [ADR-044](../../docs/adr/adr-044-unified-notification-routing-fabric.md), [ADR-068](../../docs/adr/adr-068-ace2-operator-agent-tooling.md).
- Archived NOTIFY-001 verification and the existing `node_notify` role/tests.
