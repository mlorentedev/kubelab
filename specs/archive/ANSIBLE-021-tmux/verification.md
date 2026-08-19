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
      exactly that; the review's naming finding filed as #1158
- [x] Independent adversarial review: `review.md`, PASS WITH GAPS, signed
      `nan/deepseek-v4-flash` — not the model that reconciled this spec
- [x] Promotion candidates executed, not left as intentions:
      `docs/lessons/ansible-provisioning/lesson-349-*` (presence is not coverage)
      and `docs/lessons/process-method/lesson-350-*` (a scope boundary is a claim
      about a date)

## Adversarial review — findings and their disposition

`review.md`, `nan/deepseek-v4-flash`, 2026-08-18, verdict **PASS WITH GAPS**: five
Minor findings, no Blocker and no Major, reviewer's own recommendation "running
`dotf spec archive` is advisable with the current review". Each finding is
dispositioned below rather than inherited by the archive.

`verification.md` is deliberately the only file changed after the review. The
staleness gate's contract is `proposal.md`, `tasks.md` and `features.json`
(`cli/internal/spec/review.go:24`), so recording dispositions here does not
invalidate the verdict — and nothing below alters what the reviewer judged.

**1. AC2 idempotency was not evidenced — APPLIED, by a different method.**
The reviewer proposed `apt-get install -y tmux; echo $?`. That closes the gap by
*performing an install* on four live hosts, one of them prod, to prove an install
would do nothing. The simulation flag answers the same question and mutates
nothing:

```
$ for h in ace1 aws1 beelink rpi4; do printf "%-9s " "$h"; \
    ssh "$h" 'apt-get -s install tmux 2>/dev/null | grep -E "^[0-9]+ upgraded"'; done
ace1      0 upgraded, 0 newly installed, 0 to remove and 44 not upgraded.
aws1      0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.
beelink   0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.
rpi4      0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.
```

`0 newly installed` on every reachable covered host: a re-run changes nothing.
(ace1's "44 not upgraded" is unrelated pending updates on other packages, not
this one.)

**Corrected 2026-08-19, and the correction is the more useful record.** This
paragraph first concluded "AC2 moves from *accepted* to *evidenced*", which
contradicted the `[~]` entry above it and overstated what was measured. AC2 says
*provisioning* is idempotent — a property of the whole `base_system` run. What
`apt-get -s` proves is that the **apt task** would no-op, which is necessary and
not sufficient: the role also templates, sets sysctl and configures a firewall,
and none of that was re-run. AC2 therefore stays **accepted, now with
package-level supporting evidence**, and the `[~]` entry above stands unchanged.

Raised by CodeRabbit on #1156 — *"do not promote package-manager simulation to
full provisioning evidence without changing the criterion"* — and it is right.
The overclaim substituted a narrower measurement for a broader claim, in the same
document that promotes "presence is not coverage" as a lesson. The uncorrectable
residue: the original wording is also in #1156's body, which the squash made
master's commit message permanently. It is corrected here and on that PR.

**2. Naming inconsistency, `beelink` vs `provision-bee.yml` — TICKETED as #1158,**
and it is wider than the review found. `make provision` resolves the playbook by
interpolation (`-p provision-$(NODE)`), so `NODE=beelink` fails while the node's
real hostname *is* `beelink`. Beyond that, three hand-maintained node lists in the
Makefile disagree, and the one printed on a wrong invocation — `Makefile:691` —
omits `bee`, `rpi3` and `jetson` entirely. The error path teaches a smaller fleet
than the one that exists, to the reader least able to know better. Out of scope
here: this spec's diff is one line of a package list, and renaming a playbook is
not a drive-by.

**3. Scope boundary invalidated by an unrelated change — DECLINED as work,
recorded as a lesson.** Already corrected in `proposal.md`, and the reviewer's
real observation is the one under it: "UNTESTED — no test asserts any scope
boundary". True, and a test would not have helped. The boundary was prose about
the world on a date, and #1059 changed the world without reading it. What catches
this class is re-measuring at archive time, which is what caught it. Kept as a
promotion candidate above rather than converted into an assertion that would pin
`provision-rpi3.yml` for the wrong reason.

**4. ace2 unverified — DECLINED, bounded.** It is powered off, not failing, and it
is an on-demand node: nothing can measure it until it is next booted. The AC says
"every covered host", and this is a deferral against that, stated rather than
quietly satisfied by rewording the criterion. The bound is that ace2's role
membership is identical to four hosts that passed, so the only unobserved step is
an apt transaction whose no-op behaviour is now evidenced on all four.

**5. No test pins `tmux` in `base_packages` — DECLINED, reasoning unchanged.**
The reviewer grades this defensible and it is the position already argued in "Test
status" above: an assertion over one line of a package list is a change-detector,
and the static test this repo does carry (`test_spoke_rbac_covers_manifests.py`)
earned its place through a real prod refusal. A future deletion of the `tmux` line
would indeed go unnoticed by CI — and would surface as `sshmux` falling back to
plain SSH, which is the symptom the spec exists to fix and is self-announcing.
