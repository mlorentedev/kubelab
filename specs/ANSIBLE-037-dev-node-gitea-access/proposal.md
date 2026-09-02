---
id: "ANSIBLE-037-dev-node-gitea-access"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-09-01"
issue: "mlorentedev/kubelab#1075"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# ANSIBLE-037-dev-node-gitea-access

## Why

<!-- from issue #1075: ANSIBLE-037: dev_node has no provisioned git access to Gitea -->

The `dev_node` role provisions ace2 as the self-hosted CDE ([ADR-058](../../docs/adr/adr-058-ace2-dev-node.md) D1) and Gitea runs on the Beelink as the private forge ([ADR-061](../../docs/adr/adr-061-stateful-service-placement.md)), but nothing connects them: `grep -riE "gitea|git_remote|ssh_key|known_hosts" infra/ansible/roles/dev_node/` returns zero results, re-verified 2026-09-01. So the workflow both nodes exist to support has no provisioning path, and doing it today means configuring git credentials by hand on ace2 — the non-reproducible path this project rejects everywhere else, leaving no record of which key can reach the forge.

## What

After this change, `make provision NODE=ace2 ENV=staging` leaves ace2 able to clone and push to a Gitea repository with no manual step, and a second run reports `changed=0`. The credential is the node's own, resolved from the identity SSOT, and removing it from Gitea makes the access fail until the node is re-provisioned.

### D1 — the node authenticates as the machine identity, not as a human

**Decision: ace2 provisions `hefesto` (`apps.auth.identities.machine`).** #1075 asks for this to be recorded rather than assumed, and the constraints already settle it:

- **A fourth identity is excluded.** #1075 states the role "must not invent a third credential path", and its AC2 requires the credential resolve from the identity SSOT. `apps.auth.identities` declares exactly three keys — `superadmin: manu`, `operator`, `machine: hefesto` — so a node-specific identity would mean amending [ADR-062](../../docs/adr/adr-062-platform-identity-model.md) D1, which is out of scope here.
- **A named human's key must not live on the node.** #1075's AC1 requires clone/push with no manual step, which means a credential at rest on ace2. ADR-062 D1 makes a named human account personal and accountable; a private key sitting on an on-demand shared node satisfies neither, and any agent running there would then sign as the human. R2 also measured that `manu` is the forge's **sole admin account** (uid 1), so this is the worst credential to place on a node.
- **The machine class already describes exactly this.** ADR-062 D1 defines the machine class as an agent running on a node with a scoped token and no interactive login. The Vikunja runbook already states that on-demand dev nodes pull delegated tasks on boot. ace2 acting as `hefesto` is the model working, not identity sharing.

**The human half needs no provisioning at all,** which is what dissolves #1075's "a human and an agent should not share a key" concern rather than trading it off: R2 measured that `manu`'s Gitea account already carries an SSH key (`msi-workstation`). Interactive work from ace2 uses SSH agent forwarding from the workstation, so the operator's pushes remain attributable to them and no key of theirs is ever written to the node. This spec provisions only the machine path.

### D2 — a per-node key on the bot's account, not the shared API token

The bot's API token (`apps.services.core.gitea.bot_token`) carries `write:repository,write:user` and is the credential the Beelink provisioning already holds. Copying it to ace2 would put a `write:user`-scoped credential on an on-demand node and make revocation all-or-nothing.

Instead the role registers a **per-node SSH key** on `hefesto`'s account (`title: ace2-dev-node`), using the existing token only at provision time, from the control machine. Blast radius on the node becomes repository-only, and #1075's AC4 ("removing the key from Gitea makes the access fail, and re-provisioning restores it") maps directly onto `POST` / `DELETE /user/keys`.

## Out of scope

