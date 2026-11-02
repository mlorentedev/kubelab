---
id: lesson-673-uptime-kuma-has-no-not-found-answer-so-only-its-null-row-error-confirms-a-delete
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: observability
tags: [kubelab, observability, uptime-kuma, monitoring]
---

# Uptime Kuma has no not-found answer, so only its null-row error confirms a delete

**Context**: `monitoring-apply` deletes the monitors it no longer declares, then re-reads each one before it creates the replacements, so a delete that has not landed cannot leave two monitors on one target (OPS-016). It counted a monitor as deleted when the read raised anything (#2506).

**Problem**: A timeout, a dropped login or a lost socket raise too, and none of them says whether the monitor is gone. The guard read each of them as a confirmed delete and went on to create. And no test failed with the guard removed: the fake Kuma had no `get_monitor`, so every read raised `AttributeError`, which the broad `except` took for a delete. Kuma 2.2.1 has no not-found reply either. `getMonitor` in `server/server.js` reads the row with `R.findOne` and dereferences it, so a missing monitor answers `ok: false` with V8's message `Cannot read properties of null (reading 'id')`, which `uptime_kuma_api` 1.2.1 raises as `UptimeKumaException`. `Timeout` is a subclass of that same exception.

**Solution**: `_assert_deleted` treats only an `UptimeKumaException` carrying that message as gone, and re-raises every other error. The fake answers the same message for a deleted id. Tests cover a monitor that outlives the deadline, three other errors (`Timeout`, `You are not logged in.`, `ConnectionError`) and a delete confirmed at once, which must not wait. The marker was checked against a real `louislam/uptime-kuma:2.2.1` container with `tests/test_monitoring_integration.py -k dropping_a_monitor`, and `make mutate` turned each test red against its mutant, a wrong marker against the real container among them.

**Rule**: A guard that reads an error as a fact must name the one error that states that fact. When the API has no such answer, find what it actually returns in its source, pin it in the fake, and prove it against the real service. A fake that lacks the method the guard calls hands the guard an error to swallow, and the suite stays green.

**Tags**: `#uptime-kuma` `#monitoring` `#issue-2506`
