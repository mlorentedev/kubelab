---
tags: [spec, tasks, templates]
created: "2026-06-21"
---

# Tasks - TOOL-015-fetch-over-transport

> TDD order. Pure helpers first (unit-tested), then the I/O. Builds on TOOL-014's
> `k8s_connect` helpers — extract, don't duplicate.

## Setup

- [ ] Branch: `feat/TOOL-015-fetch-over-transport` (already created from master)
- [ ] `/spec fill` to resolve the trigger-policy open question, then freeze acceptance
- [ ] Land the TOOL-014 evidence first (see handoff) so master's spec is current

## Implementation

- [ ] Generalize `ts_bridge_argv(binary, host, port, local_port)` (drop the apiserver-only `ClusterTransport` coupling); update TOOL-014 callers + tests
- [ ] Extract the bridge lifecycle from `connect()` into a transient context manager: `with ts_bridge_tunnel(host, port, local_port) as ready: ...` — spawn, healthcheck the local port, `try/finally` terminate
- [ ] Test: the context manager terminates the process even when the body raises (inject a failure; assert no orphan via the returned pid)
- [ ] Resolve SSH user + mesh host from SSOT for a cluster's node (reuse `_node_block`; user from `networking.ssh_users.<category>` per SSOT-014a)
- [ ] Implement the trigger policy (per /spec fill): direct `ssh <alias>` first, fall back to the tunnel on connect/timeout failure ONLY (auth failure fails loud)
- [ ] Wire `fetch_kubeconfig`: on fallback, read `k3s.yaml` via `ssh -p <ephemeral> -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=accept-new <user>@127.0.0.1`, then the existing `rewrite_server` + 0600 write
- [ ] Update `operate-from-new-workstation.md`: replace the manual rodeo with the codified one-command path
- [ ] Update the TOOL-014 runbook caveat to point at the now-codified path

## Closing

- [ ] Every acceptance criterion covered by a test or a documented manual check
- [ ] `features.json` filled (teardown-no-orphan + idempotent-overwrite are the key machine checks)
- [ ] Type + lint pass
- [ ] PR opened referencing this spec; live-validated from the non-admin box (the whole point)

## Machine-readable features

Emit `features.json` per [[pattern-feature-list-as-primitive]] once acceptance is frozen.
Key non-vacuous checks: idempotent overwrite, guaranteed teardown (no orphan on failure),
deterministic known_hosts, end-to-end fetch+connect+`kubectl get ns` from a non-admin box.