- **Provisioning any human identity on ace2.** Agent forwarding covers it; see D1.
- **Getting repositories into Gitea** — that is TOOL-035 (#1076), and it is what makes this spec's verification possible, not part of it.
- **CI on the forge.** Gitea Actions is #504 / TOOL-035 AC6-AC7. "Develop" here means clone, push and PRs.
- **Agent task-pull (`tk task sync`).** This spec provisions the credential an agent would use; it does not implement the agent's task loop.
- **Changing `hefesto`'s account state.** Its creation, scope and the `prohibit_login` gap are AUTH-004 Part 3, already recorded there as a named gap.

## Risks / open questions

Every one of these is settled by observing a live instance, never by reading a template. Do not write the role against a guess — the same discipline AUTH-004's Part 0 used for R1-R6.

- **R1 — is Gitea's SSH path actually usable from ace2?** The Beelink compose publishes `{{ tailscale_ip }}:{{ gitea_ssh_port }}:22` (the official image's OpenSSH) and advertises it through `GITEA__server__SSH_DOMAIN`, so on paper it works over the tailnet. **But that same template records the precedent for not trusting it**: the K8s manifest it replaced "set `SSH_LISTEN_PORT=2222` without enabling that server, so nothing was listening on the port it published — one of the reasons its advertised clone URL had never connected." Settle with a live `ssh -T` from ace2 before choosing the transport. **Fallback if it fails: HTTPS with a git credential helper**, which is the known-working path (#1389 AC2 tested an authenticated clone over HTTPS) and would change D2 from a registered SSH key to a scoped token at rest — a materially different blast radius, which is why the transport is a gate rather than a detail.
- **R2 — does the image's OpenSSH honour keys registered through Gitea's API for this account?** `hefesto` is deliberately *not* `prohibit_login` (AUTH-004 Part 3 measured that the flag kills API-token auth too), so it is a normal account holding a password nobody knows. Confirm the key it registers is actually accepted for git transport.
- **R3 — does key removal fail closed, immediately?** AC4 asserts it does. Gitea may cache `authorized_keys`; measure the revocation rather than assuming the API write is the whole story.
- **R4 — both nodes are on-demand.** ace2 and the Beelink must be powered for every probe here, and the Gitea port is bound to the Tailscale IP, so LAN addressing will not reach it. Not a design risk; a scheduling one that has already blocked verification elsewhere this cycle.

## Acceptance criteria

- [ ] **AC1** — a fresh `make provision NODE=ace2 ENV=staging` leaves ace2 able to clone and push to a Gitea repository with no manual step, demonstrated by a transcript; a second run reports `changed=0`.
- [ ] **AC2** — the credential resolves from `apps.auth.identities`, not hardcoded in the role, and anything secret about it is registered in `SECRET_CATALOG` with `envs` checked against the ANSIBLE-033 failure mode.
- [ ] **AC3** — the Gitea host key is pinned by the role; a first connection produces no interactive prompt, demonstrated on a node whose `known_hosts` was cleared.
- [ ] **AC4** — removing the node's key from Gitea makes the access fail, and re-provisioning restores it. Both halves captured; a credential that works proves only half the claim (AUTH-004 AC5's finding).
- [ ] **AC5** — R1 is answered by a live probe and the chosen transport recorded in `verification.md` with its transcript, before the role is written.
- [ ] **AC6** — the operator's own interactive access from ace2 is demonstrated to work through agent forwarding with no key of theirs on the node, confirming D1's claim rather than asserting it.

## References

- Bitácora board: `mlorentedev/kubelab#1075`
- [ADR-062](../../docs/adr/adr-062-platform-identity-model.md) — platform identity model; D1's four identity classes decide this spec's D1
- [ADR-058](../../docs/adr/adr-058-ace2-dev-node.md) — ace2 as the on-demand developer node / CDE
- [ADR-061](../../docs/adr/adr-061-stateful-service-placement.md) — why Gitea runs on the Beelink in Compose
- `specs/AUTH-004-identity-and-machine-access/` — Part 3 provisioned `hefesto`; its `verification.md` holds R2's account inventory and R4's `prohibit_login` measurement
- #1076 (TOOL-035) — puts repositories in the forge; this spec's AC1 needs one to clone
