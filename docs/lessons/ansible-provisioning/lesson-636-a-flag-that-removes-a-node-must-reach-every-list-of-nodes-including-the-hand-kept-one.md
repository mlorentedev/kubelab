---
id: lesson-636-a-flag-that-removes-a-node-must-reach-every-list-of-nodes-including-the-hand-kept-one
type: lesson
status: active
created: "2026-10-27"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, testing, inventory]
---

# A flag that removes a node must reach every list of nodes, the hand-kept one included

**Context**: the Jetson left the lab for some weeks. `networking.aws` already
had the flag for this, `retired: true` (#1365): the block is a rebuild recipe,
not a running machine. The generator skipped a retired cloud block, so the
obvious change was to extend that skip to `networking.nodes`.

**Problem**: the six `make test-infra` failures for the Jetson would have stayed
red after that change. `tests/infra` does not read the generated inventory. It
reads `infra/ansible/inventories/homelab.yml`, a file kept by hand, which names
hosts its own way (`kubelab-jet1` for `networking.nodes.jetson`). A change
tested only against the generator would have passed its unit tests, and the
symptom that motivated it would have persisted.

**Solution**: the flag is honoured at both lists. The generator skips a retired
node and says so on stderr. `fixtures.load_inventory` drops a host whose address
belongs to a retired declaration, since the address is what the two files share.
A test runs the fixture against the committed inventory and the real
`common.yaml`, so it fails on the symptom itself, not on a model of it.
`platform.json` already rendered a retired node as standby. The DHCP
reservation, the DNS entry and rpi4's `PermitOpen` stay, so its return is one
flag.

**Rule**: before changing how a declaration is enumerated, find every list of
the same things, generated or hand-kept, and check which one the failing
consumer reads. Write the test that fails on the observed symptom first: a test
of the code you meant to change only proves that code.

**Tags**: `#retired` `#inventory` `#infra-tests` `#issue-2720`
