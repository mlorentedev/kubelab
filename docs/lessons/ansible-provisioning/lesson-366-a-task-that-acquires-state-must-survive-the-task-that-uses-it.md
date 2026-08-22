---
id: lesson-366-a-task-that-acquires-state-must-survive-the-task-that-uses-it
type: lesson
status: active
created: "2026-08-22"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, apt, idempotence, failure-modes]
---

# A task that acquires state must survive the task that uses it, or the failure leaves the node worse than it found it

**Context**: SEC-010 added security patching to the fleet's weekly maintenance
run. The shape is three tasks: hold the packages whose upgrade would restart a
live workload, upgrade, release the holds. Review then raised a fourth
requirement — release only the holds *this run* created, so an operator's
deliberate pin survives.

Implementing that added a gate: skip the upgrade when a hold failed on a package
apt actually knows about. The gate read

```yaml
when: ... and not (_unprotected | default([]))
```

**Problem**: Ansible refuses a conditional whose result is not boolean.

```
Conditional result (False) was derived from value of type 'list'
Conditionals must have a boolean result.
```

That is a *fatal task error*, and it landed **between the acquire and the
release**. The run placed holds on docker, containerd and tailscale, aborted,
and never came back to unhold them. Beelink was left with its container runtime
pinned by a maintenance run that had failed — a node in a state no one chose,
by a role whose entire purpose is leaving nodes healthier.

The severity is inverted from how it reads. `not (a list)` is a trivial mistake
and the linter says nothing about it; the *consequence* is that a routine
weekly job can strand a fleet-wide package hold. And it is silent: nothing
polls for unexpected holds, so it would surface weeks later as "why won't
docker upgrade on this node".

**Solution**: The conditionals compare lengths, which yields a boolean:

```yaml
when: ... and (_unprotected | default([]) | length) == 0
```

But the real lesson is not the filter. It is that **an acquire/release pair
across separate Ansible tasks has no unwind path**. `block`/`always` gives one;
so does making the acquiring task's own failure non-fatal; so does not
acquiring at all when the work can be scoped instead. Any task added *between*
the two — a gate, a fact, a debug — is a new place the release can be skipped,
and Ansible will not warn you.

Three consequences worth carrying:

- The blast radius of a mid-pair failure is the acquired state, not the task.
  Ask what the node looks like if the run dies at each step, and prefer the
  arrangement where the answer is "unchanged".
- **A hold, a lock, a drain, a firewall rule, a maintenance-mode flag** are all
  this shape. Patching is just where it showed up here.
- The guard for it belongs on the conditional's *type*, not on its logic. That
  test parses the YAML and asserts no `when:` tests a bare list — cheap, and it
  fires before the node does.

**Rule**: **When one task acquires state that another must release, the failure
of anything between them is a defect in the pair, not in the task that failed.**
Either give the pair an unwind path, or make every step between them incapable
of aborting. Reviewing the happy path tells you nothing about this.

A corollary paid for in the same hour: the first guard written for this walked
the file line by line with a `continue` that skipped exactly the lines it was
meant to inspect. It passed against the very mutation it existed to catch.
**Parse the structure; do not grep it** — and prove the guard red before
trusting it green (lesson-357).

**Tags**: `#ansible` `#apt` `#failure-modes` `#idempotence` `#pr-1267`
