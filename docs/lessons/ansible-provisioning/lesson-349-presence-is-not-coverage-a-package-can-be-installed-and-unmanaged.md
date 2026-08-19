---
id: lesson-349-presence-is-not-coverage-a-package-can-be-installed-and-unmanaged
type: lesson
status: active
created: "2026-08-18"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, verification, ssot]
---

# Presence is not coverage — a package can be installed on a host nothing manages

**Context**: Archiving ANSIBLE-021, which added `tmux` to the `base_system` role's
package list. The spec's acceptance criterion was a smoke loop: `for h in ...; do
ssh "$h" tmux -V; done`. Verifying it at archive time meant asking not just
whether the package is there, but whether anything put it there.

**Problem**: The VPS returns `tmux 3.4` and is covered by nothing.
`provision-vps.yml` deliberately omits `base_system` — it says so in a comment —
and no playbook installs `tmux` by any other route:

```
$ ssh vps 'tmux -V'
tmux 3.4
$ grep -n 'tmux' infra/ansible/playbooks/provision-vps.yml
(no match)
```

The package is present and unmanaged: a rebuild from scratch produces a VPS
without it, and nothing would notice. The dangerous part is not the gap, it is
that the obvious check hides it. A fleet-wide `tmux -V` sweep now returns green
on **every** node, including the one where the result proves nothing at all. The
check answers "is it here", and the criterion means "would we put it back".

The same pass found the inverse: rpi3 *is* covered now, but through `3c9629b`
(#1059), a firewall fix that adopted `base_system` for `firewall_tailnet_ports`
and took the package list with it — not through #817, the ticket the spec named
as the route, which is still open. Coverage arrived without the ticket that was
supposed to bring it.

**Solution**: Verify coverage by reading the playbooks, and presence by reading
the hosts, and never let one stand in for the other. Reported on #817, which is
about exactly this non-uniformity.

**Rule**: A host check proves the *state*; only the IaC proves the *mechanism*.
When an acceptance criterion is about provisioning, a green sweep across the
fleet is necessary and not sufficient — ask which playbook would restore each
result, and treat any host without an answer as uncovered no matter what it
currently reports. Same family as a container reporting `healthy` while its port
is unreachable, and as `git diff --quiet` over a pathspec that matches nothing.

**Tags**: `#ansible` `#verification` `#pr-1156` `#issue-817`
