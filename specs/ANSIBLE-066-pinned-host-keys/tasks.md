---
tags: [spec, tasks, templates]
created: "2026-10-14"
---

# Tasks - ANSIBLE-066-pinned-host-keys

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch `fix/ansible-pinned-host-keys` from master
- [x] Host keys of the six homelab nodes pinned in dotfiles (mlorentedev/dotfiles#2465), each equal to msi's prior record

## Implementation

- [x] [AC1] [AC2] [AC3] [AC5] Failing tests: `tests/test_ansible_pinned_host_keys.py`
- [x] [AC1] `networking.ssh_known_hosts` in `common.yaml`; the generator emits the pinned options globally
- [x] [AC2] The hub override, derived from `tailscale_dns` without `tailscale_ip`
- [x] [AC3] The bastion jump verified; the hop keeps the node's own host-key options
- [x] [AC5] `homelab.yml` carries the same arguments
- [x] [P] [AC4] Failing test, then the preflight in `toolkit infra ansible run`
- [x] [P] [AC7] `docs/runbooks/add-a-node.md`; stale `accept-new` comments in `wait-node-ready.yml`, its test and `gcp-hub-bootstrap.md`
- [ ] [AC6] Live from the Mac, after #2465 is deployed: `ping` on every stable node; one swapped key refused

## Closing

- [x] `make test-fast` green: 4595 passed after regenerating `platform.json` (2026-10-14)
- [ ] `features.json` and `verification.md` filled
- [ ] Draft PR with `## Knowledge`; reviewers triaged; `## Review triage`
- [ ] `dotf spec review`, dispositions, archive
