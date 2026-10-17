---
id: lesson-321-uptime-kuma-api-s-wrapper-times-out-on-the-fi
type: lesson
status: active
created: "2026-08-13"
owner: manu
category: observability
tags: [kubelab, observability]
---

# `uptime-kuma-api`'s wrapper times out on the first call over a fresh v2 socket, and integration-test containers need per-process names

**Context:** #962 (`toolkit monitoring bootstrap` swallows a Kuma-v2 setup timeout and misreports it as "admin already exists") turned out to be three separate defects layered on top of each other, each hidden until the fix for the one above it was live-tested.

**Problem 1 — the wrapper genuinely can't talk to v2 for two different calls.** `api.setup()` (`_call("setup", ...)`) times out against a real v2 instance, as the ticket's own investigation already found. Live-testing the fix surfaced a second instance of the identical failure: `api.need_setup()` — a plain read, called *before* `setup()` even runs — timed out the same way, every time, when it was the first call issued on a just-opened socket. `api.login()` elsewhere in this file has never shown the symptom. The distinguishing factor is not the event name, it's socket freshness: a short settle delay (`time.sleep(1)`) before the first call on a newly-connected `UptimeKumaApi` made both `need_setup()` and the raw `setup` emit succeed reliably; `login()` apparently never needed it because nothing calls it as the very first thing on a cold connection. A third call inherited from the pre-existing code, `upload_backup` with the v1 `{"version": "1.23.0", ...}` backup envelope, was flagged in the ticket as "not yet tested" and turned out to also time out against v2 once actually exercised live — `bootstrap`'s import step now delegates to `apply_monitors`, which already has a working, tested per-monitor create path, instead of carrying a second broken import mechanism.

**Problem 2 — a fixed integration-test container name collides across parallel sessions.** This repo runs several worktree lanes in parallel, each running `make test` independently. The integration suite's Docker container used a literal fixed name (`kubelab-test-kuma`); one lane's `docker rm -f` on setup silently killed another lane's live container mid-run. The failure read as a plain socket connection refusal and initially looked like host memory pressure (this machine's swap was genuinely near-exhausted from ~9 concurrent Claude sessions) — a plausible-but-wrong diagnosis that cost real time before the actual mechanism (a `docker ps` timeline showing a container that existed but wasn't the one this test process started) was checked.

**Solution:** `_settle()` — one named constant, one helper, called before both `need_setup()` in `bootstrap()` and inside `_run_setup()` itself (so the latter is self-contained regardless of caller). Container names suffixed with `os.getpid()`. A defensive `_wait_until_socket_reachable()` retry was also added as belt-and-braces, though the real fix was the unique name, not a longer wait.

**Rule:**
- **"Mechanically identical to a proven-working call" is not evidence a new call will succeed against the same server.** `sio.call()` and a manual `emit()` + polled callback are the same code path underneath, yet `need_setup()` failed where `login()` never had — the variable that mattered was connection freshness, not which wrapper function was used. Test every distinct *call*, not just the mechanism, against the real server before trusting it.
- **A bare "connection refused" from a fresh test container should raise "did something else claim my container's name" before "is the host out of resources."** Memory pressure produces slow, not refused; a refusal from a URL that was healthy seconds earlier is what a different process's `docker rm -f` on a shared name looks like. Check `docker ps` for a container you didn't expect before reaching for `free -h`.
- **Any shared literal identifier (container name, lock file, tmp path) is a collision risk the moment more than one agent session can run the same code concurrently** — the same bug class as the `gh` default-repo ambiguity already known to bite parallel sessions in this project. PID-suffix or otherwise namespace anything a concurrent run of the same test suite could also create.
- **Delegating one function's write path to another's does not preserve safety guarantees for free — audit every caller before assuming it does.** `apply_monitors` is a safe declarative sync when invoked deliberately (`make monitoring-apply`), but `bootstrap` runs unattended on every rpi3 Ansible provision, not just the first one; calling `apply_monitors` unconditionally from `bootstrap` would have handed an automated, unattended path the power to delete monitors the seed had merely drifted from — exactly the hazard #962/#925 had just removed from `apply_monitors` itself. The fix stayed correct by keeping the delegation strictly inside the fresh-install branch, where an empty live set makes the diff provably create-only.

**Tags:** `#uptime-kuma` `#socketio` `#integration-tests` `#docker` `#parallel-sessions` `#obs-012` `#gotcha`
