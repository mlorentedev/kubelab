---
id: "TOOL-015-fetch-over-transport"
type: spec
status: verifying # draft | implementing | verifying | archived
created: "2026-06-21"
issue: "kubelab#733"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# TOOL-015: fetch-kubeconfig over the transport

> Fast-follow to TOOL-014. Codifies the manual ts-bridge-to-SSH "rodeo" into
> `fetch-kubeconfig` so the kubeconfig can be obtained from a non-admin box.

## Why

<!-- from issue #733 -->

TOOL-014 (#731/#732) codified the **apiserver** transport, but `fetch-kubeconfig`
still SSHes to the node's **mesh IP on port 22**, which is **not routable from a
non-admin box with no native Tailscale**. Validated 2026-06-21 from EGW-LEN029:
`make fetch-kubeconfig ENV=staging` → `ssh ace1 → 100.64.0.11:22: Connection timed
out`. The only way to fetch from such a box today is a manual ts-bridge-to-SSH
dance documented in `operate-from-new-workstation.md`. That manual step is the
exact "undocumented recurring dance" the access work set out to eliminate — so
leaving it manual is the gap to close.

## What

`fetch-kubeconfig` works from a non-admin box with one command. When the direct
`ssh <alias>` path is unreachable, it routes the read through a **transient**
ts-bridge SSH tunnel (`<node>:22` → `127.0.0.1:<ephemeral>`), reusing TOOL-014's
mechanism. Concrete changes:

- Generalize `ts_bridge_argv` (k8s_connect) to any `host:port`, not just the apiserver.
- Extract the shared bridge lifecycle (spawn + port healthcheck + terminate) from
  `connect()` into a reusable **transient-tunnel context manager** (`try/finally`).
- `fetch_kubeconfig` resolves the node's SSH user + mesh host from the SSOT
  (`clusters.<env>` + `networking.*`, same resolver as TOOL-014), brings up the
  SSH tunnel, reads `k3s.yaml` via `ssh -p <port> <user>@127.0.0.1`, rewrites, saves.

## Out of scope

- Collaborator / per-user access (OIDC + RBAC + Headscale ACLs) — ADR-052 Phase 3 / VPNACL-001.
- ts-bridge multi-target (#186) — the SSH tunnel is a transient single instance, brought up and torn down within the fetch.
- Native-SSH path hardening (bastion `deployer`, `AllowTcpForwarding`, key-mgmt 2+3) — #719. This spec routes *around* that gap via ts-bridge, it does not fix the SSH layer.

## Risks / open questions

- **OPEN — trigger policy (resolve in /spec fill).** Always route mesh clusters
  through the bridge, or try direct `ssh <alias>` first and fall back only on a
  **routing/connect** failure? Critical: an **auth** failure (wrong/locked key)
  must NOT trigger the fallback (it would mask the real error and spin up a tunnel
  for nothing). Lean: try-direct-then-fallback, distinguishing connect-timeout
  (fall back) from auth-denied (fail loud).
- **Teardown is the failure mode.** The tunnel is transient; if the SSH/fetch
  throws, the bridge process + ephemeral Headscale node must still be cleaned up
  (`try/finally`). A leaked bridge per failed fetch is the bug to prevent.
- **known_hosts determinism.** `127.0.0.1:<ephemeral>` maps to different real hosts
  across runs/clusters → use `-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=accept-new`.
- **Reuse, don't fork.** The bridge spawn/healthcheck/terminate already exists in
  `connect()`; extract it rather than duplicating, or the two drift.
- **Interactive auth still required.** The SSH read needs the operator's ssh-agent
  (passphrase) — the toolkit is the deliverable; the human runs it (ADR-052, unchanged).

## Acceptance criteria

- [ ] `make fetch-kubeconfig ENV=staging` succeeds from a non-admin box (no native Tailscale), producing a working `~/.kube/kubelab-staging-config`; `make connect ENV=staging` + `kubectl get ns` then works end-to-end.
- [ ] **Idempotent**: re-running overwrites the same kubeconfig (0600), never appends or accumulates state.
- [ ] **Guaranteed teardown**: a forced failure mid-fetch leaves **no orphan** ts-bridge process and no lingering ephemeral Headscale node (`try/finally` verified by a test that injects a failure).
- [ ] **Deterministic known_hosts**: repeated fetches across clusters never raise "host key changed" / never write to the user's known_hosts.
- [ ] No hardcoded IPs — SSH user + host derived from `clusters`/`networking` SSOT; pure helpers (generalized argv, user/host resolution) unit-tested without network.

## References

- Bitácora board: kubelab#733
- Builds on: TOOL-014 (`specs/archive/TOOL-014-k8s-connect/` once archived; `toolkit/features/k8s_connect.py`), ADR-052 (`docs/adr/adr-052-cluster-access-transport.md`)
- Runbook to update: `docs/runbooks/operate-from-new-workstation.md` (replace the manual rodeo with the codified path)
- Distinct: #719 (non-admin SSH hardening), ts-bridge#186 (multi-target), VPNACL-001 (collaborator OIDC)
