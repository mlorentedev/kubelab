---
id: ssh-keys
type: runbook
status: active
created: "2026-03-14"
owner: manu
---

# SSH Keys — Reference

> Two SSH key pairs in use. All homelab nodes must accept BOTH.

## Key Inventory

| Key | Comment | Location (private) | Purpose |
|-----|---------|-------------------|---------|
| `manu@msi` | `AAAAC3...brpc` | `~/.ssh/id_ed25519` on workstation | Manual SSH access from dev machine |
| `mlorentedev@deployment` | `AAAAC3...f69p` | GitHub Secrets: `SSH_KEY`, `SSH_PRIVATE_KEY` | CI/CD deploy via GitHub Actions |

## Where Each Key Must Be

| Node | `manu@msi` | `mlorentedev@deployment` |
|------|-----------|-------------------------|
| RPi4 (kubelab-rpi4) | Yes — manual access | Yes — CI deploys DNS/configs |
| RPi3 (kubelab-rpi3) | Yes | Optional |
| VPS (kubelab-vps) | Yes | Yes — CI deploys apps |
| K3s nodes (server, agents) | Yes | Yes — CI deploys manifests |
| Acemagic Proxmox hosts | Yes | No (not deployed to) |
| Beelink | Yes | Optional |
| Jetson | Yes | Optional |

## Adding Keys to a New/Reflashed Node

Both keys must be in `~/.ssh/authorized_keys` for user `manu`:

```bash
# If SSH access available (password or another key):
ssh-copy-id -i ~/.ssh/id_ed25519.pub manu@<IP>

# If mounting SD card / disk directly:
# Append both keys to /home/manu/.ssh/authorized_keys
cat >> /media/$USER/writable/home/manu/.ssh/authorized_keys <<'EOF'
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG3Hinn+4zSfBoW5r9gJrCbdXDbM+PZ2oJVGjZuybrpc manu@msi
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFr59Z/icIPCppjKgVltXCYzSq7F32lK6QD1OAb1f69p mlorentedev@deployment
EOF
```

## After Reflashing a Node (Host Key Changed)

The node generates new SSH host keys. Your workstation will reject the connection:

```
WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!
```

Fix on workstation:
```bash
ssh-keygen -f ~/.ssh/known_hosts -R <IP>
# Also clean Tailscale IP and any hostname aliases:
ssh-keygen -f ~/.ssh/known_hosts -R <TAILSCALE_IP>
```

## GitHub Secrets

| Secret | Content | Last updated |
|--------|---------|-------------|
| `SSH_KEY` | Private key of `mlorentedev@deployment` | 2025-06-09 |
| `SSH_PRIVATE_KEY` | Same private key (duplicate, legacy) | 2025-06-09 |

The 4 files `~/.ssh/ssh_key_*` on the workstation are copies of the public key — safe to delete (they are not used by SSH config).

## Gotchas

- **Raspberry Pi Imager** only adds ONE key. If you flash with it, manually add the second key before first boot or via SD card mount.
- **cloud-init** on Ubuntu Server may overwrite `authorized_keys` on first boot. Disable cloud-init network/user management after initial setup.
- **Never commit private keys** to the repo. Deploy keys live ONLY in GitHub Secrets and on the CI runner.
