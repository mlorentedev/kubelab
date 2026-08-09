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
- [x] Runtime end-to-end through the bastion -> f6 (**passed 2026-08-09 off-mesh for real**, see below)

## Test status

- Unit suite: `poetry run pytest tests/test_generator_ansible.py` -> **5 passed**.
- Full non-e2e suite: **394 passed, 0 failed** (no regression). `ruff` clean.
- **Re-verified 2026-08-09** after rebasing onto master (23 commits, no file overlap, no
  conflicts). The rebase carried the branch across four dependency bumps that its original
  evidence predates — `typer ^0.26.8 -> ^0.27.0` (which validates the new `--transport`
  option), `pytest ^8 -> ^9`, `ruff ^0.15 -> ^0.16`, `mypy ^2.1 -> ^2.3` — plus `a7d3722`,
  which changed config merge semantics the generator reads through. f1-f5 all re-run
  verbatim: exit 0.
- **Re-verified again after the second rebase**, onto master at `2e9541f` (8 further commits,
  no conflicts, no overlap with the generator, the `provision` target or the aws1 path). f1-f5
  re-run verbatim: f1 2 passed / 3 deselected, f2 4 passed / 1 deselected, f3 exit 0, f4 exit
  0, f5 5 passed. Full non-e2e suite 394 passed, `make type` 59 files 0 issues. f6 was **not**
  re-run: none of the eight commits touches `generator_ansible.py`, the Makefile `provision`
  target, or anything on the aws1 path, and re-running it costs an off-mesh window of the
  operator's time. That is a stated judgement, not an omission.
- **f2's recorded count was corrected, not regressed.** `-k mesh` selects 4, not 3: pytest
  substring-matches the full node ID, so `test_mesh_only_nodes_get_proxy_via_ssot_bastion`
  satisfies both filters. What is verifiable is that **3 does not reproduce against the
  committed test names** — under any pytest version, since `-k` node-ID matching is not new
  in 9. Why July recorded 3 cannot be recovered: the branch is a single squashed commit, so
  a transcription of the mesh class's size and a rename landing after the capture are
  indistinguishable. Either way the entry had stopped tracking the command; it now records
  what the command prints.
- **`make type` now passes: 59 source files, 0 issues.** It previously failed on
  `toolkit/features/notify_smoke.py` for missing `types-requests` stubs — **pre-existing on
  master**, reproduced there with an identical error and untouched by this branch. Filed as
  CI-GATE-005 (#902), fixed in #903, and deliberately not folded in here to keep this PR
  atomic; the second rebase (2026-08-09, onto master at `2e9541f`) carried the fix in, so the
  failure is resolved by its own PR rather than by this one.
- **CI-GATE-006 (#904) is still open and still applies.** No CI job runs the toolkit suite,
  ruff, or mypy — including on this PR. The 394 passing tests and the clean mypy run above
  were produced locally and are **not** backed by any green check on the PR. That gap is why
  the failure above could survive on `master` in the first place.
- Smoke (real `toolkit infra ansible generate --transport bastion`): ace2 (100.64.0.5) and
  aws1 (MagicDNS) carry `ProxyCommand=ssh -i ~/.ssh/id_ed25519 -W %h:%p -q … deployer@<vps.public_ip>`;
  kubelab-vps (public IP) has no per-host args — it is the jump. Inventory restored to mesh after.
- **f6 was retargeted from `ace2` to `aws1` on 2026-08-09, and that unblocked it.** The
  behavior f6 asserts is reaching a **mesh-only node** from an off-mesh controller — it never
  named ace2. `aws1` is equally mesh-only (`networking.aws` has no `public_ip`, so the
  generator gives it a ProxyCommand exactly like ace2's) and, unlike ace2, it is **always-on**
  per ADR-028. The old command `NODE=ace2 --tags dev_node` chose a node that also happened to
  carry an interesting role, and that incidental choice is what made f6 look homelab-gated for
  a month. The `behavior` field was right; the `verification` command was narrower than it.
- **The probe is now non-invasive.** `CHECK=1` plus a tag no task carries means Ansible
  connects, gathers facts, and skips every task — so it proves the transport and changes
  nothing on the Argo CD hub. Verified `changed=0`. `CHECK=1` is a new passthrough on the
  `provision` target, added here because f6 needs it to be a `make` command rather than a
  raw toolkit invocation.
- **Dress rehearsal, 2026-08-09 — explicitly NOT f6.** The probe was run while the controller
  was still on the mesh: exit 0, `Gathering Facts ok: [aws1]`, `ok=3 changed=0 unreachable=0`,
  34s. It proves the ProxyCommand is well-formed, that the hop authenticates with the SSOT
  key, and that `aws1.kubelab.internal` resolves — resolution happens on the **VPS**, because
  `-W %h:%p` hands the name to the jump host, which is why the path can work with no local
  mesh route at all. It does **not** prove f6, because a mesh route existed and Ansible was
  free to prefer it. f6 stays `pending` until the same command passes after `tailscale down`.
- **f6 PASSED for real, 2026-08-09.** Same command, controller genuinely off the mesh. The
  precondition was *established and checked*, not assumed: `tailscale status` printed
  "Tailscale is stopped", `tailscale0` retained only a link-local `fe80::/64` with no
  `100.64.0.1`, and `ping -c1 100.64.0.7` to aws1 failed — while `getent hosts
  vpn.kubelab.live` still returned the public `162.55.57.175`, so the jump stayed reachable
  exactly as the design requires. Result: exit 0, `TASK [Gathering Facts] ok: [aws1]`,
  `PLAY RECAP ok=3 changed=0 unreachable=0 failed=0 skipped=2`, 35.6s wall — within a second
  of the on-mesh rehearsal's 34s, which is itself evidence that the mesh route was never
  what carried the connection. The target's restore leg ran: 0 `ProxyCommand` left in the
  generated inventory and `aws1` back to `ansible_host: aws1.kubelab.internal`.
  **Verifying the negative was the point of the run** — an off-mesh test that never confirms
  it is off-mesh proves the same nothing the rehearsal did.
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
- [x] New pattern candidate for `00_meta/patterns/`? **Yes — an amendment to
      [[pattern-feature-list-as-primitive]], not a new pattern.** Its Anti-patterns section
      already carries two failure modes from ANSIBLE-033, both about a command that passes
      when it should not. This spec produced the mirror image: **a `verification` narrower
      than the `behavior` it claims to verify, which manufactures a false blocker.** f6's
      behavior said "a mesh-only node"; its command said `NODE=ace2`, a node that is also
      on-demand. Nothing was wrong with the code, the probe, or the gate — and the PR still
      sat in draft for a month waiting on a precondition its own stated behavior never
      required. Decide the wording at archive; the pattern is the SSOT, so this is one more
      entry under the same question ("can I trust this verification command?"), not a
      sibling pattern.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/TOOL-016-ansible-transport/` -> `specs/archive/TOOL-016-ansible-transport/`
- [ ] Bitácora ticket (#818) closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
