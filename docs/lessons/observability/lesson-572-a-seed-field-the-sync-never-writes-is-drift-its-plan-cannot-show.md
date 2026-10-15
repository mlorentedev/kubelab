---
id: lesson-572-a-seed-field-the-sync-never-writes-is-drift-its-plan-cannot-show
type: lesson
status: active
created: "2026-10-14"
owner: manu
category: observability
tags: [kubelab, observability, uptime-kuma, monitoring, drift]
---

# A seed field the sync never writes is drift its plan cannot show

**Context**: #1974 added the `on-demand` tag to seven Uptime Kuma monitors in
`monitors.json`. `make monitoring-apply CHECK=1` planned seven edits, the apply
reported `7/7 edited`, and a second plan reported zero.

**Problem**: The live monitors still had no `on-demand` tag. `edit_monitor` does
not carry tags, so the apply path attached them only when it created a
monitor. The diff deliberately skipped tags too: "compare exactly what you
write" was the rule, and a test named `test_tags_alone_never_mark_a_monitor_dirty`
pinned it. The seven edits were real, but only because muting is derived from
the seed's tags and so cleared each monitor's notifications. The tags
themselves never moved, and a zero plan said so falsely. One more monitor had
drifted the same way unnoticed: Homepage Cockpit lacked `web` live. And two tags
the seed already used, `dns` and `web`, were not even declared in `tags.json`.

The check that would have caught it at once was the export, and it lied in a
different way: it overwrites the seed in the raw API shape (OBS-037, #2291), so
the honest comparison had to be made on a scratch copy.

**Solution**: Tags are compared by `tag_drift` beside the call that writes
them, following the `notificationIDList` precedent rather than joining
`WRITABLE_FIELDS`. Every edit runs `_reconcile_tags`: add what the seed has,
remove what it does not, and fail loudly on a tag `tags.json` does not declare.
The next plan showed eight edits, the seven plus Homepage Cockpit's missing
`web`. After the apply, a live read found zero tag drift across all 37
monitors.

**Rule**: "Compare exactly what you write" is half a rule. The other half is
"write everything the seed declares". A declared field the sync never writes
drops out of the comparison, so a zero plan certifies nothing about it. Verify a
declarative sync by reading the live object back, field by field, never by its
own plan.

**Tags**: `#uptime-kuma` `#declarative-sync` `#issue-1974` `#issue-2291`
