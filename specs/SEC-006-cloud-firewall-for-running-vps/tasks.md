---
id: "SEC-006-cloud-firewall-for-running-vps"
type: spec
status: implementing
created: "2026-09-02"
issue: "mlorentedev/kubelab#1557"
tags: [spec, tasks]
template_version: "1.0"
---

# SEC-006 — tasks

Legend: `[ACn]` traces a task to its acceptance criterion in `proposal.md`.

## Setup

- [x] Worktree `~/Projects/kubelab-sec006-wt`, branch `feat/sec006-cloud-firewall-on-running-vps`, `make worktree-init` green.
- [x] Spec scaffolded. Work-gate #1557 verified OPEN via REST; `dotf spec init`'s GraphQL check was rate-limited, recorded in `proposal.md` frontmatter and filed as `mlorentedev/dotfiles#1452`.

## Implementation

- [x] **[AC1]** Declare `networking.firewall.vps_inbound` in `common.yaml` as the single inbound allow-list, with the reasoning inline: which two layers consume it, that ufw is not the control (#959), and that removing an entry drops live traffic at the cloud edge.
- [x] **[AC1]** Wire the ufw side: `provision.yml` sets `firewall_allowed_ports` from that key for the `vps` group only, via `set_fact` (outranks role defaults). Every other node keeps `base_system`'s fleet default — deliberately unchanged, since the VPS is the only node with a public IP.
- [x] **[AC1]** Repoint the existing SEC-005 guard (`test_traefik_ports_stay_behind_the_firewall.py`) at the new SSOT. It read `base_system`'s role default, which after this change answers for the fleet rather than for the VPS the test is about.
- [x] **[AC2]** `infra/terraform/vps-firewall/` — `data "hcloud_server"` + `hcloud_firewall` with rules from a variable + `hcloud_firewall_attachment`. The server is never a managed resource, which is what makes a replacement structurally impossible rather than merely unlikely.
- [x] **[AC2]** Input validation in `variables.tf`: refuse an empty rule list, refuse a list without `22/tcp`, refuse a proto that is not tcp/udp. An attached firewall with no rules locks every operator out of a host whose recovery path (Headscale) is on that same host.
- [x] **[AC1][AC2]** `toolkit infra terraform vps-firewall-tfvars` renders `.auto.tfvars` from the SSOT. Injects no secret — the allow-list is policy and belongs in a reviewable diff; the token travels separately in the child process's environment.
- [x] **[AC2]** `make tf-vps-firewall-plan` / `-apply`. No `-auto-approve` on the apply, deliberately: the failure mode is an operator locked out, not a degraded service.
- [x] **[AC5]** Static half of the guard (`test_vps_cloud_firewall_is_attached.py`): SSH present in the SSOT, ufw wired to the SSOT, module does not manage the server, DR module still declares itself DR.
- [x] **[AC5]** Live half: queries the Hetzner API for the firewall attached to the running server and compares its rules to the SSOT in both directions — a missing rule is a coming outage, an extra rule is an undeclared open port. Marked `infra`; run via `make test-vps-firewall-live`, which injects the token from SOPS rather than having anyone print it.
- [x] **[AC5]** Mutation-proved. M1 (drop 22/tcp) red, M2 (data source → managed resource) red, M3 (unwire ufw from the SSOT) red. Committed before mutating; working tree restored and `make test-fast` green afterwards — 1810 passed, 15 skipped.

## Blocked on the operator — not startable in this session

These are the post-apply half. None can be done before a human reads a plan and applies, because every one of them verifies a running system rather than a declaration, which is the entire premise of the spec.

- [ ] **[AC2]** `make tf-vps-firewall-plan`, and **a human reads the plan**. Proceed only if destroy count is 0 and the only change is the firewall plus its attachment. Note the module has never been `terraform init`-ed, so the first run also downloads the provider — expected, not a failure.
- [ ] **[AC2]** `make tf-vps-firewall-apply` once the plan is approved.
- [ ] **[AC3]** Verify by consequence from a **non-tailnet** path that a port outside the allow-list is refused at the cloud edge. Confirm the path really is non-tailnet first (`ip route get`), the way #1538 did — a check that leaves via `tailscale0` proves nothing about the public internet.
- [ ] **[AC4]** Verify every allow-listed port still works: SSH reachable, HTTPS serving, tailnet still forming. 3478/udp is the one that would fail quietly rather than loudly.
- [ ] **[AC6]** Re-run apply; assert no changes.
- [ ] **[AC5]** Run `make test-vps-firewall-live` against the applied state. This is also the first execution of the API accessors, whose response shape is asserted rather than assumed — if the shape is wrong it fails here naming the missing key, which is intended.

## Closing

- [ ] Confirm the plan output and the AC3 verification are recorded in `verification.md` as evidence, not as claims.
- [ ] Independent `adversarial-review` before archive — must not be the implementer.
- [ ] `#1557` closed with the change that closed it. Reference other ACs **without** a closing keyword: `Closes #N (AC1, AC2)` closes the whole issue, which bit #1538 and #1543 on consecutive days.

## Out of scope, tracked elsewhere

- `#1565` — SEC-005's port guard compares an empty set, found by mutation M4b during this work. Not fixed here: the correct fix means modelling the upstream chart's own defaults, which is a design decision rather than a drive-by.
- `#558` / `#559` / `#1499` — remote Terraform state with locking. This module inherits `backend "local"`.
- Embedded-DERP retirement. Measured 2026-09-02: the `kubelab` region answers at 167.5ms against 24.6ms for the nearest public one and is never selected from the client measured. **Scope limit, carried deliberately:** that is one client's view; it is not evidence about how other peers reach each other, and no such claim is made.
