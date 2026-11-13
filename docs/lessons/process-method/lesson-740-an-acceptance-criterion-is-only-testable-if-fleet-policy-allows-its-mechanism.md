---
id: lesson-740-an-acceptance-criterion-is-only-testable-if-fleet-policy-allows-its-mechanism
type: lesson
status: active
created: "2026-11-12"
owner: manu
category: process-method
tags: [kubelab, process-method, spec, ssh, acceptance-criteria]
---

# An acceptance criterion is only testable if fleet policy allows the mechanism it names

**Context**: ANSIBLE-037 (#1075) gave ace2 its own forge key. Its D1 said the operator's half needed no provisioning, because interactive work from ace2 would use SSH agent forwarding from the workstation. AC6 was the measurement meant to prove that claim: `ssh -A ace2`, then a push attributed to the operator.

**Problem**: AC6 could never pass. `ssh_hardening` sets `AllowAgentForwarding no` on every node, by fleet policy (dotfiles#2464). The role itself writes `IdentitiesOnly yes` for the forge host, which would refuse a forwarded key even if one arrived. On 2026-11-12, `ssh -A ace2` gave an empty `SSH_AUTH_SOCK`. The spec froze on 2026-09-01 with a design claim that rested on a mechanism the fleet had already closed. Nobody saw it until the last criterion ran, two months and one merged implementation later.

**Solution**: The owner kept the fleet policy and withdrew AC6. The spec's D1 amendment now names the operator's workstation as the human half: they push from there, or work on ace2 through the agents' account. In both cases no key of theirs reaches the node, which is the property D1 wanted.

**Rule**: Before a spec freezes, take each acceptance criterion that names a mechanism (forwarding, a port, a capability, a scope) and grep the fleet's hardening and policy roles for it. When a criterion is the measurement that proves a design claim, a closed mechanism breaks the claim along with the criterion. Run that grep before the first PR is written, not after the last one.

**Tags**: `#spec` `#ssh` `#pr-3391`
