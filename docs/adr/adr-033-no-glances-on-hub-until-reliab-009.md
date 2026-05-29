---
id: adr-033-no-glances-on-hub-until-reliab-009
type: adr
status: active
created: "2026-05-19"
---

# ADR-033: No Glances on Hub (aws1) Until RELIAB-009 Closes

> **Date:** 2026-05-19
> **Status:** Accepted
> **Stakeholders:** Manu (sole operator)
> **Related:** [adr-028-operational-topology](adr-028-operational-topology.md), RELIAB-009, DASH-DT-014a, DASH-DT-014b, DASH-DT-015

## Context

PR #175 (DASH-DT-014a) closed the Glances coverage gap on ace1 + ace2 via a shared Ansible role. Post-merge verification of the Homepage cockpit (AC8) confirmed live tiles for 6 of 8 nodes. Two nodes have no Glances widget: **Beelink** (already runs Glances, cockpit gap only — covered by DASH-DT-014b) and **aws1** (the Argo CD hub on AWS Spot t4g.small).

The natural follow-up question — "can we add Glances to aws1 too?" — has a non-trivial answer that deserves a documented decision rather than a one-line README note.

## Forces

- **Memory budget**: aws1 is a t4g.small (2 GB RAM). Per `CLAUDE.md`: "2 GB fits Argo CD with all components (7 pods, ~940 MB). Upgraded from t4g.micro (2026-03-28) — 1 GB caused OOM on every Helm upgrade." There is roughly 1 GB of headroom shared across kernel, kubelet, container runtime, networking, and burst.
- **Recent OOM incident**: the 2026-05-06 cascade on aws1 that directly motivated RELIAB-009 (Argo CD hub memory hygiene + zombie-pod GC + hub IaC bootstrap, Plan B1). Hub stability is currently fragile; non-essential services on the hub raise blast-radius risk.
- **Hub has no Ansible day-2 path**: aws1 was bootstrapped via Terraform cloud-init (AWS-001..005). No `make provision NODE=aws1 ENV=hub` exists today. RELIAB-009 Plan B1 closes that gap by extending `k3s_server` role for hub day-2 use. Deploying Glances to aws1 today would require either ad-hoc Docker (off-the-Ansible-rails, violates standing orders) or a one-off bootstrap (premature work the RELIAB-009 plan supersedes).
- **Observability alternative path is in flight**: DASH-DT-015 covers the durable migration from Glances widgets to Prometheus + `node_exporter`. `node_exporter` is lighter than Glances (~10-15 MB vs ~80 MB resident) and is the right enterprise pattern for hub-class nodes. Adding Glances to aws1 now would create disposable work that DASH-DT-015 deletes.
- **Operational signal**: the user can already see aws1 health via the Argo CD dashboard (`https://argo.kubelab.live`) which is the natural surface for the hub. Adding a Glances tile would duplicate, not complement, that signal.

## Decision

**Do not deploy Glances to aws1.** The Homepage cockpit entry for aws1 stays as `ping: https://argo.kubelab.live` (the current state) — a liveness signal scoped to what the hub actually serves.

Revisit when RELIAB-009 closes and `node_exporter` is the deployment target, not Glances. At that point:
1. aws1 has an Ansible day-2 path (Plan B1).
2. The observable surface is `node_exporter` + Grafana, not Glances + Homepage widget.
3. Memory footprint is `node_exporter` (small), not Glances (medium).
4. Same shared role pattern as the rest of the fleet.

## Consequences

- **Positive**: hub memory budget stays predictable. No risk of a 256 MB Glances container nudging the OOM watermark. No premature one-off deploy that DASH-DT-015 would tear down.
- **Negative**: the cockpit Nodes section is visually asymmetric — aws1 looks "less monitored" than peers. Mitigation: the Argo CD dashboard provides better hub signal than a Glances tile would.
- **Followups**: when RELIAB-009 closes, file a sub-task on DASH-DT-015 to onboard aws1 to `node_exporter` and update the cockpit accordingly. When DASH-DT-015 closes, this ADR can be marked superseded.

## Alternatives considered

1. **Glances as a Pod inside the hub K3s cluster** — more kosher with the topology (already managed via Argo CD), but still consumes hub memory and still creates work that DASH-DT-015 supersedes. Rejected on the same memory + premature-work grounds.
2. **Glances via Docker bare-metal on aws1** — fast but violates the rule that hub state is managed declaratively (Terraform cloud-init today, Ansible day-2 after RELIAB-009). Rejected.
3. **Reduce Argo CD resource requests to free room for Glances** — possible but risks regressing the very stability that the t4g.small upgrade was designed to deliver. Rejected.

## References

- [adr-028-operational-topology](adr-028-operational-topology.md) — defines aws1 as always-on hub, resource-constrained.
- RELIAB-009 (active in `Now` queue of `11-tasks.md`) — hub IaC bootstrap (Plan B1) and memory hygiene work.
- DASH-DT-015 (in `11-tasks.md`) — Prometheus + `node_exporter` migration that this ADR defers to.
- 2026-05-06 OOM incident — direct trigger of RELIAB-009.
- `CLAUDE.md` "Hub t4g.small sizing" gotcha — current memory headroom analysis.
