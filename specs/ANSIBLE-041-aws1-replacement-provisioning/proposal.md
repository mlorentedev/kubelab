---
id: "ANSIBLE-041-aws1-replacement-provisioning"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-08-16"
issue: "mlorentedev/kubelab#1102"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# ANSIBLE-041-aws1-replacement-provisioning

> **Naming**: file lives at `<repo>/specs/ANSIBLE-041-aws1-replacement-provisioning/proposal.md`. `ANSIBLE-041-aws1-replacement-provisioning` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #1102: ANSIBLE-041: a Spot replacement of aws1 silently drops the maintenance timer and the whole notify path -->

`make aws1-replace` rebuilds the Argo CD hub and then stops, printing `Wait ~5 min for cloud-init, then run: make deploy-argocd`. Neither that instruction nor anything else in the chain runs `provision-aws1.yml`, which is where the `node_maintenance` role lives — so a replaced aws1 comes up with no maintenance timer, no `kubelab-maintenance-notify.service`, and no fleet webhook secret. ANSIBLE-035 was created because a rebuild "wiped the fleet's only maintenance timer with nothing noticing"; it added the role to the playbook, which was necessary and not sufficient, because the replacement path never calls the playbook. The gap is invisible in the direction it fails: no timer produces no maintenance failures, so the absent notifier is never exercised and a silently unmonitored hub is indistinguishable from a healthy one.

## What

`make aws1-replace` completes the node's bring-up instead of handing a checklist to a human. After this change one command takes aws1 from "replaced" to "monitored and reconciling":

1. Terraform replaces the instance (unchanged).
2. The target **waits for the node to accept connections** — a real readiness poll, not the current `Wait ~5 min` prose. The wait is an Ansible `wait_for_connection`, not shell embedded in the Makefile.
3. It runs `provision-aws1` with `ENV=hub`, installing `node_maintenance` and everything else day-2 provisioning owns.
4. It hands off to `make deploy-argocd`.

Observable outcome: after `make aws1-replace` returns, `kubelab-maintenance.timer` is enabled and active on aws1 and `make maintain-notify-test NODE=aws1 ENV=hub` delivers, with no manual step in between.

## Out of scope

- **The `stop` vs `terminate` interruption decision.** `main.tf` sets `instance_interruption_behavior = "stop"` while `provision-aws1.yml`'s header documents `terminate` + ASG as the contract; `git log -S` shows `terminate` was never applied. #1106 owns that decision. The two are coupled in one direction only — `terminate` is safe *after* this spec lands, because a terminated node is rebuilt by the path this spec is fixing — so #1106 cites this spec as its prerequisite, and this spec does not touch Terraform's spot options.
- **Auditing which other nodes have bring-up paths that bypass `provision-*.yml`.** aws1 is the only node with a `-replace` target, but the question is pattern-level. Recorded on #1102 as a follow-up line item, not addressed here.
- **Fixing the stale claims in `provision-aws1.yml`'s header** (interruption behavior, `8 GB` EBS where the volume is 12 GB). Those are #1106's acceptance criteria. This spec must not cite that header as authority for anything.

## Risks / open questions

- **RESOLVED — the replaced node's address.** A concern that a new instance would get a new Tailscale IP and break the inventory. It does not: `ansible_host` for aws1 is `aws1.kubelab.internal`, a MagicDNS name (`common.yaml:329`, ADR-025), and the generator reads `tailscale_dns` in preference to `tailscale_ip` (`generator_ansible.py:136`). Verified against the generated hub inventory. No inventory edit is needed after a replacement.
- **RESOLVED — stale Headscale node records.** Re-registration without cleanup previously yielded `aws1-<random>` hostnames, which would break MagicDNS resolution. cloud-init already performs stale-node cleanup via the Headscale API key (lesson 2026-03-26). This spec relies on that and does not reimplement it.
- **OPEN, does not block implementation — the readiness signal is not just SSH.** `wait_for_connection` proves sshd answers. It does not prove cloud-init finished, and cloud-init owns K3s and the Tailscale registration that provisioning depends on. Provisioning too early would fail confusingly rather than dangerously. Task breakdown must decide whether to wait on `cloud-init status --wait` (authoritative, needs the connection first) or accept an SSH-only gate with a retry.
- **OPEN, blocks AC1's evidence tier, resolved below.** A real `make aws1-replace` is currently destructive and would very likely fail: aws1 is `stopped` after a Spot interruption with its persistent request `sir-xng7dfkh` open at `capacity-not-available`, so the target would cancel the queued restart, delete the root volume (`delete_on_termination = true`) and then be unable to create a replacement. Verification must not require an act this spec's own evidence argues against.

## Acceptance criteria

Evidence tiers are named deliberately. AC1–AC3 are the closing bar; AC4 is recorded as a known evidence gap rather than silently assumed, and is closed later by AC5 when a replacement is independently warranted.

- [ ] **AC1 — the chain runs unattended.** `make aws1-replace` performs readiness wait, `provision-aws1 ENV=hub` and `deploy-argocd` with no human step between them, and fails loudly if any stage fails (no `|| true` swallowing).
- [ ] **AC2 — the readiness wait is a poll, not a sleep, and is not inline Makefile shell.** Demonstrated by pointing the wait at an unreachable host and showing it times out with a diagnostic, rather than proceeding.
- [ ] **AC3 — provisioning genuinely installs the notify path on aws1.** Against the *restarted* instance once Spot capacity returns: `make provision NODE=aws1 ENV=hub TAGS=maintenance` reports `changed=0` on a second pass, and `make maintain-notify-test NODE=aws1 ENV=hub` returns `Result=success, ExecMainStatus=0`.
- [ ] **AC4 — staged verification is declared, not glossed.** `verification.md` states explicitly which segment of the chain has direct evidence and which does not: the Terraform replacement step will be exercised against a restarted rather than a replaced instance, so AC1–AC3 prove everything except that Terraform hands off to a node the wait can actually reach.
- [ ] **AC5 — full-cycle evidence, deferred.** A complete `make aws1-replace` ending with the timer enabled and `maintain-notify-test` green, run when a replacement is warranted on its own merits — #1106 predicts a concrete trigger, since a restart exhibiting the WireGuard/SSH corruption of the 2026-03-26 lesson makes replacement necessary rather than gratuitous. Tracked on #1102 after archive; **not** a blocker for this spec.

## References

- Bitácora board: `mlorentedev/kubelab#1102` (see the `issue:` frontmatter field)
- Coupled ticket: `mlorentedev/kubelab#1106` (ANSIBLE-043) — `stop` vs `terminate`; cites this spec as its prerequisite
- Prior art: `specs/archive/ANSIBLE-035-maintenance-timer-rollout/` — added the role to the playbook; this spec closes the path that never calls it
- `docs/lessons.md` — "Adding a role to a playbook does not install it on any path that never runs the playbook"
- `docs/adr/adr-023-*` (hub-and-spoke), `docs/adr/adr-025-*` (MagicDNS path resolution), `docs/adr/adr-028-*` (always-on vs on-demand)
