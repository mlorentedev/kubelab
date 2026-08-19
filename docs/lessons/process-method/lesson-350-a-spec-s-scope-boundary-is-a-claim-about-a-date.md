---
id: lesson-350-a-spec-s-scope-boundary-is-a-claim-about-a-date
type: lesson
status: active
created: "2026-08-18"
owner: manu
category: process-method
tags: [kubelab, process-method, sdd, specs]
---

# A spec's scope boundary is a claim about a date, not a durable guarantee

**Context**: ANSIBLE-021 shipped in June and was archived in August. Its proposal
carried a confident exclusion: "**vps and rpi3 are NOT covered by this change**:
their bespoke playbooks deliberately omit `base_system`. They receive tmux as
part of the minimal-baseline fix in **ANSIBLE-029 (#817)**".

**Problem**: Both halves had stopped being true by archive time, and **neither
changed for the reason the spec predicted**. rpi3 now runs `base_system` — via
#1059, a firewall fix that wanted `firewall_tailnet_ports` and took the whole
role with it — while #817 is still open. The VPS has `tmux` from an unmanaged
source. The spec was wrong for seven weeks and nothing reported it, because
nothing *could*: no test asserts a scope boundary, and the changes that
invalidated it never read the spec. They had no reason to.

Writing a test for it would have been the wrong instinct. Pinning
`provision-rpi3.yml` to *not* include `base_system` would have made #1059 fail
for a reason unrelated to what #1059 was doing, to protect a sentence in a spec
whose implementation was already complete.

**Solution**: Re-measure the boundary at archive time and correct the proposal in
place, with the date and the commit that moved it (`3c9629b`), rather than
quietly deleting the stale paragraph. The archived spec now records both what it
claimed and what became true.

**Rule**: Treat "not covered by this" as a measurement, not a guarantee. It was
true when written, it is unowned by anything afterwards, and the cheapest control
is a re-measurement in the archive pass — not an assertion that pins another
team's file. Corollary for reviews: "no test asserts this" is a real finding and
still not always an argument for adding one.

**Tags**: `#sdd` `#specs` `#pr-1156` `#issue-1144`
