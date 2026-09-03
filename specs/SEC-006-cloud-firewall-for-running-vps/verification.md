---
tags: [spec, verification, templates]
created: "2026-09-02"
---

# Verification - SEC-006-cloud-firewall-for-running-vps

Everything below was produced against the running production VPS on 2026-09-02,
after the operator applied. Where a claim could be made from the repository or
from the provider, it is made from the provider — that distinction is the whole
subject of this spec.

## The premise, established at the source

Before the apply, asked the Hetzner API directly rather than inferring from a
missing local state file (`backend "local"`, gitignored — absence on one disk
proves nothing):

```
servers in this project: 1
  name='mlorente-01' id=61231002 ipv4=162.55.57.175 status=running firewalls=[]
firewalls in this project: 0
```

**Production had no cloud firewall.** Not a lapsed apply — none had ever existed.

## Evidence

- [x] **AC1 — the allow-list is declared once.** `networking.firewall.vps_inbound`
  in `common.yaml`. Consumed by `infra/terraform/vps-firewall/` (via
  `toolkit infra terraform vps-firewall-tfvars`) and by `provision.yml`, which
  sets `firewall_allowed_ports` from it for the `vps` group only. Commits
  `a028446f`, `5465a873`. Guarded by
  `test_the_ansible_side_reads_the_ssot_rather_than_its_own_copy`; mutation M3
  (unwire the playbook) → red.

- [x] **AC2 — plan shows 0 to destroy and no managed server.**

  ```
  Plan: 2 to add, 0 to change, 0 to destroy.
    + hcloud_firewall.vps             "kubelab-vps-inbound", 6 rules
    + hcloud_firewall_attachment.vps  server_ids = [61231002]
  ```

  Read by the operator before applying, through `make tf-vps-firewall-plan`. The
  server is a `data` source, so a replacement is structurally impossible rather
  than merely unlikely — asserted by `test_the_module_does_not_manage_the_server`;
  mutation M2 (`data` → `resource`) → red.

- [x] **AC3 — a port outside the allow-list is refused at the cloud edge.**
  Verified by the same port flipping state, from the same path, before and after:

  | | before apply | after apply |
  |---|---|---|
  | `8080/tcp` | **`200 OK`** (plaintext HTTP) | **timeout** |
  | `9000/tcp` | timeout | timeout |
  | `5000/tcp` | — | timeout |

  Path confirmed non-tailnet immediately before each measurement:
  `ip route get 162.55.57.175` → `via 10.0.0.1 dev wlp1s0`, not `tailscale0`.

  **9000 is useless as a probe and that matters** — #1541 already closed it at
  the Traefik layer, so it times out with or without a firewall. 8080 is the
  only port that changed state, because Headscale keeps listening on it
  regardless. A before/after on 9000 would have "passed" while proving nothing.

- [x] **AC4 — everything inside the allow-list still works.**

  ```
  22/tcp            succeeded
  80/tcp            succeeded
  443/tcp           succeeded
  6443              HTTP 401          (auth holds; reachable)
  vpn.kubelab.live  HTTP/1.1 200 OK
  ```

  `kubectl --kubeconfig ~/.kube/kubelab-prod-config get nodes` →
  `kubelab-vps Ready control-plane 166d v1.34.4+k3s1`.

  Tailnet identical to the pre-apply baseline: `Relay: "kubelab"`, `CurAddr: ""`,
  `Online: true`.

  `vpn.kubelab.live` returning 200 is the live test of the argument for leaving
  8080 out: K3s Traefik reaches Headscale at the host's own public IP from the
  same host, which the kernel delivers locally and never sends to Hetzner's edge.
  That was reasoning at plan time and is a measurement now.

  Monitoring impact settled **before** the apply rather than by watching the
  dashboard after: all 37 Uptime Kuma monitors read from
  `infra/config/uptime-kuma/monitors.json` (config-as-code since OPS-016). No
  monitor pings the public IP; the only ICMP check against the VPS targets
  `100.64.0.2`, which rides inside WireGuard where the cloud firewall never sees
  it. The two that do reach the public IP use 22 and 443.

- [x] **AC5 — a live guard fails when the firewall is absent, detached or edited.**
  `tests/test_vps_cloud_firewall_is_attached.py::TestTheFirewallIsLive`, run via
  `make test-vps-firewall-live`, which injects the token into the child process.

  **Run before the apply it FAILED**, with `assert []` — *"the production VPS
  (mlorente-01) has NO cloud firewall attached"*. Run after, it **PASSED**. Same
  test, same command, opposite verdict, and the only thing that changed was
  production. A guard first observed passing has never been observed disagreeing
  with anything.

  Rules read back from Hetzner, not from the config:

  ```
  firewall 'kubelab-vps-inbound'  applied_to=[61231002]
     in  tcp  port=22     in  tcp  port=80     in  tcp  port=443
     in  udp  port=3478   in  tcp  port=6443   in  udp  port=41641
  ```

  Six rules, all `in`, **zero `out`** — so egress is unrestricted, which is
  Hetzner's documented default with no outbound rules and was checked before
  writing the module: breaking egress would have taken ACME, image pulls and the
  tailnet with it.

  Continuous half: one Uptime Kuma monitor,
  `Infra · Sec · VPS firewall holds (8080 shut)` — `port` type on
  `162.55.57.175:8080` with `upsideDown: true`, up when the check *fails*. The
  first of the now-38 monitors to ask whether something is **closed**; the other
  37 all ask whether something is up, which is exactly why 9000 could answer the
  internet for months with every monitor green.

