---
id: lesson-654-a-file-two-roles-agree-on-is-still-rewritten-by-a-writer-outside-ansible
type: lesson
status: active
created: "2026-10-29"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, edge, cloud-init]
---

# A file two roles agree on is still rewritten by a writer outside Ansible

**Context**: Two roles write `/etc/hosts`: `base_system` owns the `127.0.1.1` line and `dns_resilience` a marked block holding the `vpn.kubelab.live` pin to the public address (lesson-100). They do not touch each other's lines, so every provision converges and its second run reports `changed=0`.

**Problem**: After the B14 hard-reset test of #2661, the edge's `/etc/hosts` held cloud-init's header and no `KUBELAB DNS RESILIENCE` block (#2777). The Raspberry Pi image's NoCloud seed (`/boot/firmware/user-data`) sets `manage_etc_hosts: true`, so cloud-init's per-boot `update_etc_hosts` rewrote the file from its template at every boot. Between a reboot and the next provision the edge had lost the pin, and each provision reported both tasks `changed` with nothing to say why. Idempotence checks cannot see this: they compare a run with the one before it, never with what the node did in between. A drop-in under `/etc/cloud/cloud.cfg.d/` does not stop it either, because user-data outranks the image's system config.

**Solution**: `base_system` writes `/etc/cloud/cloud-init.disabled`, which stops cloud-init at its systemd generator, behind `base_system_disable_cloud_init` (default off, on only in `provision-rpi4.yml`), before it writes its own line. bee, ace1 and ace2 already carry the marker, which the Ubuntu installer writes. `force: false` leaves an existing marker alone. `tests/test_cloud_init_etc_hosts.py` holds the role list of `/etc/hosts` writers to the two known ones, the order, and the play that turns it on.

**Rule**: A managed file is converged only if nothing else on the node writes it. Before trusting a role's `changed=0` on a system file, check what rewrites that file at boot (cloud-init, NetworkManager, DHCP hooks), and read the file after a reboot, not only after a run.

**Tags**: `#adr-075` `#cloud-init` `#issue-2777`
