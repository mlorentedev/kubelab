---
tags: [spec, verification, templates]
created: "2026-07-10"
---

# Verification - TOOL-016-ansible-transport

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof.

- [x] AC1 (bastion adds ProxyCommand to mesh-only, none on VPS) -> f1 (`pytest -k bastion`, 2 passed) + smoke
- [x] AC2 (mesh unchanged / regression) -> f2 (`pytest -k mesh`, 4 passed, 1 deselected) + full suite 394 passed
- [x] AC3 (bastion target from SSOT, no hardcoded IP) -> f3 (grep: 0 IPs in generator source)
- [x] AC4 (`--transport` flag + Makefile `TRANSPORT=`) -> f4
- [x] AC-coverage (new AnsibleGenerator unit suite) -> f5 (5 passed; was 0 coverage before)
- [ ] Runtime end-to-end through the bastion -> f6 (Linux-gated; provision session)

## Test status

- Unit suite: `poetry run pytest tests/test_generator_ansible.py` -> **5 passed**.
- Full non-e2e suite: **394 passed, 0 failed** (no regression). `ruff` clean.
- **Re-verified 2026-08-09** after rebasing onto master (23 commits, no file overlap, no
  conflicts). The rebase carried the branch across four dependency bumps that its original
  evidence predates — `typer ^0.26.8 -> ^0.27.0` (which validates the new `--transport`
  option), `pytest ^8 -> ^9`, `ruff ^0.15 -> ^0.16`, `mypy ^2.1 -> ^2.3` — plus `a7d3722`,
  which changed config merge semantics the generator reads through. f1-f5 all re-run
  verbatim: exit 0.
- **f2's recorded count was corrected, not regressed.** `-k mesh` selects 4, not 3: pytest
  substring-matches the full node ID, so `test_mesh_only_nodes_get_proxy_via_ssot_bastion`
  satisfies both filters. What is verifiable is that **3 does not reproduce against the
  committed test names** — under any pytest version, since `-k` node-ID matching is not new
  in 9. Why July recorded 3 cannot be recovered: the branch is a single squashed commit, so
  a transcription of the mesh class's size and a rename landing after the capture are
  indistinguishable. Either way the entry had stopped tracking the command; it now records
  what the command prints.
- `make type` fails on `toolkit/features/notify_smoke.py` (missing `types-requests` stubs).
  **Pre-existing on master** — reproduced there with an identical error, untouched by this
  branch. Filed as CI-GATE-005 (#902) and fixed in #903; not folded in here, to keep this PR
  atomic. The reason it could survive on `master` at all is CI-GATE-006 (#904): no CI job
  runs the toolkit suite, ruff, or mypy — including on this PR, whose 394 passing tests were
  produced locally and are not backed by any green check above.
- Smoke (real `toolkit infra ansible generate --transport bastion`): ace2 (100.64.0.5) and
  aws1 (MagicDNS) carry `ProxyCommand=ssh -i ~/.ssh/id_ed25519 -W %h:%p -q … deployer@<vps.public_ip>`;
  kubelab-vps (public IP) has no per-host args — it is the jump. Inventory restored to mesh after.
- f6 is Linux-gated: the real provision through the bastion uses the passphrase-gated key
  from a Linux controller — same runtime shape as #816/#859.
- No regression: mesh transport asserted to carry no per-host ssh args and an unchanged
  `all.vars` block.

## Decisions made during implementation

- **`ProxyCommand` with an explicit `-i <ssh_key>`** (not `ProxyJump`) so the hop provably
  authenticates with the SSOT `networking.ssh_key`, not the ssh client's default identity —
  the concern flagged in the proposal's design decision (b).
- **Fail-closed on no public jump**: `transport="bastion"` raises `ValueError` if
  `networking.vps.public_ip` is absent. A Tailscale-only VPS is unreachable from a non-mesh
  controller, so silently falling back to it would produce a broken inventory.
- **Seam is per-host, not a blanket global arg**: keyed on "node has no `public_ip`", so the
  VPS (the jump) and any public-IP node keep the jump-free global args.
- **`lan` is not a third transport value**: the existing `--bootstrap` flag already emits LAN
  IPs; the Makefile `provision` target regenerates for `BOOTSTRAP` **or** `TRANSPORT` then
  restores the mesh inventory, composing both without duplicating the LAN path.
- Refactor: extracted a pure `_build_inventory(...) -> dict` from `_generate_inventory` (which
  now only writes) — that is what made the generator unit-testable at all.

## Promotion candidates

- [ ] Lesson for the repo's `docs/lessons.md`? <decide at archive>
- [ ] ADR-worthy? Likely a short note or an ADR-052 addendum (SSH transport mirrors the
      kubectl transport) — decide at archive.
- [ ] New pattern candidate for `00_meta/patterns/`? No — repo-specific.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/TOOL-016-ansible-transport/` -> `specs/archive/TOOL-016-ansible-transport/`
- [ ] Bitácora ticket (#818) closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
