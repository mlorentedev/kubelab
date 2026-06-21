---
id: "adr-052"
type: adr
status: accepted
owner: manu
date: "2026-06-21"
issue: "kubelab#723"
tags: [architecture, decision, kubeconfig, transport, ts-bridge, tailscale, headscale, mesh, onboarding, non-admin, cluster-access]
depends_on: [adr-047-cluster-wide-bootstrap-ssot, adr-036-shared-infra-namespace, adr-025-magicdns-internal-naming, adr-023-hub-spoke-multicloud-gitops, adr-014-secrets-management-strategy, adr-028-operational-topology, adr-030-self-hosted-ci-runner]
created: "2026-06-21"
---

# ADR-052: Cluster access transport — operate K3s from any machine (incl. non-mesh / non-admin)

## Status

Accepted — 2026-06-21. Establishes the convention for **how an operator machine obtains and uses a kubeconfig** for each kubelab cluster (staging/prod/hub), so deploy/apply works identically on the home LAN, off-network over the VPN, from CI, and from a corporate **non-admin box with no native Tailscale**. Scopes the implementation of #723 (`fetch-kubeconfig`) and the follow-on `connect` helper. **Owner-bootstrap only** — per-user collaborator access is explicitly deferred (D5).

## Context

Operating any cluster needs a kubeconfig whose `server:` endpoint is *reachable from the machine running `kubectl`*. The repo's only precedent is `make fetch-kubeconfig-hub`: an inline `ssh … sudo cat /etc/rancher/k3s/k3s.yaml | sed 's/127.0.0.1/aws1.kubelab.internal/'` that rewrites the server to the node's **MagicDNS** name. That convention silently assumes the consuming machine has **native Tailscale** (a TUN device routing `100.64.0.0/10` + MagicDNS resolution).

The primary operator workstation (EGW-LEN029) breaks that assumption: it is a **corporate, non-admin** box that cannot install Tailscale (no TUN, no admin). Its only mesh transport is **ts-bridge** — a userspace `tsnet` bridge (no TUN) that forwards a **local TCP port** to a mesh target. Because `tsnet` installs no system route, a separate process (`kubectl`) can reach a mesh service **only via a forwarded `127.0.0.1:<port>`**, never via `100.64.0.11` or `ace1.kubelab.internal`. So "rewrite server → MagicDNS" produces a kubeconfig that does not work on this machine.

Requirement (clarified): operate **from anywhere**, on-LAN *and* off-network. Off-network the home-LAN SSH jump (`rpi4-lan`) is unreachable; only the mesh (public Headscale control-plane `vpn.kubelab.live` + public VPS bastion) reaches staging/hub. So the **mesh is the universal transport**; LAN and prod's public IP are opportunistic fast paths.

## Reference audit (Regla del 3, ADR-015)

This decision governs **cross-machine reuse** (operator laptops, a corporate non-admin box, CI runners) → the gate fires.

