---
id: lesson-644-a-zero-that-means-never-delivered-reads-as-the-oldest-time-there-is
type: lesson
status: active
created: "2026-10-28"
owner: manu
category: observability
tags: [kubelab, observability, notify, systemd]
---

# A zero that means "never delivered" reads as the oldest time there is

**Context**: #2733 asked for the failed `kubelab-notify@<unit>.service` that a refused page leaves behind to be cleared once the incident's recovery is delivered. The issue's analysis said the recovery is still sent after a refused page, because the incident state survives with a count above zero.

**Problem**: It is not sent when the refused page is the incident's first. The state file holds `<count> <first> <last>`, where `last` is the epoch of the last *delivered* page and `0` means none was. The staleness check measured the incident's age as `now - last`, so a `last` of 0 made every incident whose first page was refused 56 years old: it was discarded as stale on the next read, and the recovery mode, finding a count of 0, exited without a word. That is the exact case of the lab edge losing its route, the one the issue was filed from. Nothing caught it because no test ran a recovery after a refused first page: the suite's refused-delivery test passed *because* of the discard, which also happened to make the next failure a first page again.

**Solution**: Measure the age from the newer of `first` and `last`, so an undelivered incident ages from its first failure, and call a page the first one while `last` is 0 rather than while the count is 1. The second change is what the discard used to do by accident. Then clear the failure notifier only after the recovery is out. Each test pins one change, measured with `make mutate`: `test_an_undelivered_incident_ages_from_its_first_failure` and `test_a_delivered_recovery_clears_the_failed_page_of_its_incident` (which asserts the recovery title as well as the reset, so a skipped recovery cannot pass as a skipped reset) go red when the age is measured from `last` alone; `test_the_next_failure_after_a_refused_first_page_is_still_the_first_page` goes red when the first page is told by the count again. Each stays green against the other change, the masking described above.

Honoring an undelivered incident also opened a race the discard had hidden: a recovery could close an incident while its first page was still being delivered, and the page would then reopen it. Review found it. Both notices of a unit now take one lock from the state read to the state write, and the units' timeout holds the wait plus the run's own delivery (`test_a_recovery_waits_for_a_page_still_in_flight`). The test helper that aged the state had the same sentinel bug: it turned a 0 negative, so the script dropped the state, and every test of the age rule passed against the old code.

**Rule**: A sentinel that stands for "has not happened" must never reach arithmetic that treats it as a time. Where a 0 means "never", every comparison against it has to say what "never" should mean there. A test that passes through the sentinel's side effect is no evidence the behavior was designed. A fix that makes a state reachable makes its races reachable too: check what else could read the state while it is in that form.

**Since #2787**: a refused page is kept and delivered later, so it no longer leaves its notifier failed, and the next failure no longer pages again (lesson-678). The age rules above still hold for a state with no page recorded. `test_the_next_failure_after_a_refused_first_page_is_still_the_first_page` was replaced by tests of the spool.

**Tags**: `#notify` `#systemd` `#sentinel` `#issue-2733`
