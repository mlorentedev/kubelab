---
id: lesson-358-a-passing-re-run-is-not-evidence-against-a
type: lesson
status: active
created: "2026-08-20"
owner: manu
category: process-method
tags: [kubelab, process-method, testing, flaky-tests, reasoning]
---

# A passing re-run is not evidence against a flake — it is what a flake looks like

**Context**: `make test` failed once on
`test_monitoring_integration.py::TestPushMonitorRoundTrip` with a
`socketio.exceptions.TimeoutError` at fixture setup. A peer session was running
tests on the same machine, so Docker contention was a plausible cause. Re-running
that class alone gave **4 passed**.

**Problem**: I read the isolation pass as *evidence for* the contention
explanation, concluded there was no defect, recorded the reasoning, and filed
nothing.

The next CI run refuted it: the same test failed on a **GitHub-hosted runner** —
a clean VM with no competing containers, where contention cannot be the cause.
Measured frequency across four runs, local and hosted: roughly one in four.

The error was not the hypothesis. Contention was reasonable. The error was
treating the re-run as a **test of** it. **A flaky test passing on re-run is the
defining behaviour of a flaky test**, so that observation is consistent with both
explanations and discriminates between neither. I took a result with zero
diagnostic power and scored it for the hypothesis I already held.

**Solution**: Filed as TEST-001 with the frequency table, and with the correction
written into the ticket rather than quietly dropped. The real discriminator was
available and cheap: *does it fail somewhere the proposed cause cannot exist?*
One hosted-runner result settled in seconds what the isolation run could not
settle at all.

**Rule**: When a test fails and then passes, that sequence tells you **nothing**
about why. Before accepting an environmental explanation, name the observation
that would **distinguish** it from a flake — usually "run it where the proposed
cause is absent" — and go get that observation. If you cannot think of one, you do
not have an explanation, you have a guess with a green run stapled to it.

Corollary, because it is the part that actually costs: an unfiled flake teaches
everyone to merge past a red test row. #1193 was merged with `Tests` red, which
was a reasonable call **only because someone already knew that particular red**.
The next one will not be this test.

**Tags**: `#testing` `#flaky` `#reasoning` `#issue-1196`
