---
id: "OPS-016-dnat-drift-healing"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-08-11"
issue: "kubelab#959"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# OPS-016: DNAT drift healing

## Why

<!-- from issue #959: OPS-016: ufw provisioning leaves live-restored containers without their DNAT rules -->

Five of seven nodes published no Docker port at all — Glances dark everywhere, MinIO dark on beelink — and **nothing reported it**, because the nodes kept answering ICMP and Uptime Kuma only pings them (#963). The failure is invisible from inside a node: containers report `healthy`, since health probes run *inside* the container while port publishing is kernel state *outside* it. It was found by hand, months after it started.

The trigger is still unknown and has now survived five deliberate reproduction attempts across two Docker generations (`ufw reload`, `ufw disable/enable`, `systemctl restart ufw`, `systemctl restart docker`, and a host reboot — which turns out to *repair* rather than break). **This spec therefore treats the symptom on purpose**: the repair is proven at fleet scale, the cause resists reproduction, and an unattended `docker-ce` upgrade restarting dockerd cannot be prevented in any case — only detected and healed.

## What

Three observable changes, one per ticket in the chain:

1. **`make monitoring-apply` becomes non-destructive** (#962, #925). It converges the live Uptime Kuma instance to `monitors.json` by upserting — creating what is missing, editing what differs, deleting what the seed dropped — instead of deleting all 31 monitors and recreating them. Accumulated uptime history survives a sync. The delete race that reported `Removed 32 monitors (32 remaining)` as a SUCCESS becomes a bounded assertion that fails loudly.
2. **Per-node agent ports are monitored** (#963). Every node that publishes an agent port gets an HTTP monitor for that port, derived from `networking.nodes.*` in `common.yaml` rather than hand-written, so the next node inherits monitoring by existing. A dark Glances endpoint raises an alert within one check interval instead of going unnoticed for months.
3. **DNAT drift is detected and repaired on the node** (#959). An idempotent Ansible task compares the port bindings Docker declares against the DNAT rules actually installed in the `nat` table, and runs `up -d --force-recreate` on exactly the compose projects that disagree. A healthy node reports `changed=0`. Headscale is excluded by project name — it is the VPN control plane, and recreating it is a decision a human makes, not a side effect of a drift sweep.

## Out of scope

- **Finding the trigger.** Five candidates eliminated with measured before/after counts on two nodes; the one event-shaped lead (a `docker-ce` 29.5.3→29.7.2 upgrade three minutes before the discovering measurement on beelink) explains one node out of five. Investigation stays open on #959 as a comment thread, not as work in this spec.
- **`ufw-docker` / populating `DOCKER-USER`** — that is #961 and a *different* problem: restricting access to published ports, not restoring rules that vanished. Adopting it would not have prevented this.
- **The Jetson's Glances**, which runs from a raw `docker run` outside any role and answers to any Host header — #984.
- **A read-only `monitoring list` CLI.** #925 names the gap (`monitoring-export` clobbers the seed, so live state cannot be inspected without destroying local edits) and explicitly defers it.

## Risks / open questions

- **RESOLVED — can the API even upsert?** `uptime_kuma_api.UptimeKumaApi.edit_monitor(id_, **kwargs)` exists in the pinned `^1.2.1`. Verified before writing this criterion, because the whole of change 1 rests on it.
- **RESOLVED — what is a monitor's identity?** The seed grows an explicit immutable `key` field. `name` cannot be the identity: renaming a monitor would read as delete + create and silently discard its history, reintroducing this spec's own bug in a narrower case. The constraint found while deciding: Uptime Kuma persists only the fields in `_MONITOR_EXPORT_FIELDS`, so there is nowhere on the live instance to store a custom field. The key is therefore **carried in `description`** as a machine-readable marker — not in `tags`, whose code path is the flakiest part of `apply_monitors` (`monitoring.py:190` swallows every tag failure in a bare `except Exception: pass`) and whose namespace has real semantics. `export` parses the marker back out and strips it, so the seed stays clean. Matching is marker-first with a **name fallback that stamps the key**, which makes migration free: the first apply matches all 31 existing monitors by name and stamps them via edits, deleting nothing.
- **How is the repair tested when the failure cannot be reproduced?** The remedy has to be provable against a broken node, and no trigger produces one. Intended answer: induce it deliberately (`iptables -t nat -F DOCKER`), the same technique OBS-007 used to prove the ACME alert both fires and clears. Named here because a repair task verified only against healthy nodes is a task verified against nothing.
- **RESOLVED — does the key marker survive?** Proven against a throwaway `2.2.1` container, before any diff logic was written. `edit_monitor(id_, description=...)` round-trips (`'Beelink metrics agent.\n[kuma-key:glances-bee]'`), and a rename preserves both the monitor `id` and the marker. The design holds.
- **RESOLVED — `bootstrap` cannot initialise a FRESH Kuma 2.2.1, and it misreports why.** `monitoring.py:292-301` calls `api.setup()`, which **times out** against v2 (measured on a throwaway 2.2.1 — the v1-era wrapper does not complete v2's setup handshake), then catches the timeout in a bare `except Exception` that logs *"Admin user already exists"* and falls through to `login`, which fails with `authIncorrectCreds` because no user was created. The broad except turns "setup did not run" into "setup was not needed" — the same anti-pattern as the OBS-007 SOPS guard that silently skipped 13 tests while reporting green. Fix: emit `setup` on the raw socket and read the ack (`{"ok": True, "msg": "successAdded"}`, verified), and narrow the except so a real failure surfaces.
- **CORRECTED — an earlier revision of this file claimed `apply_monitors` could not populate a rebuilt Kuma. That was wrong.** It came from probing the library's `add_monitor` directly and generalising to the toolkit without reading its create path. `monitoring.py:254-257` already injects `conditions` with the comment `Uptime Kuma v2.x requires conditions (NOT NULL in DB)`, and line 261 deliberately calls `api.sio.call("add", …)` because the wrapper "has issues with v2 responses". Both workarounds predate this spec. Recorded rather than silently deleted, because the mistake is the instructive part: a library-level probe does not license a claim about the caller.
- **RESOLVED — `get_monitors()` is a client-side cache, not a server read.** It does not reliably refresh after a write within the same session: a rename was invisible to `get_monitors()` for 15s while `get_monitor(id)` returned it immediately. **This is the real explanation for #925's `time.sleep(3)`** — the sleep was compensating for cache lag, not for server-side deferred deletes. It follows that AC3's bounded poll must assert over authoritative `get_monitor(id)` reads; a poll over `get_monitors()` would replace a fixed guess with a longer one and still be racing a cache.
- **OPEN — the delete path was never exercised.** Everything proven this session concerns creates and edits. Whether Uptime Kuma v2 *also* has genuinely deferred delete cleanup (as the `time.sleep(3)` comment claims) is untested, so the cache-lag explanation above accounts for the observed behaviour but does not exclude a second effect. AC3's bounded poll must therefore be written against a real delete on the throwaway instance before it is asserted to work; if both effects are real, the poll has to converge on both.
- **Accepted risk — `uptime-kuma-api` is unmaintained for Kuma v2.** 1.2.1 is the latest release on PyPI and is v1-era. Survivable only because the server is pinned (`common.yaml:639`, `louislam/uptime-kuma:2.2.1`): any future Kuma bump must re-run this probe before merging. Explicitly NOT solved by rewriting on raw socket.io — that is a separate ticket if the pin ever moves.
- **rpi3 is NOT the dev loop.** An earlier draft of this section claimed the monitoring changes could only be validated against the live instance — false, and it was the strongest risk here. `louislam/uptime-kuma` runs as a throwaway local container, so AC1–AC3 develop against a disposable instance. rpi3 is touched only for the final convergence check and AC4's real-alert path, which is the one thing a local container cannot prove.

## Acceptance criteria

- [ ] AC1 — Running `make monitoring-apply` twice with an unchanged seed leaves every monitor's `id` identical across both runs, and performs zero deletes on the second.
- [ ] AC2 — With a seed edited to add one monitor, change one monitor's interval, and remove one monitor, a single apply converges the live instance to the seed and leaves the `id` of every untouched monitor unchanged.
- [ ] AC3 — `apply_monitors` contains no fixed `sleep`, and exits non-zero when the live state fails to reach its expected precondition instead of logging SUCCESS and continuing.
- [ ] AC4 — Every node in `networking.nodes.*` publishing an agent port has a corresponding HTTP monitor in the seed, asserted by a test that reads `common.yaml`; stopping that port makes the monitor report down within one interval.
- [ ] AC5 — Against a node with its `DOCKER` nat chain deliberately flushed, the drift task restores every published port (probed over HTTP from off-node); re-run on the now-healthy node reports `changed=0`.
- [ ] AC6 — The drift task never recreates the headscale compose project, asserted by a test rather than by a comment.

## References

- Bitácora board: `kubelab#959` (this spec's gate), plus `#962`, `#963`, `#925` covered by the same chain
- Evidence: the Step 1 / Step 2 / correction comments on `#959` — five eliminated triggers with before/after rule counts
- Adjacent, deliberately not included: `#961` (`DOCKER-USER`), `#984` (Jetson), `#960` (rpi3 firewall — its blocker rationale is weakened by this spec's measurements)
- Related gotcha: CLAUDE.md, "A ufw rule cannot restrict a Docker-published port"
