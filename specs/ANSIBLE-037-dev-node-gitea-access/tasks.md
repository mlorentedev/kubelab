---
tags: [spec, tasks]
created: "2026-09-01"
---

# Tasks - ANSIBLE-037-dev-node-gitea-access

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers:**
> - `[P]` — no dependency on another unchecked task, safe to run in parallel.
> - `[AC<n>]` — helps satisfy acceptance criterion #`<n>` from `proposal.md`.

> **Read [ADR-062](../../docs/adr/adr-062-platform-identity-model.md) D1 first.** It supplies this spec's D1: ace2 provisions the machine identity, and the human half needs no provisioning at all.

## Setup

- [x] Branch created from origin/master: `feat/ansible-037-dev-node-gitea-access` ✓ 2026-09-01
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-09-01 — D1 (machine identity) and D2 (per-node key, not the shared token) recorded with the constraints that force them
- [ ] No open questions left in `proposal.md` "Risks / open questions" — R1, R2 and R3 are all settled by observing live instances, never by reading a template. Part 0 exists to close them. **R1 in particular gates the design**: it decides SSH vs HTTPS, and those have materially different blast radii.

## Implementation

### Part 0 — settle the transport and the credential's live behaviour, before writing any role

Nothing here changes provisioned state. Each task turns a guess into a recorded fact, and R1 can invalidate every task in Part 1 — which is why it comes first rather than being discovered mid-implementation. **All of these need ace2 and the Beelink powered on** (R4), and the Gitea port is bound to the Tailscale IP, so they must be run over the tailnet, not LAN addressing.

- [x] **R1 — is Gitea's SSH path usable from ace2 at all?** ✓ 2026-09-02 — **YES; D2 stands, the HTTPS fallback is not taken.** `r1_transport_probe.sh` from ace2: port 2222 OPEN, server identifies as **OpenSSH_10.0** (the official image's, on container port 22), host-key exchange completed (ED25519 added to ace2's `known_hosts`), and auth refused with `Permission denied (publickey)` — a working transport missing only the key this role will register, not the empty published port the compose template's own comment warned about. Transcript in `verification.md`. Original text follows. From ace2, over the tailnet: `ssh -T -p <gitea_ssh_port> git@<beelink tailscale ip>`, plus a `nc -z` on the port to separate "nothing listening" from "listening and rejecting". The compose template publishes `{{ tailscale_ip }}:{{ gitea_ssh_port }}:22` against the official image's OpenSSH, but its own comment records that the K8s manifest it replaced published a port with **nothing behind it**, so the advertised clone URL had never connected — the precedent for measuring rather than reading. Record the transcript in `verification.md`. **This is the decision task: SSH keeps D2 as written (a registered per-node key, repository-only blast radius); HTTPS falls back to a scoped token at rest on the node, which is a different security posture and must be re-recorded in `proposal.md` D2 rather than silently adopted.**
- [ ] [P] **R2 — does the image's OpenSSH honour a key registered through Gitea's API for `hefesto`?** The account is deliberately not `prohibit_login` (AUTH-004 Part 3 measured that the flag kills API-token auth too), so it is a normal account with a password nobody holds. Register a throwaway key via `POST /user/keys`, attempt git transport with it, remove it. Do this before the role assumes the API write is sufficient.
- [ ] [P] **R3 — does key removal fail closed, and immediately?** AC4 asserts it does. `DELETE /user/keys/{id}`, then retry the transport within the same minute. Gitea may cache `authorized_keys`; if there is a delay, AC4's test must wait for it explicitly rather than racing it.
- [ ] Record all three answers in `verification.md` under a `## Open questions, settled` heading, each with the command run and its output. A settled question with no transcript is an assertion.

### Part 1 — the role provisions the node's credential

Written only after R1 chooses the transport. Tests first: the Ansible-path guard is `tests/test_ansible_identity_ssot.py`'s sibling pattern — AUTH-004 learned that one decision with two delivery paths survives on the leg that has a test and rots on the leg that does not.

- [ ] [P] [AC2] Write failing test: the role resolves the identity from `apps.auth.identities.machine`, not from a literal, not from `basic_auth.user`. Assert on the rendered result, not on the template source, so it survives a refactor of how the value is plumbed. **Demonstrate it red first.**
- [ ] [AC2] Implement the resolution in `roles/dev_node`, and register anything secret in `SECRET_CATALOG` — **check `envs` against the ANSIBLE-033 failure mode**: a tuple matching no real env makes the secret vanish from every audit silently. Note the forge's identity environment is **prod** (`gitea_identity_env`), even though ace2 is provisioned with `deploy_env=staging`.
- [ ] [P] [AC3] Write failing test: the Gitea host key is pinned by the role, so a first connection cannot produce an interactive prompt. Trust-on-first-use is a manual step by another name.
- [ ] [AC3] Implement host-key pinning.
- [ ] [AC1] Implement the credential delivery and git configuration so a clone works with no per-repo setup, per R1's chosen transport.
- [ ] [AC1] Confirm idempotence: a second `make provision NODE=ace2 ENV=staging` reports `changed=0`. This is the repo's standing bar, not this spec's invention.

### Part 2 — evidence, on live nodes

- [ ] [AC1] Clone and push to a real Gitea repository from ace2, with the transcript in `verification.md`. **Sequencing: this needs a repository to exist**, which is TOOL-035 (#1076), currently blocked on the operator minting `apps.services.core.gitea.admin_token` (`make secrets-audit` → prod 76/78, this is one of the two gaps). Everything above can be built and unit-tested before that lands; only this task waits.
- [ ] [AC4] Remove the node's key from Gitea, confirm the access fails, re-provision, confirm it is restored. **Both halves captured** — a credential that works proves only half the claim (AUTH-004 AC5's finding, where an account-level rejection and a scope-level one returned the same status code and voided an entire check).
- [ ] [AC6] Demonstrate the operator's own interactive access from ace2 through agent forwarding, with **no key of theirs on the node** — `ssh -A ace2` then a push attributed to `manu`. This is what makes D1's "the human half needs no provisioning" a measurement rather than a claim; if it fails, D1 needs revisiting, not working around.

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] `make test` green, and `make test-infra ENV=staging` shows no new failures
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] Any gotcha that outlived the change is in CLAUDE.md or `docs/lessons/`
- [ ] Board ticket #1075 reflects reality
- [ ] PR opened referencing this spec folder; `adversarial-review` before `/spec archive`
