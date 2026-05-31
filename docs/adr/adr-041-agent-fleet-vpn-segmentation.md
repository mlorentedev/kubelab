---
id: adr-041-agent-fleet-vpn-segmentation
type: adr
status: active
created: "2026-05-31"
---

# ADR-041 — Agent fleet VPN segmentation: tag-based Headscale ACL

## Status

**Accepted** — 2026-05-31. Extends [ADR-013](adr-013-vpn-consolidation.md) (VPN consolidation, single control plane) and [ADR-015](adr-015-vps-k3s-migration-strategy.md) (Headscale stays outside K3s). Implementation is deferred to a follow-up spec (see Consequences → Implementation outline).

## Context

A new automation agent (`hermes`) must join the Headscale mesh, hosted on an external private cloud provider, to perform automation tasks and interact with other kubelab nodes. The operator confirmed this is the **start of a fleet** (multiple `hermes` instances, `openclaw`, etc.), not a one-off — so the decision must produce a **reusable identity + segmentation model**, not a single-node hack.

### Verified state (evidence, not memory)

- ADR-013 designed a three-user model (`kubelab`/`work`/`contractors`) + `tagOwners` + a file-based `policy.hujson` with implicit-deny. It is **`status: accepted` but was never deployed**: no `policy.hujson` exists in the repo, and `infra/ansible/roles/headscale/templates/config.yaml.j2` ships `policy.mode: file` with `policy.path: ""` → the mesh is currently **allow-all**.
- The Tailscale CIDR `100.64.0.0/10` is trusted **in bulk** by three layers: `networking.trusted_cidrs` (`common.yaml`), CrowdSec allowlist + `clientTrustedIPs` (`infra/k8s/base/services/crowdsec.yaml`), and Authelia trusted networks (`infra/k8s/overlays/prod/authelia-config/configuration.yml`). Any node on the mesh inherits this trust.
- Headscale v0.28.0 runs as a **single control plane** on the VPS (ADR-015). There is no staging Headscale → any ACL change is inherently production.
- Current real mesh flows that MUST be preserved: admin (workstation) → all nodes (SSH/kubectl/HTTP); ArgoCD hub (aws1) ↔ spoke K3s API (`:6443`); rpi4 subnet route (`172.16.1.0/24`); intra-K3s; monitoring.

### Verified Headscale v0.28 ACL semantics (multi-reference audit, N=3)

Audited against Headscale v0.28 docs, Tailscale upstream ACL/tags docs, and Tailscale's official CI/CD ACL examples — load-bearing claims confirmed by two independent sources:

1. **Deny-by-default flip.** With no `acls` (or `policy.path: ""`) the mesh is allow-all. The moment a **non-empty `acls` array** is loaded it switches to **implicit-deny** — every existing flow must be explicitly enumerated or it breaks.
2. **A tag REPLACES the user identity for ACL evaluation.** A node carrying `tag:hermes` is no longer matched by the user that registered it ("When using ACLs the User borders are no longer applied"). ACL rules are written against `tag:hermes`, never against the registering user. → **tags, not users, are the correct ACL primitive for agents** (service-account semantics).
3. **`tagOwners` is mandatory** to mint a tag (gates who may assign a privileged identity); owners may be users, groups, or other tags.
4. **Offline validation exists.** `headscale policy check --file <f>` validates a policy WITHOUT applying it, and a `tests` block (assertions of allow/deny reachability) is evaluated on `check`/`set`/reload. This neutralizes most of the single-control-plane risk: the policy is validated and asserted before it touches the live mesh.
5. **Reload, not restart.** File-mode policy reloads via `systemctl reload headscale` / SIGHUP — no container restart, no downtime, existing sessions untouched.
6. **The `ssh` ACL block gates Tailscale SSH, NOT OpenSSH/sshd.** kubelab uses plain sshd → admin→agent SSH is gated by an `acls` rule (`dst: ["tag:hermes:22"]`), not the `ssh` block.
7. **Subnet routes are governed by explicit CIDR `dst` rules** (not `autogroup:internet`). Under deny-by-default, rpi4's `172.16.1.0/24` reachability breaks unless explicitly allowed.
8. **Tagging disables node-key expiry by default** — good for long-lived agents, but credential rotation must be planned explicitly (no automatic expiry).
9. **Headscale-specific divergences:** `autogroup:self` is experimental (avoid); use legacy `acls` not `grants`; file-mode HuJSON is git-versionable (fits IaC-first); reload must be triggered by IaC.

## Constraints

| # | Constraint | Origin |
|---|---|---|
| C1 | Zero breakage of current mesh flows (admin→all, ArgoCD hub↔spokes, rpi4 subnet route, intra-K3s, monitoring) | blast-radius, single control plane |
| C2 | Least-privilege for agents: agent reaches only explicitly-needed dsts; agent not broadly reachable; agent↔agent denied unless needed | external/low-trust agent |
| C3 | Reusable for a fleet: adding an agent = mint a tag + 1–2 ACL lines, no redesign | operator: "start of a fleet" |
| C4 | IaC-first: HuJSON versioned in repo, validated by `headscale policy check` in CI, reloaded via Ansible (never edited manually on the VPS) | project IaC-first principle |
| C5 | Safe rollout on a single control plane: validate offline (`policy check` + `tests` asserting allow AND deny) before reload; permissive-first migration | ADR-015 (single Headscale, no staging) |
| C6 | Reconcile cross-layer trust: the ACL is network-layer, but agents remain inside `100.64.0.0/10`, which Authelia/CrowdSec trust in bulk | verified cross-layer gap |

## Options considered

