---
id: "TOOL-014-k8s-connect"
type: spec
status: archived # draft | implementing | verifying | archived
created: "2026-06-21"
issue: "kubelab#731"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# TOOL-014: K8s connect — idempotent cluster-access transport

> **Naming**: file lives at `<repo>/specs/<feature-id>/proposal.md`. `<feature-id>` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #731: TOOL-014: toolkit infra k8s connect — idempotent cluster-access transport + onboarding runbook -->

Operating any kubelab cluster needs a kubeconfig whose `server:` endpoint is reachable from the machine running `kubectl`. `fetch-kubeconfig` (#723/#728) already pins every kubeconfig to `https://127.0.0.1:<fixed-per-env-port>`, but nothing maps that local port to the real apiserver yet — so `make apply-secrets` / `deploy-k8s` cannot run from the primary workstation (EGW-LEN029, corporate, non-admin, no native Tailscale), which blocks #724 (apply postgres-secrets) on the CONSOLE-002 critical path. Today reaching the cluster is an undocumented manual dance (rediscover the ts-bridge invocation, the SSH paths, which one works) that recurs every session. This codifies the transport as idempotent IaC + an onboarding runbook so the "how do I reach the cluster from this machine" discussion stops happening.

## What

Three new toolkit subcommands under a dedicated sub-noun, `toolkit infra k8s access {connect,disconnect,status} --env {staging,prod,hub}`, data-driven from the `clusters:` SSOT in `common.yaml`; delegating `make connect|disconnect|connect-status ENV=x` targets (no inline Makefile scripts; `connect-status` avoids a too-generic `make status`); and an onboarding runbook. The legacy `infra k8s status` (namespace workloads) is left untouched. Concrete outputs after this PR:

- `make connect ENV=staging` brings up a transport that maps `127.0.0.1:16443` to ace1's apiserver over the Headscale mesh (ts-bridge, userspace — works on a non-admin box), idempotently.
- `make connect ENV=prod` resolves prod's public apiserver endpoint directly (no tunnel).
- `infra k8s access status --env x` reports whether the transport is up/down and which transport was resolved; `make disconnect ENV=x` tears it down cleanly.
- After `connect`, `kubectl --kubeconfig ~/.kube/kubelab-staging-config get ns` succeeds against staging.

## Out of scope

Things this PR explicitly does NOT include. Forces a sharp boundary and prevents scope creep.

- LAN `ssh -L` fast path and the SSH layer it needs — `deployer` bastion auth, multi-key `authorized_keys`, parameterizing `AllowTcpForwarding` on rpi4. That is #719.
- ts-bridge multi-target (simultaneous multi-cluster `connect`) — ts-bridge#186; v1 keeps one transport up at a time.
- SOCKS `proxy-url` kubeconfig variant (real server names through one proxy) — a later optimization adoptable without breaking the `127.0.0.1` contract.
- Collaborator / per-user access (OIDC + kube-apiserver RBAC + Headscale ACLs) — ADR-052's collaborator axis / VPNACL-001.

## Risks / open questions

Failure modes, dependencies, and unknowns to clarify before implementation. Resolved leans are noted; the one empirical unknown is a verification step, not a code blocker.

- **Node-ref heterogeneity (RESOLVED).** `clusters.staging.node: ace1` lives under `networking.nodes.ace1`, but `prod.node: vps` and `hub.node: aws1` live at `networking.vps` / `networking.aws` (top level), not under `nodes.*`. The mesh-target resolver is position-aware — the same homelab-vs-cloud lookup the Ansible generator uses (SSOT-014a). The whole target is **derived** from the existing `clusters.<env>.node` against `networking.*`; the apiserver port defaults to 6443 in code (overridable via `clusters.<env>.apiserver_port`). Net result: **no edit to the `clusters:` block at all** — even better than adding a field, and zero new IPs anywhere.
- **ts-bridge lifecycle (RESOLVED).** ts-bridge runs in the foreground and is single-target. `connect` spawns it detached, records pid + env + local port in a statefile (idempotency + `disconnect`), and only one env's transport is up at a time (switching env tears down first). Multi-target is #186.
- **ts-bridge auth (RESOLVED).** Reuse the already-configured `~/Apps/ts-bridge/.env` credentials (`TS_AUTHKEY`, `TS_CONTROL_URL`) — ts-bridge owns its own auth SSOT; do not duplicate the Headscale preauth key into kubelab SOPS.
- **Binary discovery (RESOLVED).** Locate the ts-bridge binary via a configurable path (`TS_BRIDGE_BIN` env, else a sensible default) and fail with a clear, actionable error if absent — never a silent failure.
- **Empirical unknown (verify during implementation, not a blocker).** That ts-bridge's userspace `tsnet` reaches `ace1:6443` over Headscale from EGW-LEN029 reliably. Proven out by the staging acceptance run, not by reasoning.
- **Operator-shell constraint (accepted, from ADR-052).** Passphrase SSH (for `fetch-kubeconfig`) and ts-bridge bring-up need the operator's interactive shell / ssh-agent; the toolkit is the deliverable, the human runs the bootstrap. The agent shell cannot do it non-interactively.

## Acceptance criteria

Observable outcomes. Each must be testable.

- [ ] `make connect ENV=staging` brings up the transport idempotently and `kubectl --kubeconfig ~/.kube/kubelab-staging-config get ns` succeeds.
- [ ] Re-running `connect` when already up is a clean no-op (exit 0, detected via `access status`).
- [ ] `infra k8s access status --env x` reports up/down + the resolved transport per env; `make disconnect ENV=x` tears it down cleanly.
- [ ] No hardcoded IPs — every address resolves from `networking.*` / `clusters.*` SSOT; pure resolver/idempotency helpers unit-tested without network.
- [ ] `docs/runbooks/operate-from-new-workstation.md` lets a fresh non-admin workstation reach staging end-to-end.

## References

- Bitácora board: kubelab#731 (this spec's tracking issue; see the `issue:` frontmatter field)
- Related ADR: `docs/adr/adr-052-cluster-access-transport.md` (this is its `connect` backlog item)
- Upstream: #723 / #728 (fetch-kubeconfig — the kubeconfig side, on master); downstream consumer #724 (apply postgres-secrets, CONSOLE-002)
- Distinct scope: #719 (non-admin SSH access hardening); ts-bridge#186 (multi-target); VPNACL-001 (collaborator access)
