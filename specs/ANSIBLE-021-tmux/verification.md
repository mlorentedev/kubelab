---
tags: [spec, verification]
created: "2026-08-18"
---

# Verification - ANSIBLE-021-tmux

> Written 2026-08-18, at archive time, against the live fleet — not at
> implementation time. The role change merged on 2026-06-30 and the spec then sat
> complete and unarchived for seven weeks, which is the state CI-GATE-011 (#1144)
> exists to stop. Everything below was measured today; nothing is carried over.

## Evidence

- [x] **AC1 — `base_system` defaults include `tmux`, single-line change** ->
  commit `46b9103`, *feat(ansible): install tmux via base_system role (#815)*,
  merged 2026-06-30. Verified to be exactly one insertion:

  ```
  $ git show 46b9103 --stat -- infra/ansible/roles/base_system/defaults/main.yml
   infra/ansible/roles/base_system/defaults/main.yml | 1 +
   1 file changed, 1 insertion(+)

  $ git show 46b9103 -- infra/ansible/roles/base_system/defaults/main.yml | grep '^[+-][^+-]'
  +  - tmux
  ```

- [x] **AC3 — smoke succeeds on every covered host that is up** -> 4 of 5. The
  spec's own command, run 2026-08-18:

  ```
  $ for h in ace1 ace2 aws1 beelink rpi4; do printf "%-9s " "$h"; \
      timeout 12 ssh -o ConnectTimeout=6 -o BatchMode=yes "$h" 'tmux -V'; done
  ace1      tmux 3.4
  ace2      ssh: connect to host 100.64.0.5 port 22: Connection timed out
  aws1      tmux 3.4
  beelink   tmux 3.4
  rpi4      tmux 3.4
  ```

  **ace2 is powered off**, not failing — `tailscale status` reports it `offline,
  last seen 2d ago`, and it is an on-demand node (ADR-028). Deferred under the
  spec's own closing clause ("or marked deferred — low risk"), and the deferral
  is bounded: ace2 runs `base_system` through `provision-ace2.yml` exactly as the
  four measured hosts do, so the only unproven step is the apt transaction, on
  the one host whose role membership is identical to four that passed.

- [x] **AC4 — Jetson NOT touched** -> proven by the smoke, not by inspection,
  which is the stronger of the two forms the criterion allows:

  ```
  $ ssh jet1 'tmux -V 2>/dev/null || echo "NOT INSTALLED"'
  NOT INSTALLED
  ```

  `provision-jetson.yml` contains no `base_system` and no tmux task.

- [~] **AC2 — provisioning is idempotent** -> **not re-measured, and deliberately
  so.** Re-running `make provision` across four live nodes to observe `changed:
  0` on a package that is already present would touch prod (aws1) and the whole
  homelab to prove a property of Ansible's `apt` module rather than of this
  change. The proposal itself ratified this: "Idempotency: apt module handles
  'already installed' gracefully. No risk." Recorded as accepted, not as done.

## Findings that outlived the spec

Both of the scope claims in `proposal.md` stopped being true between
implementation and archive, and **neither changed for the reason the spec
predicted**. Corrected in place there; the measurements are here.

**rpi3 is now covered, and #817 is not why.** `provision-rpi3.yml:105` runs
`base_system`, so rpi3 gets tmux (`tmux 3.5a`, measured). ANSIBLE-029 (#817) —
the ticket this spec named as the route — is **still OPEN**. The role arrived
with `3c9629b`, *fix(ansible): give rpi3 a host firewall via base_system
(#1059)*, on 2026-08-13, adopted for the firewall and taking the package list
with it. A boundary this spec drew moved because an unrelated change wanted a
different part of the same role.

**The VPS has tmux and is covered by nothing.** Measured `tmux 3.4`, while:

```
$ grep -n 'base_system' infra/ansible/playbooks/provision-vps.yml
433:    # Inline here rather than base_system's firewall_tailnet_ports (OPS-018):
434:    # the VPS never runs base_system (...)

$ grep -n 'tmux' infra/ansible/playbooks/provision-vps.yml
(no match)
```

So the package is present and **unmanaged**: nothing in IaC would reinstall it on
a rebuild, and no check would notice its absence. Presence is not coverage — the
distinction matters because a fleet-wide `tmux -V` sweep returns green on the
VPS and proves nothing about it. That is #817's subject rather than this spec's,
and it is reported there rather than fixed here.

## Test status

- `make test` -> see the PR that archives this spec. No test asserts `tmux` in
  `base_packages`, and none was added: a permanent assertion pinning one line of
  a package list is a change-detector, and the spoke-RBAC static test this repo
  does carry earned its place through a real prod refusal (#948). This did not.

## Decisions made during implementation

- The change shipped as a one-line addition to `base_packages` with no role
  restructuring, as scoped.
- Verification was left unrecorded for seven weeks. The spec was implemented,
  its two issues (#420 canonical, #814 working) were closed, and nothing asked
  the closing question — which is exactly the gap #1143 now gates and #1144 now
  makes visible for specs that declare no `issue:` at all. This spec was one of
  the four blind ones.

## Promotion candidates

- **A scope boundary can be invalidated by a change that never read the spec.**
  Two of this spec's exclusions were reversed by #1059 and by whatever installed
  tmux on the VPS — neither aware of ANSIBLE-021. A spec's "not covered by this"
  is a statement about the world at a date, not a durable guarantee, and the
  only way it stays true is a test or a re-measurement at archive time.
- **Presence is not coverage.** The VPS passes any `tmux -V` check and is
  managed by nothing.

## Archive checklist

- [x] Tracking issue declared in `proposal.md` frontmatter (`kubelab#420`)
- [x] Acceptance criteria dispositioned — done, deferred, or accepted, each with
      a reason
- [x] Stale scope claims corrected against measurement, with dates
- [x] Findings routed: the VPS gap reported on #817, which is open and is about
      exactly that