- **A — Dedicated `agents` user (key custody) + per-type tag (`tag:hermes`, `tag:openclaw`, …) + file-mode HuJSON ACL, deny-by-default with all existing flows enumerated.** Tags are the ACL identity (least-privilege per agent type); the `agents` user exists only to own/revoke preauth keys. Matches Tailscale's "deployment identity owns workload tags" pattern.
- **B — Single `tag:agent` for all agents.** Simpler, but `hermes` and `openclaw` share permissions — violates C2 (per-type least-privilege) and C3 (future granularity).
- **C — Separate user, NO ACL, host-firewall only.** Identity isolation without network enforcement — mesh stays allow-all (violates C2/C3); rejected once the operator chose full segmentation.
- **D — DB-mode policy (`headscale policy set`).** Policy lives in Headscale's DB, not git — violates C4 (IaC-first / git-versioned).
- **E — `grants`-based policy.** Headscale v0.28 docs are written around legacy `acls`; `grants` support is unverified — violates C5 (don't ship unverified semantics on a single prod control plane).

## Decision

Adopt **Option A**.

1. **Identity model.** Register fleet agents under a dedicated Headscale user `agents` (custody/revocation of preauth keys only). Each agent advertises a per-type tag (`tag:hermes`, `tag:openclaw`, …) via `--advertise-tags` on `tailscale up`. ACL rules are written exclusively against tags. `tagOwners` for all agent tags = the `kubelab` admin user.
2. **Policy storage.** File-mode HuJSON at a repo path, deployed by the `headscale` Ansible role (parameterize `policy.path`, mount the file, trigger `systemctl reload headscale` on change). Never edited manually on the VPS.
3. **Segmentation shape.** Deny-by-default. Agents are `src` to a narrow, explicitly-enumerated set of `dst` (per-agent-type). Agents are reachable only by admin on `:22` (`dst: tag:hermes:22` via `acls`, since kubelab uses sshd). Agent↔agent is denied unless a specific need is enumerated. The concrete per-agent dst matrix starts **closed** and is enumerated in the implementation spec as needs arise.
4. **Rollout (C5).** Permissive-first: first author a policy that **replicates the current allow-all** for existing identities PLUS the agent tag rules, validate with `headscale policy check` and a `tests` block asserting both the preserved flows and the agent restrictions, reload, observe; only then tighten existing flows toward least-privilege in a second iteration. This avoids a big-bang deny-by-default that could sever the live mesh.
5. **Cross-layer trust (C6).** The Headscale ACL is the **primary enforcement gate**: an agent only reaches what the ACL allows, so any service where Authelia-bypass / CrowdSec-whitelist would be unacceptable MUST be made unreachable-by-ACL from agent tags. The bulk `100.64.0.0/10` app-layer trust is retained for now (carving a sub-CIDR is infeasible — Headscale assigns IPs sequentially from the pool, not segregated by tag). A per-service review of "should agents bypass app-layer auth here?" is a tracked consequence, not a blocker.

## Rationale

- Tags are the only ACL primitive that survives Headscale's "tag replaces user" semantic and Tailscale's explicit guidance to model non-human machines as tagged service accounts — making the model identity-stable and fleet-scalable (C3).
- `headscale policy check` + the `tests` block + reload-not-restart collapse the single-control-plane risk that originally made this change scary: the policy is proven offline and applied without downtime (C5).
- File-mode HuJSON keeps the policy in git, reviewable and CI-validatable (C4), consistent with the project's IaC-first principle and ADR-013's original file-based intent.
- Permissive-first respects C1: the mesh is never exposed to an untested deny-by-default flip.

## Consequences

### Positive
- First real network segmentation in the mesh; closes the ADR-013 design↔deploy gap.
- Adding a fleet agent becomes a 2-step, low-risk operation (mint tag + ACL lines).
- Policy is git-versioned, CI-validated, and reloadable without downtime.

### Negative / costs
- Introduces deny-by-default to a previously open mesh — requires careful, complete enumeration of existing flows (mitigated by permissive-first + `tests`).
- Tagged agents have node-key expiry disabled → explicit credential-rotation policy needed.
- Cross-layer trust (C6) is only partially resolved: app-layer blanket trust remains; the ACL must carry the segmentation burden until a per-service auth review lands.

### Neutral
- The `headscale` Ansible role gains a `policy.path` parameter + a policy file + a reload handler.
- `headscale nodes tag` / `preauthkeys --tags` exact flags must be confirmed on the running v0.28 install before the spec locks (flagged [UNCERTAIN] in the audit).

### Implementation outline (deferred to spec)
1. Parameterize `headscale` role: expose `headscale_policy_path`, mount HuJSON, add reload handler.
2. Author `policy.hujson`: permissive-first baseline (preserve all current flows) + `agents`/tag definitions + `tests` block.
3. Wire `headscale policy check` into CI as a gate.
4. Onboard `hermes`: create `agents` user, mint preauth key, `tailscale up --advertise-tags tag:hermes`; record IP in `networking.nodes` SSOT.
5. Second iteration: tighten existing flows toward least-privilege; per-service C6 review.

## References

- [ADR-013](adr-013-vpn-consolidation.md) — VPN consolidation, three-user model (extended here).
- [ADR-015](adr-015-vps-k3s-migration-strategy.md) — Headscale single control plane outside K3s.
- [ADR-010](adr-010-headscale-over-tailscale-cloud.md) — self-hosted Headscale.
- Headscale v0.28 ACLs: https://headscale.net/0.28.0/ref/acls/ · routes: https://headscale.net/0.28.0/ref/routes/ · FAQ (`policy check`): https://headscale.net/stable/about/faq/
- Tailscale tags: https://tailscale.com/docs/features/tags · policy syntax: https://tailscale.com/docs/reference/syntax/policy-file · ACL examples: https://tailscale.com/docs/reference/examples/acls
