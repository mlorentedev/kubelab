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
4. **Offline validation — version-dependent (CORRECTED).** `headscale policy check --file <f>` exists since v0.26.0, but on the running **v0.28.0 it is SYNTAX-ONLY** (parse/structure validation). The `tests` block — runtime assertions of allow/deny reachability — is **evaluated only from v0.29.0**, NOT on v0.28.0 (`tests` introduced and enforced in the v0.29.0 changelog; `policy check` in #2553/v0.26.0). So on the current control plane, `policy check` does NOT prove reachability. Rollout safety must therefore come from permissive-first + external active probing (Decision §4), with the in-engine `tests` block available only after a v0.29.0 upgrade. _(This corrects an error in the original draft that assumed `tests` ran on v0.28; surfaced by adversarial review on PR #234.)_
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
| C5 | Safe rollout on a single control plane: `policy check` SYNTAX gate (v0.28) + permissive-first + external active probe of preserved flows after reload (auto-revert on failure); in-engine `tests` assertions only after a v0.29.0 upgrade | ADR-015 (single Headscale, no staging) |
| C6 | Reconcile cross-layer trust: the ACL is network-layer, but agents remain inside `100.64.0.0/10`, which Authelia/CrowdSec trust in bulk | verified cross-layer gap |

## Options considered

- **A — Dedicated `agents` user (key custody) + per-type tag (`tag:hermes`, `tag:openclaw`, …) + file-mode HuJSON ACL, deny-by-default with all existing flows enumerated.** Tags are the ACL identity (least-privilege per agent type); the `agents` user exists only to own/revoke preauth keys. Matches Tailscale's "deployment identity owns workload tags" pattern.
- **B — Single `tag:agent` for all agents.** Simpler, but `hermes` and `openclaw` share permissions — violates C2 (per-type least-privilege) and C3 (future granularity).
- **C — Separate user, NO ACL, host-firewall only.** Identity isolation without network enforcement — mesh stays allow-all (violates C2/C3); rejected once the operator chose full segmentation.
- **D — DB-mode policy (`headscale policy set`).** Policy lives in Headscale's DB, not git — violates C4 (IaC-first / git-versioned).
- **E — `grants`-based policy.** Headscale v0.28 docs are written around legacy `acls`; `grants` support is unverified — violates C5 (don't ship unverified semantics on a single prod control plane).

## Decision

Adopt **Option A**.

> **Implementation corrections (2026-05-31, from spec VPNACL-001 — two details below were wrong/insufficient and corrected during the first real onboarding):**
> 1. **`tagOwners` must include the registering user `agents@`** (item 1 below says "kubelab admin" only). Headscale rejects a node/key carrying a tag whose user is not a `tagOwner`, so the agent join fails (`"tag not permitted by auth key"`). Fix: `tagOwners["tag:hermes"] = ["kubelab@", "agents@"]` (keep `kubelab@` for manual admin tagging). Also: agents are tagged by the **key's embedded `--tags`** — do **NOT** pass `tailscale up --advertise-tags` (item 1); combining both triggers the advertise-path validation and fails.
> 2. **Reload is `docker kill --signal=HUP headscale`**, not `systemctl reload` (items 2–3): Headscale runs in Docker Compose (no systemd). A propagation window after reload means the verification probe must retry.
>
> Full procedure + gotchas: [`docs/runbooks/onboard-vpn-fleet-agent.md`](../runbooks/onboard-vpn-fleet-agent.md).

1. **Identity model.** Register fleet agents under a dedicated Headscale user `agents` (custody/revocation of preauth keys only). Each agent advertises a per-type tag (`tag:hermes`, `tag:openclaw`, …) via `--advertise-tags` on `tailscale up`. ACL rules are written exclusively against tags. `tagOwners` for all agent tags = the `kubelab` admin user.
2. **Policy storage.** File-mode HuJSON at a repo path, deployed by the `headscale` Ansible role (parameterize `policy.path`, mount the file, trigger `systemctl reload headscale` on change). Never edited manually on the VPS.
3. **Segmentation shape.** Deny-by-default. Agents are `src` to a narrow, explicitly-enumerated set of `dst` (per-agent-type). Agents are reachable only by admin on `:22` (`dst: tag:hermes:22` via `acls`, since kubelab uses sshd). Agent↔agent is denied unless a specific need is enumerated. The concrete per-agent dst matrix starts **closed** and is enumerated in the implementation spec as needs arise.
4. **Rollout (C5) — safe on v0.28 without the `tests` block.**
   - (a) **CI gate:** `headscale policy check` for SYNTAX (v0.28-available).
   - (b) **Permissive-first:** the first deployed policy replicates the current allow-all for existing identities PLUS the agent tag rules — by construction it cannot sever an existing flow (everything is still accepted).
   - (c) **External active verification:** immediately after each `systemctl reload`, an Ansible/toolkit probe asserts every preserved flow (admin→nodes SSH, ArgoCD hub→spoke `:6443`, rpi4 route, intra-K3s, monitoring) actually works; on failure, auto-revert by reloading the prior known-good policy. Reload is non-disruptive and seconds-fast, so the deny-by-default flip is **reversible**, not a one-way door.
   - (d) Only after the permissive baseline is stable does a second iteration tighten existing flows toward least-privilege — that is where deny risk is real and the probe is load-bearing.
   - (e) **Recommended end-state: upgrade Headscale to v0.29.0** before the tightening iteration, to gain in-engine `tests` (committed allow/deny assertions enforced at apply-time on a single control plane). Author the external-probe assertions in a form that migrates into the policy `tests` block on upgrade.
5. **Cross-layer trust (C6) — zero-trust per-service identity.** Network position does NOT grant authorization. Fleet agents authenticate to each service with their **own scoped credential** — SSH keypair for nodes; scoped API token / service account for Gitea, Grafana, Argo CD, MinIO; OIDC client-credentials for OIDC-protected APIs — and target token-authenticated API endpoints rather than the human ForwardAuth web routes, so the Authelia CIDR-bypass is **moot** for the agent. This matches the project's dominant pattern (ArgoCD hub→spoke scoped RBAC tokens; Ollama API-key middleware per ADR-035), not the Authelia network-trust convenience exception. The bulk `100.64.0.0/10` trust in `trusted_cidrs`/CrowdSec/Authelia is **left intact for human convenience on web UIs** — agents simply do not depend on it. Per-agent, per-service credentials are provisioned and rotated through the toolkit + SOPS like other secrets. Net: the Headscale ACL governs **reachability**; the agent's own identity governs **authorization**.

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
- Introduces deny-by-default to a previously open mesh — requires careful, complete enumeration of existing flows (mitigated by permissive-first + external probing on v0.28; in-engine `tests` only after a v0.29 upgrade).
- Rollout safety on v0.28 depends on an **external probe harness** (the in-engine `tests` block needs a Headscale v0.29.0 upgrade, itself a control-plane operation).
- Tagged agents have node-key expiry disabled → explicit credential-rotation policy needed.
- Zero-trust (C6) requires provisioning and rotating a **scoped credential per service per agent** — more setup than inheriting network trust; codified via toolkit + SOPS.

### Neutral
- The `headscale` Ansible role gains a `policy.path` parameter + a policy file + a reload handler.
- `headscale nodes tag` / `preauthkeys --tags` exact flags must be confirmed on the running v0.28 install before the spec locks (flagged [UNCERTAIN] in the audit).

### Implementation outline (deferred to spec)
1. Parameterize `headscale` role: expose `headscale_policy_path`, mount HuJSON, add reload handler.
2. Author `policy.hujson`: permissive-first baseline (preserve all current flows) + `agents`/tag definitions + an external connectivity-probe harness (assertions authored to migrate into a `tests` block on the v0.29 upgrade).
3. Wire `headscale policy check` (syntax) into CI as a gate.
4. Onboard `hermes`: create `agents` user, mint preauth key, `tailscale up --advertise-tags tag:hermes`; record IP in `networking.nodes` SSOT; provision its per-service scoped credentials (SSH key, API tokens) via toolkit + SOPS (C6 zero-trust).
5. Upgrade Headscale to v0.29.0 (gains in-engine `tests`) before the tightening iteration.
6. Second iteration: tighten existing flows toward least-privilege with `tests`-backed assertions; per-service C6 audit.

## References

- [ADR-013](adr-013-vpn-consolidation.md) — VPN consolidation, three-user model (extended here).
- [ADR-015](adr-015-vps-k3s-migration-strategy.md) — Headscale single control plane outside K3s.
- [ADR-010](adr-010-headscale-over-tailscale-cloud.md) — self-hosted Headscale.
- Headscale v0.28 ACLs: https://headscale.net/0.28.0/ref/acls/ · routes: https://headscale.net/0.28.0/ref/routes/ · FAQ (`policy check`): https://headscale.net/stable/about/faq/
- Headscale CHANGELOG (version boundaries: `policy check` v0.26.0 syntax-only; `tests` block evaluation v0.29.0): https://github.com/juanfont/headscale/blob/main/CHANGELOG.md
- Tailscale tags: https://tailscale.com/docs/features/tags · policy syntax: https://tailscale.com/docs/reference/syntax/policy-file · ACL examples: https://tailscale.com/docs/reference/examples/acls
