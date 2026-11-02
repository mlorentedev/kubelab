---
id: lesson-640-a-guard-that-pairs-two-roles-by-tag-says-nothing-about-which-runs-first
type: lesson
status: active
created: "2026-10-27"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, systemd, notify]
---

# A guard that pairs two roles by tag says nothing about which runs first

**Context**: Units in four roles name the fleet notifier's template units through
`OnFailure=kubelab-notify@%n.service` and `OnSuccess=kubelab-notify-recovered@%n.service`.
`node_notify` installs those templates. `tests/test_node_notify_role.py` already
checked that every tag reaching a consumer also reaches the notifier.

**Problem**: The lab edge's journal, read after its bring-up, showed this line
on every run of the lease check and the liveness probe, across two boots:
`Failed to enqueue OnSuccess= job, ignoring: Unit kubelab-notify-recovered@... not found`.
It stopped once the template was installed. `provision-rpi4.yml` applied
`gateway` before `node_notify`, and the bring-up runs stopped between the two,
so the gateway's units ran for hours with no template behind the name. Every
failure or recovery in that window went unannounced, and systemd counts the
missing unit as `ignoring`, not as an error. `provision-rpi3.yml`
(`rpi3_services`) and `provision-ace2.yml` (`agent_stack`) had the same order.
The tag test passed on all three, because it checks which roles a selector
reaches, not the order they run in. The playbook comment said "ordered before
node_maintenance", which named the first consumer and none of those added
after it.

**Solution**: Each play now applies `node_notify` before the first role whose
units name it, with its tags unchanged. A second guard,
`test_the_notifier_is_installed_before_the_units_that_name_it`, reads each
play's role order and fails when a consumer comes before the notifier. It
derives the consumers from the unit templates, as the tag guard does. It went
red on exactly the three plays before the move and green after it.

**Rule**: When one role depends on another, guard both selection and order.
A tag check answers "do they run together", and a play can satisfy it while
running them in the wrong order. Derive the dependent set from the artifact
that creates the dependency (here, the unit's `OnFailure=` line), not from a
list or a comment naming the first case.

**Tags**: `#systemd` `#ansible` `#ordering` `#issue-2728`
