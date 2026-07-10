---
tags: [spec, verification, templates]
created: "2026-07-10"
---

# Verification - TOOL-016-ansible-transport

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof.

- [x] AC1 (bastion adds ProxyCommand to mesh-only, none on VPS) -> f1 (`pytest -k bastion`, 2 passed) + smoke
- [x] AC2 (mesh unchanged / regression) -> f2 (`pytest -k mesh`, 3 passed) + full suite 375 passed
- [x] AC3 (bastion target from SSOT, no hardcoded IP) -> f3 (grep: 0 IPs in generator source)
- [x] AC4 (`--transport` flag + Makefile `TRANSPORT=`) -> f4
- [x] AC-coverage (new AnsibleGenerator unit suite) -> f5 (5 passed; was 0 coverage before)
- [ ] Runtime end-to-end through the bastion -> f6 (Linux-gated; provision session)

## Test status

- Unit suite: `poetry run pytest tests/test_generator_ansible.py` -> **5 passed**.
- Full non-e2e suite: **375 passed, 0 failed** (no regression). `ruff` + `mypy` clean.
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
