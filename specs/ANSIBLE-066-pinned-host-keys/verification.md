---
tags: [spec, verification]
created: "2026-10-14"
---

# Verification - ANSIBLE-066-pinned-host-keys

## Evidence

- [x] AC1: commit `c490e717`. `test_every_stable_host_is_verified_against_the_pinned_file[mesh|bootstrap]` and `TestTheSsotDeclaresThePinnedFile` use the real `common.yaml`.
- [x] AC2: `TestTheHubException::test_a_node_replaced_by_design_keeps_accept_new` and `::test_declaring_an_address_makes_it_stable`, both with a fixture that adds and then removes `tailscale_ip`.
- [x] AC3: `TestBastion::test_the_jump_and_the_hop_use_the_pinned_file` and `::test_the_hub_keeps_its_exception_on_the_proxied_hop_only`.
- [x] AC4: `TestRunRefusesWithoutThePinnedFile::test_a_missing_file_stops_the_run_and_is_named` and `::test_a_present_file_lets_the_run_through`. Code: `_missing_known_hosts_file` in `toolkit/cli/infra.py`.
- [x] AC5: `test_the_committed_inventory_never_trusts_on_first_use`.
- [x] AC6: live from macmini, 2026-10-14, after mlorentedev/dotfiles#2465 merged and `dotf converge --only configs-deploy` deployed the pins. `ssh-keygen -lf ~/.ssh/known_hosts_pinned` lists 10 lines, the six homelab hosts included.
  - Positive. `ansible all -m ping` against `generated/{staging,prod}/hosts.yml` (global `StrictHostKeyChecking=yes`, `UserKnownHostsFile=~/.ssh/known_hosts_pinned`). The prod run was repeated with `ControlMaster=no ControlPath=none`, so every node opened a new session. The inventory emits seven stable hosts. ace1, ace2, beelink, rpi3, rpi4 and kubelab-vps answered `SUCCESS` to `ping`.
    - jetson, a deviation from AC6's wording (`ping` on every stable node): the `ping` module fails on its Python 3.6 (Ubuntu 18.04, which is why its roles use `raw`), after the SSH session, and therefore the key check, had succeeded. `-m raw -a true` returns `rc=0`.
    - gcp1: `SUCCESS` with the inventory's own per-host `accept-new`. It was `UNREACHABLE` only when the override forced strict checking on it, which shows it is not pinned, as designed.
  - Negative. In a copy of the pinned file, rpi3's line carried beelink's key, with multiplexing off. rpi3 failed with `REMOTE HOST IDENTIFICATION HAS CHANGED`; beelink in the same run answered `pong`.
- [x] AC7: `docs/runbooks/add-a-node.md`. The `wait-node-ready.yml` comments are corrected, and `tests/test_wait_node_ready_host_key.py` was updated with them.

## Test status

- `make test-fast`: 4595 passed (2026-10-14, after `platform.json` was regenerated).
- Manual smoke test: AC6 above.
- No regressions in the existing test suite: yes.

## Decisions made during implementation

- The hub exception is derived from the node's SSOT shape (`tailscale_dns` without `tailscale_ip`), not from a name list, so a second node built the same way inherits it and a hub given a fixed address loses it.
- On the first negative run, rpi3 passed because it reused the ControlMaster socket left by the previous ping. Multiplexing was disabled for the evidence runs (lesson-569).

## Review dispositions

The adversarial review (`review.md`, nan/deepseek-v4-flash, PASS-WITH-GAPS, at `fa2da338`):

1. Major, multiplexing (`ControlMaster=auto`, `ControlPersist=60s`): **accepted, not changed.** A reused socket is the encrypted connection already opened to the host whose key was verified, so it cannot reach any other machine, even if the address changes inside the window. What it defeats is a test that edits the pinned file and reconnects within 60 s, which lesson-569 records. Turning multiplexing off for every run would trade that for a much slower Ansible with no security gain.
2. Minor, runbook step 4: **applied.** `add-a-node.md` says `NODE` names a playbook suffix and that a new node needs its own `provision-<x>.yml`. The usage line of `make provision` no longer lists nodes (it named `aws1` and omitted `bee`, `rpi3` and `gcp1`).
3. Minor, vacuous bastion test: **applied.** `assert ephemeral` mirrors its siblings.
4. Minor, list-valued `ansible_ssh_common_args`: **applied.** The preflight joins a list, and `test_options_given_as_a_list_are_read_too` covers it.
5. Minor, the hub-only path also needs the pinned file: **accepted.** The controller must have dotfiles deployed anyway (proposal, Risks), and one rule is simpler to operate than an exception for a run that targets only ephemeral hosts.
6. Minor, AC6 wording: **applied** above. jetson is named as a deviation, and the count names the seven stable hosts.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/ansible-provisioning/lesson-569-a-host-key-test-through-a-live-controlmaster-socket-checks-nothing.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: it applies the existing host-key policy to the generated inventory and changes no architecture; the replacement (an SSH CA) is #1261
- [x] New pattern candidate for `00_meta/patterns/`? no: one project; the SSH multiplexing caveat is captured in the lesson

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/ANSIBLE-066-pinned-host-keys/` -> `specs/archive/ANSIBLE-066-pinned-host-keys/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
