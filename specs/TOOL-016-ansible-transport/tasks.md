---
tags: [spec, tasks, templates]
created: "2026-07-10"
---

# Tasks - TOOL-016-ansible-transport

> TDD order. One task = one focused commit. Tick as you go.

## Setup

- [x] Branch created from master: `feat/TOOL-016-ansible-transport`
- [x] `proposal.md` complete; acceptance criteria testable
- [x] No open questions left ([RESOLVED]: `--transport {mesh,bastion}` flag + SSOT-derived bastion)

## Implementation

> `_build_inventory(networking, bootstrap, transport)` is the new pure, testable core.
> Mesh must stay byte-identical (regression). Bastion adds a per-host ProxyCommand to
> mesh-only nodes (no public_ip), derived from `networking.vps.public_ip` +
> `ssh_users.cloud` + `ssh_key`; the VPS (the jump) is never proxied.

- [x] [P] [AC2] Failing test: `transport="mesh"` (default) inventory has no per-host
      `ansible_ssh_common_args`; `all.vars` unchanged (regression snapshot).
- [x] [AC2] Refactor: extract pure `_build_inventory(...) -> dict` from `_generate_inventory`
      (write path unchanged); mesh test passes with no behaviour change.
- [x] [P] [AC1] Failing test: `transport="bastion"` adds a ProxyCommand to every mesh-only
      node and NONE to the VPS; target host/user/key come from the fixture's SSOT values.
- [x] [AC1] [AC3] Implement the bastion branch in `_build_inventory` — derive user/ip/key
      from `networking.*`; fail-closed (clear error) if `transport="bastion"` and no VPS
      public_ip exists.
- [x] [AC3] Failing test / guard: no literal public IP in `generator_ansible.py` source.
- [x] [AC4] Thread `transport` through `generate()` + a `--transport {mesh,bastion}` CLI
      option on `infra ansible generate` (default `mesh`).
- [x] [AC4] Thread `TRANSPORT=` through the `Makefile` `provision` target (both the normal
      and BOOTSTRAP generate calls).
- [x] Refactor for clarity; `ruff` + `mypy` clean.

## Closing

- [x] Every acceptance criterion covered by ≥1 test
- [x] Every acceptance criterion has a `features.json` entry with a non-vacuous verification
- [x] Type checks pass (`mypy`)
- [x] Lint passes (`ruff`)
- [x] No unrelated changes in the diff
- [x] `verification.md` filled in
- [ ] PR opened referencing this spec folder (draft until the Linux provision run exercises
      the end-to-end path through the bastion)

## Machine-readable features

See sibling `features.json`. Runtime end-to-end (`make provision … TRANSPORT=bastion`
through the real bastion) is Linux-gated; the static/unit criteria are Windows/CI verifiable.
