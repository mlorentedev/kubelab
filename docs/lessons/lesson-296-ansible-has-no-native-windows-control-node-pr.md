---
id: lesson-296-ansible-has-no-native-windows-control-node-pr
type: lesson
status: active
created: "2026-08-07"
owner: manu
tags: [kubelab, lesson, ansible, control-node, windows, wsl, provisioning, ansible-028, gotcha]
---

# Ansible has no native Windows control node — provision from Linux, and budget for the controller's own toolchain (ANSIBLE-028)

**Context:** ANSIBLE-028 (#816) sat with its runtime acceptance criteria `pending` for ten days. The role was written and statically verified, but no provision run had happened because the dev workstation was Windows.

**Problem:** This is not a missing package or a configuration gap — Ansible's control node requires POSIX primitives (`os.fork()`, ptys, a native `ssh`) that Windows does not provide. `ansible-playbook` is not shipped for native Windows and will not be. Windows is fully supported as a *target*, which is what makes the limitation easy to misread. The practical cost was ten days of a spec sitting at "written but unproven", with five real defects latent in it — every one of which needed a live target and a real remote repo to surface, and none of which lint, unit tests, or code review would have caught.

**Solution:** Run the controller on a Linux box already on the mesh (`msi`, ansible-core 2.20.0) against a powered-on ace2. Note that the bastion transport (TOOL-016 / #818) was **not** needed: from a mesh controller the default transport reaches the target directly, so the "merge the bastion PR first" ordering assumed earlier did not apply.

**Rule:** Provision from a Linux controller — a homelab box on the target's LAN, or WSL. But WSL is not free: it needs its own `ansible`, `sops` and `tailscale` toolchain, plus the SOPS key and mesh membership, before it can run a single playbook. Budget that as real setup work rather than assuming the dev box can stand in. More generally: when a spec's runtime criteria are blocked on an environment you don't have, that blockage is itself the risk — keep the criteria `pending` and say so, rather than marking them verified from static inspection.

**Tags:** `#ansible` `#control-node` `#windows` `#wsl` `#provisioning` `#ansible-028` `#gotcha`
