---
id: lesson-448-a-rebuild-recipe-is-not-an-inventory-of-what-is-running
type: lesson
status: active
created: "2026-08-25"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, ssot, inventory, test-infra, gcp-001, pr-1391]
---

# A rebuild recipe is not an inventory of what is running

**Context**: GCP-001 destroyed the `aws1` hub on 2026-08-23. `networking.aws`
stayed in the SSOT on purpose (#1333): the Terraform module and the
`provision-aws1.yml` playbook read it to rebuild AWS in one command. #1391
(refs #1365).

**Problem**: Nothing distinguished "values that rebuild a host" from "a host
that is running", so every consumer that enumerates nodes kept enumerating a
destroyed machine. The live suite paid two minutes per run for it:

```
$ make test-infra          # master
6 failed, 20 passed, 32 skipped
  ['kubelab-aws1 (aws1.kubelab.internal): SSH failed - Connection timed out']  x5
```

A second staleness surfaced while looking: the committed inventory had never
listed `gcp1`, so the suite was testing a machine that did not exist and not
testing the hub that did, in both directions at once, for the whole
migration.

**Solution**: A single `retired: true` flag on the node. The generator checks
it before the address and not instead of it: a retired node keeps its
`tailscale_dns`, so bringing AWS back is one flag, and an address was never
evidence that anything answers on it. A test pins both directions, so the
retirement is not a one-way door. The assertion that had guarded "the AWS hub
was not displaced" during coexistence was re-aimed rather than deleted: the
hub may leave only by an explicit retirement in the SSOT, never as a side
effect of editing the neighbouring cloud block, which is the deliberately
duplicated shape a copy-paste displaces. Result: `26 passed, 32 skipped`.

The `gcp1` gap was stated in the inventory and left to #1228, which owns that
file drifting from its generator; the stale Headscale registration was raised
on the ticket, because `recycle-stale` deliberately refuses to delete a node
that merely died.

**Rule**: A configuration block can be a recipe or an inventory, and the
readers cannot tell which from its shape. When a resource is retired but its
rebuild values are kept, say so with an explicit flag that enumerators
honour, and check the flag before any address; keeping the values without the
flag turns every live check into a timeout. Re-aim guards that a migration
made obsolete rather than deleting them, and name the case a command refuses
instead of working around the refusal.

**Tags**: `#ssot` `#inventory` `#retired` `#test-infra` `#pr-1391`
