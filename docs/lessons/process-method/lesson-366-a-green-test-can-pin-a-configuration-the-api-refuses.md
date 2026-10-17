---
id: lesson-366-a-green-test-can-pin-a-configuration-the-api-refuses
type: lesson
status: active
created: "2026-08-22"
owner: manu
category: process-method
tags: [kubelab, process-method, gcp, terraform, testing]
---

# A green test can pin a configuration the provider refuses

**Context**: Bringing up the GCP Argo CD hub (GCP-001). ADR-063 decided
`instance_termination_action = DELETE` for the Spot instance template, on the
reasoning that the `STOP` default leaves a `TERMINATED` husk after every
preemption. The decision was written into the ADR, encoded in
`infra/terraform/gcp/main.tf`, explained at length in a comment, and asserted by
`test_termination_action_is_delete_not_the_stop_default`.

Everything was green. `terraform validate` passed, 36 tests passed, three PRs
merged.

**Problem**: On the first real `terraform apply`, after eleven of twelve
resources had been created:

```
Error: Error waiting for Creating InstanceGroupManager: googleapi: Error 400:
Spot virtual machines with termination action set to DELETE cannot be used with
Managed Instance Groups.
```

The configuration could never have existed. The test asserting it had been green
for its entire life — because **it agreed with the ADR, and the ADR had never
been checked against the API**. A static guard can only assert what its author
believed; it cannot discover that the belief is refused.

Two more of the same shape followed in the same apply, on one field:

- `max_unavailable_fixed = 1` — *"has to be either 0 or at least equal to the
  number of zones"* for a regional MIG.
- `max_unavailable_percent = 100` — *"only allowed for regional managed instance
  groups with size at least 10"*.

So for a **singleton regional** MIG the zone count is the only legal non-zero
value. Neither constraint appears in the general MIG documentation; both were
learned by being refused.

**Solution**: Removed `instance_termination_action` entirely, and **inverted**
the test rather than deleting it — someone reading the ADR will try to restore
`DELETE`, and an inverted assertion is what stops them where a missing one would
not:

```python
assert not re.search(r"instance_termination_action", tf), (
    "A MIG rejects DELETE outright, and STOP is the default -- so any value "
    "here is either refused or noise."
)
```

`max_unavailable` is now derived, never typed:

```hcl
max_unavailable_fixed = length(data.google_compute_zones.available.names)
```

`3` is a fact about `europe-west4`, not about the design. Written beside a
`region` that is a *variable*, it would go silently wrong on any region with a
different zone count — wrong in the direction that blocks replacement, on the
recreate path a Spot hub depends on.

**Rule**: **A decision about a provider's API is unverified until the provider
has answered.** Reading the documentation is not the same as being refused by
it, and a test is not evidence about the world — it is evidence about what
someone wrote down.

Before encoding a provider constraint in an ADR, a module and a test, get one
`plan` or `apply` against the real API, or find the constraint in the vendor
docs and cite it. And when the API does refuse something, **check whether the
decisions that were chained onto it still stand** — here, ADR-063 had omitted
autohealing *because* of `DELETE`, so that reasoning died with it. The
conclusion survived, but only after
[the docs were read](https://docs.cloud.google.com/compute/docs/instances/spot):
*"If Compute Engine stops one or more Spot VMs in a MIG, the group repeatedly
tries to recreate those VMs using the specified instance template."*

Worth its own note: **the repository already held that sentence.** The spec cites
the adjacent clause as the basis for finding F1 — why cloud-init must complete
the whole bring-up. The same paragraph answered the autohealing question, and
nobody had connected the two. Knowledge already captured is not the same as
knowledge retrieved when it is needed.

**Tags**: `#gcp` `#terraform` `#testing` `#adr-063` `#pr-1257`
