---
id: lesson-009-from-the-non-admin-workstation-can-t-reach-th
type: lesson
status: active
created: "2026-06-20"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# From the non-admin workstation, "can't reach the node" has three independent causes — not "node down"

**Context**: Validating the new K3s upgrade runbook (OPS-002 #429) against staging needed read-only pre-flight commands on ace1. ace1 was powered on, yet every SSH attempt from this Windows non-admin box (EGW-LEN029) failed — first read as "the on-demand node is off", which was wrong.

**Problem**: Three distinct, stacked blockers, each masquerading as "node down":

1. **Mesh IPs are not locally routable here.** This box runs no native Tailscale, so `ssh ace1` (→ `100.64.0.11:22`, the alias's `Hostname`) just times out — there is no kernel route to `100.64.0.0/10`.
2. **The `-ext` bastion alias fails as a fallback.** `ace1-ext` (ProxyJump via the public VPS) dies with `deployer@162.55.57.175: Permission denied (publickey)` — the VPS jump host authenticates as user **`deployer`**, and this workstation's key isn't authorized for `deployer` on the VPS. The `-ext` aliases are *not* a drop-in transport from this box.
3. **ts-bridge + passphrase key block automation.** `ts-bridge connect` tunnels a **single target** (`ace1:22 → 127.0.0.1:33389`), not a general mesh router. And the local key `~/.ssh/id_ed25519` (`dell-egw-len029`) has a **passphrase** with **no ssh-agent** in the automation shell, so non-interactive SSH (the agent harness, Ansible) cannot authenticate even though an interactive shell can. Ansible-over-the-mesh is further blocked because the generated inventory targets the non-routable mesh IPs.

**Solution**: Deferred the empirical validation (tracked as OPS-011 #722) and shipped the runbook on doc-level review only. For interactive single-node access from here: `ts-bridge connect`, then SSH to `127.0.0.1:<bridge-port>` using the node's own user + key. For automation: run it from a native-Tailscale node, or expose a persistent `SSH_AUTH_SOCK` to the automation shell.

**Rule**: From a non-admin / non-native-Tailscale box, diagnose fleet-access failures against all three causes before concluding "node down" — mesh non-routability, the `-ext` bastion authenticating as `deployer` (not your user), and a passphrase key with no agent. `ts-bridge` solves only single-target *interactive* SSH; *automation* needs a native-Tailscale node or an inherited ssh-agent. Procedure: `docs/runbooks/non-admin-workstation-access.md`.