- [x] **AC6 — idempotent.** Re-plan after apply:
  `No changes. Your infrastructure matches the configuration.` The em-dashes in
  the rule descriptions survive the round-trip; no perpetual `~ description` diff.

## Test status

- `make test-fast` → **1811 passed, 15 skipped, 161 deselected**. No regressions.
  (It was red on arrival: the previous commit bumped the lessons category index
  and left the corpus total at 412 against 413 files. Fixed in `5edc6a7e`.)
- `make test-vps-firewall-live` → 1 passed (was 1 failed pre-apply — see AC5).
- `make monitoring-apply` → converged, then `0 create, 0 edit, 0 delete` on
  re-run.

## Decisions made during implementation

- **AC1 of #1557 was withdrawn before any code was written.** It asked whether
  `infra/terraform/compute/` is meant to manage this VPS; `compute/main.tf:1-4`
  and ADR-020 had already answered no. That AC was written from lines 50 and 105
  without line 3 — the same misreading that produced #1538's analysis. Corrected
  on the issue, and the module became attach-only as a result.

- **Three defects surfaced in the first ninety seconds against a live account**,
  after 1810 passing tests and a full static review. Each is this spec's thesis
  applied to itself: (1) a variable `description` naming `${project_name}` in
  prose, which HCL expanded, so the module could not `init`; (2) `hetzner.api_key`
  held 32 characters where a Hetzner Cloud token is 64 — declared since the
  catalogue was written, never exercised, because this spec is its first
  consumer; (3) the server lookup used `networking.vps.hostname` (the **OS**
  hostname) while Hetzner calls the machine `mlorente-01`.

- **Identity is bound to the IP, not the name.** A `precondition` on the
  attachment asserts the resolved `ipv4_address` equals `networking.vps.public_ip`.
  Mutation M8 (point it elsewhere) → the plan refuses, printing both addresses.
  Both Terraform variables lost their defaults: a plausible-looking default is
  how the lookup was silently wrong.

- **6443 in, 8080 out.** Both answered the internet and neither was declared.
  6443 stays because the prod kubeconfig uses it and preserving behaviour is the
  same reasoning that kept 3478; closing it is a capability change with its own
  ticket. 8080 — Headscale's control plane in plaintext HTTP — is unintended
  exposure rather than a capability, and is now shut.

- **A claim of mine was withdrawn mid-spec.** The justification for 3478 said
  `netcheck` showed the embedded DERP region slowest and therefore "never
  selected". Wrong inference: `netcheck` ranks regions to pick *this client's*
  home region, but a relayed connection uses the *peer's*. `tailscale status`
  shows the VPS reached via `Relay: "kubelab"`. Decision unchanged, reason
  replaced — 3478 is load-bearing, not conservative.

- **Two incidental corrections, both the same shape as the main finding.** The DR
  runbook instructed `sops -d <whole file> | yq`, which decrypts everything and
  filters only what a human reads; replaced with a single-key extraction. And
  `toolkit monitoring apply`'s docstring claimed it "deletes all existing
  monitors and recreates", describing behaviour OPS-016 had replaced with a
  keyed upsert that preserves uptime history — an error in the direction that
  stops people using the codified path.

- **`make monitoring-apply` deleted `Staging · Web · Homepage Staging`.** Not
  collateral: #1317 replaced it with `Prod · Web · Homepage Cockpit` in the seed
  and nobody ever ran the sync, so the instance kept the old monitor and
  `home.kubelab.live` **had no monitor at all**. The sync executed a decision
  that had been declared and unapplied for months — the same failure as the
  firewall, in a different subsystem.

## Promotion candidates

- [x] Lesson — already written before the apply:
  `docs/lessons/gitops-delivery/lesson-417-an-unapplied-iac-module-is-read-as-a-control.md`.
  A second lesson is warranted on what this session added to it: **a control's
  own credential is part of the control**, and every signal around
  `hetzner.api_key` was green over a value that could not authenticate. That is
  lesson 413's rule (verify by consequence) meeting 417's (a declaration is not a
  deployment) — the credential *and* the module were declared, and neither had
  ever been exercised.
- [ ] ADR — no. Attach-only is an implementation of ADR-020's existing split, not
  a new decision.
- [ ] Pattern — not yet. Recurs across subsystems within this project (firewall,
  credential, monitor seed) but has not been observed in a second project.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/SEC-006-cloud-firewall-for-running-vps/` -> `specs/archive/SEC-006-cloud-firewall-for-running-vps/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Independent `adversarial-review` — must not be the implementer, and is
      required before archive because this change closes a spec.
- [ ] Promotions above executed
