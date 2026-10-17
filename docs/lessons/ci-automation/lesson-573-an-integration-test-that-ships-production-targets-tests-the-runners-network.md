---
id: "lesson-573-an-integration-test-that-ships-production-targets-tests-the-runners-network"
type: lesson
status: active
title: "An integration test that ships production targets tests the runner's network"
created: "2026-10-14"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, uptime-kuma, flaky-test, integration]
---

# An integration test that ships production targets tests the runner's network

**Context**: The real-instance tests in `tests/test_monitoring_integration.py`
apply the whole `monitors.json` seed to a throwaway Uptime Kuma 2.2.1
container. Since 2026-08-20 they failed intermittently, one run in four in the first sample, with
`socketio.exceptions.TimeoutError` (#1196), in three different tests of the
module. The one traceback still on record (run 38113307179) is a login on a
fresh connection, right after an apply had created 37 monitors, with no answer
within 60 s. The container is module-scoped, so every test logs in on an
instance that holds, or has just held, that seed. The tests passed on every
local rerun, twelve times in a row on 2026-10-14.

**Problem**: The seed's monitors check production hosts, tailnet addresses
and VPN-only names. From a CI runner none of them answer, so right after an
apply 36 active monitors start checks that can only time out, inside the
container that also has to answer the login. A login is not one query:
`afterLogin` sends the monitor list, then a heartbeat list and stats for every
monitor at once, 74 database reads for this seed.

What was measured, and what was not:
- Login cost grows with the monitor count and the CPU. On the Mac it took
  0.05 s on an empty instance and 0.13 s after the apply. With the container
  limited to 0.25 CPU it took 0.4-0.8 s empty and 2.0-2.6 s after the apply.
  That is far short of 60 s.
- A dropped first event is not the cause. Kuma registers its socket handlers
  only after `await sendInfo(...)`, so an event sent too early would get no
  answer. But 0 of 30 fresh connections lost their first call.
- The mechanism that turns a 2 s login into 60 s on a hosted runner was not
  measured. It needs the runner's network, which a workstation on the tailnet
  cannot reproduce.

**Solution**: The tests point every monitor at the instance itself. `url`
becomes Kuma's own `http://127.0.0.1:3001`. `hostname` and
`dns_resolve_server` become `127.0.0.1`, except a `dns` monitor's hostname,
which is the name it resolves. These tests prove apply semantics: upsert by
key, rename is an edit, prune refuses. They need the seed's field shapes, not
its targets. `tests/test_monitoring_integration_targets.py` fails on a seed
field that is neither a rewritten target nor declared as not one, so a new
target field cannot slip past the rewrite.

Making the monitors inactive was the other option. It was rejected because
`active` is an export field, not one the sync writes. Adding it to
`WRITABLE_FIELDS` would put it in the plan, and a production apply would then
unpause every monitor paused in the UI. A probe that set `active: false`
measured nothing for the same reason. The sync dropped the field, so both
"phases" ran active monitors.

**Rule**: A test fixture built from production configuration also brings that
configuration's targets. It then tests whether the runner can reach them,
whatever its name says. Keep the shapes and rewrite where things connect. And
before using a field in a probe, check that the code under test writes it. A
field the sync drops makes the comparison void without a single error.

**Tags**: `#flaky-test` `#uptime-kuma` `#integration-test` `#issue-1196`
