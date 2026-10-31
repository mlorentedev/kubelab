---
id: lesson-631-an-e2e-probe-that-folds-a-refusal-into-a-timeout-skips-the-outage-it-exists-to-find
type: lesson
status: active
created: "2026-10-26"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, e2e, testing, networking]
---

# An e2e probe that folds a refusal into a timeout skips the outage it exists to find

**Context**: The e2e suite skips a service whose backend is an on-demand node (ADR-028) when a TCP probe, `backend_reachable`, cannot connect, so a powered-down homelab does not read as a prod outage. Its docstring called the conflation of a refused connection with a timeout deliberate, because `tests/infra/test_network.py` "owns the distinction".

**Problem**: That test owns it for one pairing only, Gitea on the Beelink. Nothing failed when the port of Open WebUI on ace2 refused, so every e2e suite skipped it as "powered off" while ace2 had been up for a day and the container simply was not bound (#2703). The skip reason was wrong too: it asserted a cause the probe never measured. The two outcomes are not the same signal. A timeout or no route means nothing answered (node off, or a runner off the tailnet). A refusal means the host answered and said no, so the node is up and the service is down, and a runner off the tailnet never reaches the host to be refused. The same fold had already hidden the Beelink's 2026-08-14 outage from an earlier version of `test_network.py`.

**Solution**: `backend_reachable` catches `ConnectionRefusedError` before `OSError`, as `test_network.py` does, and raises `BackendRefused` ("the node is up and nothing is listening on host:port") instead of returning False. It raises rather than returns a third value because a caller that has not been updated then fails, where a truthy `"refused"` would be read as up and a falsy one as down. Silence keeps the skip, now worded as what was measured: "timeout: node off, or this runner is not on the tailnet". `tests/test_e2e_skip_reason_wording.py` runs the real probe against a closed loopback port (refusal fails, the message names host:port), a patched `create_connection` that times out or has no route (skip), and a live listener (no skip). `make mutate` turning `ConnectionRefusedError` into `ConnectionResetError` sends the refusal tests red.

**Rule**: A comment that says another test covers a case is a claim about that test's reach, so read the reach before relying on it. When a probe has two failure modes with different meanings, give each its own outcome, and make the one that must not be skipped impossible to ignore by raising it. An "unreachable" verdict names the cause only if the probe measured it.

**Tags**: `#e2e` `#testing` `#fail-closed` `#pr-2700`
