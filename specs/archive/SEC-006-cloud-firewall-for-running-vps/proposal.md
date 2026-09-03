---
id: "SEC-006-cloud-firewall-for-running-vps"
type: spec
status: archived # draft | implementing | verifying | archived
created: "2026-09-02"
issue: "mlorentedev/kubelab#1557"   # repo#NNN — GitHub issue / Project item that tracks this spec
# Work-gate note: scaffolded with --force-no-gate because `dotf spec init`'s Gate()
# uses `gh issue view --json` (GraphQL), and GraphQL was rate-limited for this
# account at scaffold time. The gate itself was SATISFIED and verified out-of-band
# via REST: `gh api repos/mlorentedev/kubelab/issues/1557` -> state "open".
# The mechanism was unavailable, not the gate. Tooling fix tracked in dotfiles.
tags: [spec, proposal]
template_version: "1.0"
---

# SEC-006-cloud-firewall-for-running-vps

> **Naming**: file lives at `<repo>/specs/SEC-006-cloud-firewall-for-running-vps/proposal.md`. `SEC-006-cloud-firewall-for-running-vps` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #1557: SEC-006: the Hetzner cloud firewall is declared and attached in Terraform but has never been applied — prod has none -->

The production VPS has **no cloud firewall**. Every inbound port that any process publishes is reachable from the internet, governed only by what happens to be listening. This was not a theoretical gap: SEC-005 (#1538) found `http://162.55.57.175:9000/api/overview` returning 200 to the public internet — Traefik's dashboard and API, serving the full routing topology — and three controls that should each have stopped it had all failed independently.

The two other controls are now understood and one is fixed (#1541 removed the exposure; #1548 guards it live). This spec addresses the third and worst, because it is the one that still *reads* as protection: `hcloud_firewall.vps` is declared in `infra/terraform/compute/`, so anyone auditing the repo concludes prod has a cloud firewall restricting inbound ports. It does not. A control that exists only in code is indistinguishable from a control that exists, right up until somebody checks — and it silently weakens every future decision that assumes a second layer is there.

If we do not ship this, prod's only inbound protection remains ufw, which **structurally cannot** cover a Docker- or klipper-lb-published port (#959: DNAT is evaluated in PREROUTING, before ufw's filter chains). That is not a partial defence; for published ports it is no defence.

## What

A new Terraform root module, `infra/terraform/vps-firewall/`, that manages **only** a Hetzner cloud firewall and its attachment to the already-running production VPS. Observable outcomes:

1. **A cloud firewall exists and is attached to the prod VPS.** Inbound traffic on any port outside the allow-list is dropped at Hetzner's edge, before it reaches the host — therefore before Docker's DNAT, which is what makes it succeed where ufw cannot.
2. **The VPS is never managed by Terraform.** The module reads the server through a `data` source and attaches via `hcloud_firewall_attachment` (present in the locally cached provider, v1.60.1, verified by inspecting the binary). The server never enters state: nothing to import, no `lifecycle { ignore_changes }`, and the plan's destroy count is structurally 0 because no managed resource can be replaced.
3. **A live guard proves it by consequence.** A check queries the Hetzner API for the firewall actually attached to the running server and fails when its rules do not match what is declared. Same shape as #1548 — the question is never "is it declared", it is "is it live".
4. **A Makefile entry point** (`tf-vps-firewall-plan` / `-apply`), because the repo's standing order forbids raw `terraform` outside the Makefile, and `compute/` being the only module without an entry point is part of how it stayed unexamined.

`infra/terraform/compute/` is not modified. It stays a recreate-only DR module per ADR-020.

## Out of scope

- **Modifying `infra/terraform/compute/`.** ADR-020 defines it as Layer 0 of the disaster-recovery bootstrap; it describes a world in which nothing exists yet. Importing the running VPS into it would convert DR into live management and contradict the ADR.
- **Migrating Terraform state to a remote backend.** Every root here is `backend "local"` — gitignored, machine-local, no locking. That is a real gap and the industry baseline is remote state with locking, but it is already tracked in #558 (evaluate backends), #559 (migrate if adopted) and #1499 (per-worktree DNS state). This spec inherits the constraint rather than fixing it.
- **Scheduled drift detection / alerting.** The live guard in AC-scope answers "is it right now". A periodic run that notices later drift and notifies someone is the fuller answer, but it adds scheduling, alert routing and an on-call path. Separate ticket.
- **Reconciling ufw with the cloud firewall.** They are different layers with different reach (#959). Making ufw's list agree with the cloud allow-list is desirable but is its own change.

## Risks / open questions

- **[MUST RESOLVE BEFORE CODE] The allow-list is declared twice and the two declarations disagree.** Measured:
  - `infra/ansible/roles/base_system/defaults/main.yml:47-51` (ufw): 22/tcp, 80/tcp, 443/tcp, 41641/udp — **four** ports.
  - `infra/terraform/compute/main.tf:53-91` (DR module): the same four plus **3478/udp** ("Headscale STUN") — **five**.

  Neither is a trustworthy SSOT. ufw's list is not ground truth because a ufw rule cannot restrict a Docker-published port anyway — Headscale publishes `3478:3478/udp` (`roles/headscale/templates/docker-compose.yml.j2:11`) with embedded DERP enabled and `stun_listen_addr: "0.0.0.0:3478"` (`config.yaml.j2:28`), so **3478 is reachable today despite ufw not listing it**. The DR module's list is closer to reality but has never been applied, so it has never been tested against anything.

  This matters far more here than for ufw: **a cloud firewall is enforced before DNAT, so unlike ufw it genuinely will block a published port.** Getting the list wrong is not a no-op — it is an outage. The port set must be derived from what is actually needed and published, and then declared once, in `common.yaml` under `networking.*`, per the repo's SSOT rule. Consuming it from two places afterwards is the point.

  **Resolved 2026-09-02 — 3478/udp stays in the allow-list.** Two facts settle it:

  1. **3478/udp is STUN, not the relay.** `config.yaml.j2:28` shows `stun_listen_addr: "0.0.0.0:3478"` as the block's only UDP listener; the embedded DERP relay itself is served over Headscale's HTTPS listener, which is 443 and already allowed. So blocking 3478 would not sever relaying — it would remove the NAT-discovery/latency probe for region 999, which in practice deprioritises the embedded region without breaking the public ones. `config.yaml.j2:32` also loads `controlplane.tailscale.com/derpmap/default`, so the public regions are available independently.
  2. ~~**Measured from msi (`tailscale netcheck`, 2026-09-02):** region `kubelab` is served and reachable at **167.5ms** — the slowest of every region offered — against Denver at 24.6ms, which is the nearest. From this client, connections are direct or public-relayed and the embedded region is never selected.~~

  **CORRECTED the same day, before the apply, by a better measurement.** Point 2 was a wrong inference from a right number. `netcheck` ranks regions by latency in order to choose *this client's* home region; a **relayed connection to a peer uses that peer's home region**, not the client's nearest. So a slow embedded region does not mean an unused one.

  `tailscale status --json` for the VPS peer, 2026-09-02: `Relay: "kubelab"`, `CurAddr: ""`. There is **no direct path** to the VPS from this client and traffic is relayed **through the embedded region**. It is in active use.

  The conclusion is unchanged and better supported: 3478/udp stays. What changes is why — it is load-bearing rather than merely conservative, and retiring the embedded DERP would move real traffic onto a public relay rather than tidying away something dormant. That ticket now needs its own evidence; this measurement is not it.

  **Scope limit, still stated deliberately:** this is one client's view. It says nothing about how ace1↔rpi4 or beelink↔vps reach each other, and the `relay "fra"` previously seen belonged to aws1, offline 10 days and destroyed — stale state. The correction above narrows what was claimed; it does not license the opposite claim about other peers.

  Therefore: SEC-006 preserves current behaviour. Making the perimeter real and changing what the perimeter allows are two changes, and coupling them would mean a VPN capability change shipping inside a security fix. Retiring the embedded DERP (`headscale_derp_enabled: false`, drop the compose publish, then drop 3478) is a separate ticket, for which the netcheck above is the evidence. Confirmed no existing DERP/STUN issue in the repo.

- **[MUST RESOLVE BEFORE CODE] Lockout.** Port 22 is in every candidate list, but the failure mode deserves naming: an allow-list applied with a mistake in the SSH rule locks every operator out of a machine whose recovery path (Headscale, on the same host) may also be blocked by the same mistake. Hetzner's web console is the out-of-band path and it must be confirmed reachable *before* apply, not discovered afterwards.

- **Name collision with the DR module.** `compute/` names its firewall `${var.project_name}-vps`. If this module uses the same name and the old firewall survives the disaster that triggers DR, the recreate collides on the name. Recording it now so it is not discovered during an actual recovery.

- **Token handling.** The module needs `hetzner.api_key` (in SOPS, `secrets_manager.py:131`). It must be injected into the child process, never printed — mirror however `tf-dns-plan` supplies the Cloudflare token rather than inventing a path, and never `make secrets-show`.

- **The `apply` is the first time this module has ever run against a real account.** `plan` is safe and reversible; `apply` creates and attaches. A human reads the plan.

## Acceptance criteria

- [ ] **AC1** — the inbound allow-list is declared **once**, in `common.yaml` under `networking.*`, and both the cloud firewall and ufw's `firewall_allowed_ports` read from it. The two lists cannot disagree again without the declaration changing.
- [ ] **AC2** — `terraform plan` for `infra/terraform/vps-firewall/` shows **0 to destroy** and no `hcloud_server` under management, run through a `tf-vps-firewall-plan` Makefile target. A human reads the plan before any apply.
- [ ] **AC3** — after apply, a port outside the allow-list (e.g. 9000, already closed at the Traefik layer by #1541) is **refused at the cloud edge**, verified from a non-tailnet path — the same verification method as #1548, not a config read.
- [ ] **AC4** — every port *inside* the allow-list still works after apply: SSH reachable, HTTPS serving, and the tailnet still forms (3478/udp is the one that would fail silently, degrading DERP rather than erroring).
- [ ] **AC5** — a live guard queries the Hetzner API for the firewall attached to the running server and fails when its rules do not match the `common.yaml` declaration. It must fail if the firewall is detached, deleted, or its rules edited out of band.
- [ ] **AC6** — re-running `apply` reports no changes (idempotent, `changed=0` equivalent).

## References

- Bitácora board: `mlorentedev/kubelab#1557` (see the `issue:` frontmatter field)
- `#1538` — SEC-005, the exposure this was the third failed control for
- `#1541` — the fix that closed the exposure at the Traefik layer (merged, deployed)
- `#1548` — the live guard whose shape AC3 and AC5 copy
- `#959` — why ufw could never have covered the port
- `#558` / `#559` / `#1499` — remote state backend, out of scope here
- ADR-020 — IaC Lifecycle Strategy; defines `infra/terraform/compute/` as DR Layer 0
- ADR-049 — Edge & Object-Storage Placement Doctrine (Hetzner Storage Box, relevant to #558)

<!-- archived 2026-09-02 — PR: https://github.com/mlorentedev/kubelab/pull/1574 -->
