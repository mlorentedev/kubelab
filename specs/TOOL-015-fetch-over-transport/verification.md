---
tags: [spec, verification, templates]
created: "2026-06-21"
---

# Verification - TOOL-015-fetch-over-transport

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [!] **AC1** (end-to-end fetch from non-admin box) -> **PENDING live smoke from EGW-LEN029**. Code path implemented + unit-tested (trigger policy, tunnel context manager, SSH fallback read).
- [x] **AC2** (idempotent overwrite, 0600) -> existing `fetch_kubeconfig` write logic unchanged; permissions set with `dest.chmod(0o600)`. Manual verification: re-run `make fetch-kubeconfig` overwrites the file.
- [x] **AC3** (guaranteed teardown — no orphan on failure) -> `TestTsBridgeTunnel::test_guaranteed_teardown_when_body_raises` — injects `ValueError` inside the context manager, asserts `_terminate(pid)` called.
- [!] **AC4** (deterministic known_hosts) -> **PENDING live validation**. Code: `UserKnownHostsFile=/dev/null` + `StrictHostKeyChecking=accept-new` in the tunnel SSH command. No writes to `~/.ssh/known_hosts`.
- [x] **AC5** (no hardcoded IPs; pure helpers unit-tested) -> `TestResolveSshUser`, `TestResolveSshTunnelParams`, `TestTsBridgeArgv`, `TestIsConnectFailure`, `TestFetchKubeconfig` — all without network.

## Test status

- Unit (feature): `poetry run pytest tests/test_k8s_connect.py tests/test_k8s_kubeconfig.py -q` -> **315 passed** (incl. 16 new tests for TOOL-015).
- No regressions in TOOL-014 after extracting the tunnel helper + generalizing `ts_bridge_argv`.
- Lint: `make lint` -> **All checks passed**.
- Type: `make type` -> TOOL-015 files clean; 2 pre-existing errors in `generator_authelia.py` (unrelated).
- Manual smoke (the whole point): `make fetch-kubeconfig ENV=staging` from EGW-LEN029 -> **PENDING** (requires homelab on + ts-bridge auth configured).

## Decisions made during implementation

- **Trigger policy resolved**: try direct `ssh <alias>` first; on `returncode=255` + connect-error substring in stderr (timeout / no route / refused) fall back to tunnel; any other failure (auth: "Permission denied", remote command fail) raises loud. The `_is_connect_failure` predicate encodes this distinction as a pure function (unit-tested).
- **`resolve_ssh_tunnel_params` as a single helper** — rather than exposing `_node_block` or duplicating config loading in `k8s_kubeconfig.py`, one function returns `(ssh_user, mesh_host)` for a cluster env. Keeps `k8s_connect` private surface minimal.
- **`ts_bridge_argv` decoupled from `ClusterTransport`** — the old signature took `ClusterTransport` (apiserver-specific). Generalizing to `(binary, host, port, local_port)` lets the same function serve both apiserver tunnels (port 6443) and SSH tunnels (port 22) without forking.
- **Context manager yields `pid`** — callers (and tests) can observe which process was terminated. The test injects a failure and asserts on the pid, proving teardown rather than assuming it.
- **SSH run inside the `with` block** — `subprocess.run` (blocking) runs inside `with ts_bridge_tunnel(...)`, so the tunnel is always up during the SSH call and always torn down after, whether the call succeeds or raises.

## Promotion candidates

- [ ] Lesson for `docs/lessons.md`? **no** — the tunnel pattern and known_hosts options are standard; the trigger-policy distinction (connect vs auth failure) is captured in `_is_connect_failure` comments and tests.
- [ ] ADR-worthy? **no** — ADR-052 covers the transport doctrine; this is its implementation.
- [ ] Pattern candidate? **no** — repo-local.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved to `specs/archive/`
- [ ] Bitácora #733 closed with PR link (ADR-018)
