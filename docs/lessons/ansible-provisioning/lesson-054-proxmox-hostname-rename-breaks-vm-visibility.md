---
id: lesson-054-proxmox-hostname-rename-breaks-vm-visibility
type: lesson
status: active
created: "2026-02-20"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# Proxmox Hostname Rename Breaks VM Visibility

**Context**: Renaming hostnames from `cubelab-*` to `kubelab-*` as part of the global project rename.

**Problem**: After `hostnamectl set-hostname kubelab-ace1`, `qm list` returns empty. VMs appear to have vanished. Proxmox ties VM `.conf` files to the directory `/etc/pve/nodes/{hostname}/qemu-server/`. When the hostname changes, Proxmox creates a new directory but configs remain in the old one.

**Solution**: Move the `.conf` files from the old directory to the new one:
```bash
ls /etc/pve/nodes/                    # You'll see old-name and new-name
mv /etc/pve/nodes/{old}/qemu-server/*.conf /etc/pve/nodes/{new}/qemu-server/
qm list                               # VMs reappear
qm start <vmid>
```

**Rule**: NEVER rename a Proxmox host with just `hostnamectl`. Always check `/etc/pve/nodes/` and move VM configs. Also documented in the `proxmox-setup.md` runbook in the vault.