| Dimension | R1 · repo precedent | R2 · k3s/kubectl mechanics | R3 · ts-bridge / non-admin reality |
|---|---|---|---|
| Get kubeconfig | `fetch-kubeconfig-hub`: ssh+sed, `server`→MagicDNS; `_K8S_KUBECONFIG_PATTERN` = `~/.kube/kubelab-{env}-config`; addresses are SSOT in `common.yaml` | k3s server cert SAN includes `127.0.0.1`, `localhost`, node IP + `tls-san` ⇒ `server: https://127.0.0.1:<port>` validates TLS | userspace `tsnet` has **no TUN** ⇒ only `127.0.0.1:<port>` port-forwards are reachable by `kubectl` |
| Use kubeconfig | assumes native Tailscale (MagicDNS) on the consumer | `kubectl` `cluster.proxy-url` supports `socks5://` ⇒ a SOCKS proxy can keep real server names | ts-bridge forwards one target today; multi-target / SOCKS are open (ts-bridge #186 / new) |
| Address source | `networking.*` in `common.yaml` (never hardcode IPs) | n/a | two separate meshes; prod VPS apiserver reachable by public IP (break-glass) |

### Divergence log

- **Intersection (reused):** the hub mechanic — fetch `k3s.yaml`, rewrite `server`, save to `~/.kube/kubelab-{env}-config` — is sound and kept.
- **Divergence (the fix):** the **server value** must be transport-agnostic, not MagicDNS. `https://127.0.0.1:<fixed-per-env-port>` is a **superset** convention: it works on userspace/non-admin boxes (the hard case) *and* on native-Tailscale machines and CI (a trivial local forward, or the direct fast path). MagicDNS-in-`server` is Linux/native-TS-only — effectively the same portability trap as the `.sops.yaml` basename lesson.
- **Strategic finding:** making the kubeconfig name a **stable local endpoint** and the reachability a **swappable transport** decouples two things the hub target fused — which is what lets one convention serve every machine.

## Constraints

| # | Constraint | Origin |
|---|---|---|
| C1 | kubeconfig embeds cluster-admin **client certs** (secret) → never committed; fetched per machine | ADR-014 |
| C2 | consumer may have **no native Tailscale / no admin** (ts-bridge userspace) → transport must not assume a system mesh route | non-admin workstation reality |
| C3 | every cluster/network address is **SSOT in `common.yaml`**, never hardcoded in code/manifests | repo rule (CLAUDE.md) |
| C4 | must work **on and off** the home network → mesh is the universal path; LAN/public are fast paths | this ADR's requirement |
| C5 | **no inline scripts in the Makefile** → logic in the toolkit, target delegates | repo rule (CLAUDE.md) |

## Options Considered

**kubeconfig `server:` convention**

| Option | Verdict |
|---|---|
| `https://127.0.0.1:<fixed-per-env-port>` + pluggable local forward | **Chosen** — transport-agnostic; TLS valid via k3s `127.0.0.1` SAN; works on every machine |
| MagicDNS / mesh name (the hub pattern) | Rejected for general use — requires native Tailscale on the consumer; breaks on userspace/non-admin |
| `proxy-url: socks5://127.0.0.1:<port>` + real server name | **Deferred** — cleanest for multi-cluster (one proxy, real names), but needs ts-bridge to expose SOCKS; adopt later as a kubeconfig-field swap, no redesign |
| Public IP for every cluster | Rejected — only prod exposes a public apiserver; exposing staging/hub publicly is unacceptable surface |

**transport selection**

| Option | Verdict |
|---|---|
| Data-driven, default = mesh, with detected fast paths (prod→public IP; staging→LAN `ssh -L` when `rpi4-lan` answers; else ts-bridge) | **Chosen** — universal by default, cheap when possible, declared in SSOT |
| Hardcode env→transport in Python branches | Rejected — adding a cluster = code edit; violates the SSOT rule (C3) |
| Always ts-bridge | Rejected — ignores prod's public path and the LAN fast path, and makes ts-bridge a SPOF where it is avoidable |

## Decision

- **D1 — Transport-agnostic kubeconfig.** Every fetched kubeconfig uses `server: https://127.0.0.1:<fixed-per-env-port>` (e.g. staging `16443`, prod `16444`, hub `16445` — declared in SSOT, not magic numbers). The **transport** maps that local port to the env's apiserver; the kubeconfig never encodes *how*. TLS verifies against the k3s cert's `127.0.0.1` SAN. The SOCKS variant (`proxy-url` + real server name) is a future optimization adoptable without breaking this contract.
- **D2 — Per-cluster access metadata is SSOT in `common.yaml`.** A declarative block (per cluster: apiserver node ref, SSH alias, mesh DNS name, fixed local port, optional public endpoint) drives both fetch and connect. Adding/altering a cluster is a YAML edit; the toolkit stays data-driven (no env→transport branches).
- **D3 — Transport is capability-selected, default mesh.** Resolution order per cluster: declared **public endpoint** (prod, direct, no tunnel) → **LAN `ssh -L`** when the LAN jump answers (home fast path) → **ts-bridge** (universal mesh, on/off-network). CI (native Tailscale, ADR-030) may take the direct mesh path; the `127.0.0.1` convention still holds if it runs `connect`.
- **D4 — One unified fetch command.** `toolkit infra k8s fetch-kubeconfig --env {staging,prod,hub}` (Makefile target delegates) **retires** the bespoke inline `fetch-kubeconfig-hub` target — one pattern, no inline Makefile shell (C5).
- **D5 — Owner-bootstrap only; collaborator access is a separate axis.** This ADR covers the single operator fetching an **admin** kubeconfig and tunneling to it. Onboarding *other people* by copying admin client-certs has **no per-user identity and no revocation** — wrong by design. Per-user access is deferred to a separate spec built on **Authelia OIDC + kube-apiserver RBAC + Headscale ACLs (VPNACL-001)**, not in scope here.

## Consequences

**Positive:** one convention works on the non-admin box, native-Tailscale laptops, and CI; the kubeconfig is stable while the transport is swappable; cluster access becomes data-driven (SSOT) and the inline hub target's smell is retired; the design names the owner-vs-collaborator split instead of conflating it.

**Negative:** using a cluster now requires a running transport (`connect`) for staging/hub, so ts-bridge lifecycle becomes load-bearing — it needs robust start/teardown/health, not a bare subprocess. Simultaneous multi-cluster `connect` depends on **ts-bridge multi-target (#186)**; the optional SOCKS variant needs a further ts-bridge feature. Both are tracked in the ts-bridge repo.

**Neutral:** single-cluster ops work **today** with ts-bridge single-target, so the immediate staging unblock (#724 → CONSOLE-002 PR-1b) does not wait on #186. The agent/automation shell cannot do passphrase SSH non-interactively — the toolkit is the deliverable; the human (or a mesh-native CI node with an ssh-agent) runs the interactive bootstrap.

## Implementation / backlog

- **Phase 1 (now — unblocks CONSOLE-002):** this ADR + **#723** `fetch-kubeconfig --env {staging,prod,hub}` (data-driven from D2 SSOT, server per D1, unit-tested) + per-cluster SSOT block in `common.yaml`; then `apply-secrets` to staging via single-target ts-bridge → **#724**.
- **Phase 2 (tracked):** `toolkit infra k8s connect --env` with real ts-bridge lifecycle + healthcheck; owner-focused onboarding runbook (`docs/runbooks/operate-from-new-workstation.md`); **ts-bridge #186** (multi-target) and a SOCKS ticket in the ts-bridge repo.
- **Phase 3 (separate spec):** collaborator access — Authelia OIDC + RBAC + Headscale ACLs (intersects **VPNACL-001**).

## References

- [[adr-047-cluster-wide-bootstrap-ssot]] (bootstrap SSOT), [[adr-036-shared-infra-namespace]] (`common.yaml` SSOT), [[adr-025-magicdns-internal-naming]] (MagicDNS), [[adr-023-hub-spoke-multicloud-gitops]] (hub/spoke kubeconfigs), [[adr-014-secrets-management-strategy]] (kubeconfig = secret), [[adr-028-operational-topology]] (on-demand nodes), [[adr-030-self-hosted-ci-runner]] (CI native Tailscale)
- Tickets: kubelab #723 (fetch-kubeconfig), #724 (apply postgres-secrets); ts-bridge #186 (multi-target); VPNACL-001 (fleet segmentation / ACLs)
- Lessons: `docs/lessons.md` — non-admin workstation fleet-access; SOPS basename portability (same class of "ambient-state" trap)
