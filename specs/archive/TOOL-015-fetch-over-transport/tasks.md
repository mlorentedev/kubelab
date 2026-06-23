---
tags: [spec, tasks, templates]
created: "2026-06-21"
---

# Tasks - TOOL-015-fetch-over-transport

> TDD order. Pure helpers first (unit-tested), then the I/O. Builds on TOOL-014's
> `k8s_connect` helpers — extract, don't duplicate.

## Setup

- [x] Branch: `feat/TOOL-015-fetch-over-transport` (already created from master) ✓ 2026-06-21
- [x] `/spec fill` to resolve the trigger-policy open question, then freeze acceptance ✓ 2026-06-22 (try-direct-then-fallback; 255+connect-stderr → fallback; 255+auth-stderr → fail loud)
- [x] Land the TOOL-014 evidence first (see handoff) so master's spec is current ✓ 2026-06-21 (#732)

## Implementation

- [x] Generalize `ts_bridge_argv(binary, host, port, local_port)` (drop the apiserver-only `ClusterTransport` coupling); update TOOL-014 callers + tests ✓ 2026-06-22
- [x] Extract the bridge lifecycle from `connect()` into a transient context manager: `with ts_bridge_tunnel(host, port, local_port) as pid: ...` — spawn, healthcheck the local port, `try/finally` terminate ✓ 2026-06-22
- [x] Test: the context manager terminates the process even when the body raises (inject a failure; assert no orphan via the returned pid) ✓ 2026-06-22 (`TestTsBridgeTunnel::test_guaranteed_teardown_when_body_raises`)
- [x] Resolve SSH user + mesh host from SSOT for a cluster's node (`resolve_ssh_user`, `resolve_ssh_tunnel_params`; user from `networking.ssh_users.<category>` per SSOT-014a) ✓ 2026-06-22
- [x] Implement the trigger policy: direct `ssh <alias>` first, fall back to the tunnel on connect/timeout failure ONLY (auth failure fails loud; `_is_connect_failure` predicate) ✓ 2026-06-22
- [x] Wire `fetch_kubeconfig`: on fallback, read `k3s.yaml` via `ssh -p <ephemeral> -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=accept-new <user>@127.0.0.1`, then the existing `rewrite_server` + 0600 write ✓ 2026-06-22
- [x] Update `operate-from-new-workstation.md`: document the now-codified one-command path + auto-fallback note ✓ 2026-06-22
- [x] Update the TOOL-014 runbook caveat to point at the now-codified path ✓ 2026-06-22 (Step 1 in operate-from-new-workstation.md now documents auto-fallback)

## Closing

- [x] Every acceptance criterion covered by a test or a documented manual check ✓ 2026-06-22 (unit tests; live smoke pending from EGW-LEN029)
- [x] `features.json` filled ✓ 2026-06-22 (TOOL-015-f1..f6; f3/f5/f6 verified by tests; f1/f2/f4 pending live smoke)
- [x] Type + lint pass ✓ 2026-06-22
- [x] PR opened referencing this spec; live-validated from the non-admin box (the whole point) ✓ 2026-06-22 (PR #741 merged; EGW-LEN029 smoke: 6 namespaces via kubectl get ns)

## Machine-readable features

Emit `features.json` per [[pattern-feature-list-as-primitive]] once acceptance is frozen.
Key non-vacuous checks: idempotent overwrite, guaranteed teardown (no orphan on failure),
deterministic known_hosts, end-to-end fetch+connect+`kubectl get ns` from a non-admin box.
