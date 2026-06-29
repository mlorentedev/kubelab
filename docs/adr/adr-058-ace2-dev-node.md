---
id: "adr-058-ace2-dev-node"
type: adr
status: accepted
created: "2026-06-29"
tags: [architecture, dev-environment, homelab, cde, agents, security, topology]
related:
  - adr-028-operational-topology
  - adr-029-intelligence-layer
  - adr-037-environment-promotion-strategy
  - adr-023-hub-spoke-multicloud-gitops
  - adr-052-cluster-access-transport
issue: mlorentedev/kubelab#809
owner: manu
---

# ADR-058: ace2 dev-node — self-hosted CDE, dev-flow model, and agent security posture

## Status

Accepted — 2026-06-29

Repurposes **ace2** (Acemagic-2, 12GB x86) from Ollama LLM compute to a centralized development node. Amends [ADR-028](adr-028-operational-topology.md) (node classification) and [ADR-029](adr-029-intelligence-layer.md) (local inference placement). Tracks [#809](https://github.com/mlorentedev/kubelab/issues/809).

## Context

ace2 was provisioned as an on-demand Ollama LLM compute node ([ADR-028](adr-028-operational-topology.md)), but it is effectively idle:

- The in-cluster consumer of local inference — `/v1/llm` ([ADR-029](adr-029-intelligence-layer.md)) — is **decided but unbuilt**. Nothing in the platform consumes ace2's Ollama today.
- Inference is served by OpenRouter (VPS fallback); the planned embedding pipeline uses `nomic-embed-text` on VPS CPU or OpenRouter embeddings. Mistral Nemo 12B on ace2's CPU is marginal and unattended.
- The K8s `external/ollama.yaml` (Service + EndpointSlice + IngressRoute) points at an on-demand node that is usually powered off — a stub.

Meanwhile there is **no dedicated development tier** in the topology. Tooling and mesh access are inconsistent across workstations (see `docs/runbooks/non-admin-workstation-access.md`); agents (Claude Code, Codex, pi) run on whichever workstation has the repo, causing environment drift and preventing parallel orchestration; staging deploys and CI operations originate from "whichever machine has the repo".

## Decision

### D1 — ace2 becomes a centralized self-hosted CDE (the `dev-node`)

A persistent (on-demand) tmux workspace host where the toolchain, repos, and agents live server-side, accessed from any workstation via SSH / ts-bridge ([ADR-052](adr-052-cluster-access-transport.md)). This is the self-hosted Cloud-Dev-Environment pattern (Coder / Codespaces class), not a bespoke setup. The environment is defined as **IaC — the Ansible `dev_node` role is the SSOT** — so onboarding a future collaborator is reproducible by construction, not a manual ritual.

A first-class DX capability rides on the existing stack: **port-to-subdomain with OIDC** — Traefik + Authelia ForwardAuth + a `*.dev.kubelab.live` wildcard route any local port on ace2 (`<port>.dev.kubelab.live`) behind Authelia. (The common "nginx + Google OAuth" recipe, implemented natively.)

### D2 — Dev-flow model: three loops, fit-for-purpose (not a ladder)

ace2 is **not** a K8s cluster; ace1 is the K3s staging node. "Developing on ace2" relocates the inner loop there — it does not replace the cluster.

| Loop | Where | What it validates | Stance |
|------|-------|-------------------|--------|
| **Inner (fast)** | ace2, no cluster | unit + integration + `docker compose` stacks | Keep. This is "local", relocated — it does not lose meaning. ~80% of feedback. |
| **Cluster (fidelity)** | ace1 shared staging, `make deploy-k8s ENV=staging` | real manifests, Traefik, OIDC, e2e | The pre-merge gate. [ADR-037](adr-037-environment-promotion-strategy.md) (`selfHeal: false` on staging) already lets a feature-branch deploy persist. |
| **Throwaway (isolation)** | — | destructive / cluster-scoped / parallel | **Not built.** See reopen triggers. |

Shared staging is the default because it has **maximum fidelity** (it *is* the real edge path). No per-feature namespaces, no vcluster, no k3d now — for a solo operator the shared `kubelab` namespace + `selfHeal: false` is sufficient, and per-feature isolation would require overlay templating + per-namespace DNS (the manifests hardcode `*.staging.kubelab.live`) for value that does not yet exist.

### D3 — Security posture: proportional to agent autonomy; blast radius contained by construction

The VPN (Headscale/Tailscale) is the **perimeter** (necessary, not sufficient). The dev-node's new risks are credential concentration and a new actor — agents with write access. Controls scale with how autonomously the agents act, not with "it is a server":

- **Always, by construction:** prod credentials **never** touch the dev-node — staging-scoped SOPS key + staging kubeconfig only; prod deploys via Argo from the hub ([ADR-023](adr-023-hub-spoke-multicloud-gitops.md)). Capability scoping via **Bitwarden-over-API** (secrets fetched on unlock, not stored at rest; the dev-node identity unlocks staging-only). The crown jewel becomes the BW session → short auto-lock TTL. A compromised dev-node **cannot reach prod**.
- **Self-driving (now):** laptop-grade hygiene — SSH key-only (already hardened), firewall bound to the Tailscale interface. Full-disk encryption (LUKS) is optional given few long-lived keys at rest with BW.
- **Autonomous agents (deferred, trigger-gated):** a host-level policy jail (AgentJail / jail-ai class — deterministic default-deny tool-call interception) + a human-approval channel (HumanLayer-style `request_permission` MCP, native to Claude Code via `permission_prompt_tool`). The `NOPASSWD` sudo fleet convention is **reversed for the agent user** (no sudo / password sudo, separated from the Ansible provisioning user). Note: the K8s Agent Sandbox is already vendored at `infra/k8s/cluster/agent-sandbox/` — host-level vs K8s-native agent isolation is a deferred sub-decision.

### D4 — Migration: decouple additive from subtractive

- **PR-1 (additive, low-risk, reversible):** the `dev_node` Ansible role (tmux + tmux-resurrect, neovim, node/go/python, gh, dotfiles, workspace skeleton, `dev-session.sh`) + Traefik/Authelia wildcard dev routing + BW capability scoping. **ace2 keeps Ollama running alongside** (12GB holds both; on-demand `keep_alive` does not consume when idle).
- **PR-2 (subtractive, deliberate, its own change):** retire Ollama via the full multi-SSOT sweep — `apps.services.ai.ollama.*` (common.yaml), `provision-ace2.yml` + `ace2_services` role, `infra/k8s/base/external/ollama.yaml`, prod overlay `ollama-throttle.yaml` + `api-key-ollama` middleware, toolkit `SECRET_CATALOG`/`MIDDLEWARE_CATALOG`/`SERVICES_AI`, DNS (`deploy-dns.yml`, `provision-rpi4.yml`), homepage `custom.js` — and amend [ADR-028](adr-028-operational-topology.md) + [ADR-029](adr-029-intelligence-layer.md). Fold in the two pending `CLAUDE.md` doc-drift fixes (Ollama-on-Beelink gotcha, errors-manual-pin gotcha).

PR-1 delivers the value at zero risk and does not require Ollama gone; PR-2 reclaims RAM/clarity deliberately when wanted.

### D5 — ace2 stays on-demand

The dev-node is an **interactive** CDE — powered when working. Unattended 24/7 autonomous agents are a **separate capability** that, per [ADR-028](adr-028-operational-topology.md)'s "would I need this at 3 AM?" doctrine, belongs on the **always-on tier (VPS / aws1)** and is gated behind D3's autonomous-agent layer. This is **not** a reason to reclassify ace2 to always-on.

### D6 — Housekeeping is codified, not disciplined

A long-lived dev/build host accumulates orphans, and on-demand power-off does **not** reclaim disk (the disk persists across power cycles). Housekeeping therefore ships as part of the `dev_node` role — scheduled `systemd` timers with size caps, never manual discipline (same principle as "push-before-shutdown is automation, not willpower"):

- `docker system prune` + `docker buildx prune --keep-storage=<cap>` (build cache is the fastest-growing offender on a build box).
- git: prune branches gone on remote (the `clean_gone` pattern), `git worktree prune`, periodic `gc`.
- agent workspaces (`~/workspaces/*-agent/`) are re-clonable → a reset/refresh script; nothing irreplaceable lives only there.
- language caches (Go build/mod, npm, pip/`.venv`) pruned or size-capped.
- a **disk-usage threshold alert** via the existing Glances + notify stack (apprise / NOTIFY-001), so the box warns *before* it fills.

The orphan surface is bounded to the dev-node's **local disk**: because D2 uses the shared `kubelab` namespace (no per-feature namespaces), feature-branch deploys to staging **overwrite in place** (same resource names) rather than accumulate — the cluster does not collect orphans from this workflow.

## Options Considered

| Option | Verdict | Reason |
|--------|---------|--------|
| Node role swap (ace1 ↔ ace2, or repurpose RPi4 for K3s) | Rejected | RPi4 (ARM64 + SD-card I/O + 2 interfaces) cannot be K3s staging; ace1 (x86 + NVMe) must stay staging. Topology is sound. |
| Per-feature K8s namespaces on ace1 | Rejected (now) | Manifests hardcode `kubelab` ns + `*.staging.kubelab.live`; multi-ns needs overlay templating + per-ns DNS. Over-engineering for a solo operator; revisit with collaborators (VPNACL-001). |
| vcluster / virtual clusters now | Deferred | Isolation value only materializes with concurrent agents, and a vcluster has *lower* edge-path parity than shared staging. Reopen trigger below. |
| microVM / gVisor isolation (E2B, Kata) | Rejected | That class is for *untrusted* code execution; dev-node agents are semi-trusted doing dev work. Host-level jail is the right fit; microVM is solving a problem we do not have. |
| Make ace2 always-on for unattended agents | Rejected | Couples 24/7 cost + ADR-028 violation + mandatory heavy autonomy stack. Unattended work belongs on the always-on tier (D5). |
| Big-bang PR (add dev-node + remove Ollama together) | Rejected | Couples a risky multi-SSOT subtractive sweep to a safe additive change. Decoupled in D4. |

## Consequences

**Positive:** a missing operational tier (dev-node) is unlocked; the dev env is reproducible IaC (team-ready onboarding); ace2's idle 12GB is used; the documented multi-workstation access pain is solved; blast radius to prod is capped by construction; ANSIBLE-021 (tmux) gets a concrete host.

**Negative:** ace2 now concentrates dev tooling + (scoped) credentials — a new asset to maintain and harden; PR-2 is a non-trivial multi-SSOT sweep; two `CLAUDE.md` gotchas remain pending until PR-2 folds them; the dev-node introduces a new actor (agents) whose autonomy must be governed as it grows.

**Neutral:** Ollama is retired from ace2 — local CPU inference is deferred until a GPU node exists; OpenRouter covers inference in the interim. ADR-028 and ADR-029 are amended, not superseded.

## Triggers to Reopen (deferred sub-decisions)

- **vcluster / per-workspace clusters** — when ≥2 agents need concurrent *cluster runtime* (not just parallel editing). Until then, agents take turns on shared staging.
- **Host-level jail vs K8s-native Agent Sandbox** — when unattended autonomous agents are introduced (D3 peldaño-2). The vendored `agent-sandbox` makes this a live fork.
- **Always-on dev tier** — if unattended 24/7 agents become a requirement → the workload goes to VPS / aws1, not a reclassified ace2 (D5).
- **VPNACL-001 mesh segmentation** — prioritize when the dev-node holds more credentials / runs more agents; least-privilege *within* the mesh (the VPN perimeter is not enough).

## References

- Issue: [#809](https://github.com/mlorentedev/kubelab/issues/809) — Repurpose ace2 from LLM compute to centralized dev-node
- [ADR-028](adr-028-operational-topology.md) — Operational topology (amended: ace2 reclassification)
- [ADR-029](adr-029-intelligence-layer.md) — Intelligence layer (amended: local inference placement)
- [ADR-037](adr-037-environment-promotion-strategy.md) — Environment promotion (staging `selfHeal: false`)
- [ADR-023](adr-023-hub-spoke-multicloud-gitops.md) — Hub-and-spoke GitOps (prod via Argo from hub)
- [ADR-052](adr-052-cluster-access-transport.md) — Cluster-access transport (ts-bridge mesh)
- `docs/runbooks/non-admin-workstation-access.md` — multi-workstation access pain
- ANSIBLE-021 (tmux base install) · VPNACL-001 (fleet segmentation)
- Agent-safety tooling surveyed: AgentJail (`bugthesystem/agentjail`), jail-ai (`cyrinux/jail-ai`), agent-sandbox (`mattolson/agent-sandbox`), K8s Agent Sandbox (`agent-sandbox.sigs.k8s.io`), HumanLayer
