---
id: onboard-vpn-fleet-agent
type: runbook
status: active
created: "2026-05-31"
owner: manu
---

# Onboard a VPN Fleet Agent (tag-based, ADR-041)

> Join a fleet automation agent (`hermes`, `openclaw`, …) to the Headscale mesh as a
> **tagged, segmented** node. The tag (`tag:<agent>`) is the ACL identity; the `agents`
> Headscale user only holds key custody. See [ADR-041](../adr/adr-041-agent-fleet-vpn-segmentation.md).

## Prerequisites

- The dedicated Headscale user **`agents`** exists (`docker exec headscale headscale users list`; create with `headscale users create agents`).
- `policy.hujson` (rendered from `infra/ansible/roles/headscale/templates/policy.hujson.j2`) defines, for the agent's tag:
  - **`tagOwners["tag:<agent>"]` includes `agents@`** (the registering user) — and `kubelab@` for manual admin tagging.
  - an `acls` egress rule: `{ "src": ["tag:<agent>"], "dst": [ …allowed services… ] }`.
- The file-mode policy is **active**: `headscale_policy_path` set in `deploy-vps.yml`, deployed via `make deploy TARGET=vps ENV=prod`. Verify: `make check-headscale-policy` → "Policy is valid".

## Steps

1. **Mint a one-time, tagged preauth key** (under the `agents` user, id from `users list`):
   ```bash
   ssh deployer@<vps-public-ip> \
     "docker exec headscale headscale preauthkeys create -u <agents-id> -e 72h --tags tag:<agent>"
   ```
   One-time + non-ephemeral (node persists). The key **carries the tag** — the node is tagged on registration. _(VPN-ACL-007 will turn this into `toolkit infra headscale mint-agent-key`.)_

2. **Join from the agent host**:
   ```bash
   tailscale up \
     --login-server=https://vpn.kubelab.live \
     --authkey=<KEY> \
     --accept-routes=false
   ```
   - **Do NOT pass `--advertise-tags`** — the key already tags the node (see Gotchas).
   - `--accept-routes=false` unless the agent must reach the `172.16.1.0/24` LAN (most agents only talk to Tailscale IPs).
   - **K8s pod / no systemd**: the daemon won't auto-start and there is no TUN device — run `tailscaled` in **userspace** mode first (`--tun=userspace-networking`, create `/dev/net/tun` if the container allows), then `tailscale up`.

3. **Record the assigned IP in the SSOT** — add `networking.nodes.<agent>` (`hostname`, `tailscale_ip`) to `infra/config/values/common.yaml`, then `toolkit infra ansible generate --env prod` to regenerate the inventory.

4. **Provision the agent's scoped credential (C6 zero-trust)** via toolkit + SOPS — its own SSH key / API token / service account for each target service. The ACL governs *reachability*; the credential governs *authorization*. Agents never rely on the `100.64.0.0/10` bulk trust.

5. **Verify**:
   ```bash
   docker exec headscale headscale nodes list        # <agent> present, Tags = tag:<agent>
   toolkit infra headscale probe                      # preserved flows still hold
   ```
   Then confirm the agent reaches an allowed service **with its own credential**, and is reachable only by admin on `:22`.

## Gotchas (hard-won)

- **`tagOwners` must include the registering user (`agents@`), not just the admin.** Headscale rejects a node/key carrying a tag whose user is not a `tagOwner` (`"tag … not permitted by auth key"`). ADR-041's original "tagOwners = kubelab admin" was insufficient — corrected to `["kubelab@", "agents@"]`.
- **Never combine the key's `--tags` with `tailscale up --advertise-tags`.** Two tagging paths exist: (a) the key carries the tag (auto-applied on registration), (b) the node advertises it (requires the node's user to own the tag). Using both triggers (b)'s validation and fails. Use (a) only — drop `--advertise-tags`.
- **User reference form on v0.28**: ACL `src` / `tagOwners` need `user@` (e.g. `kubelab@`), not bare `kubelab`.
- **K8s container = userspace Tailscale**: no systemd PID 1 (daemon won't auto-start) and no TUN device → run `tailscaled --tun=userspace-networking`. Inbound `admin→agent:22` over userspace netstack may need extra handling (`tailscale serve` / SSH via the proxy); the agent's **outbound** egress works in userspace.
- **Preauth key lifecycle**: one-time keys are consumed on a *successful* registration (a rejected attempt does not consume them). Expire in the `-e` window if unused. They are throwaway — do not store/document the key value.
- **Post-reload propagation window**: right after a SIGHUP policy reload, the new network map takes a few seconds to reach clients. The deploy probe retries (`retries: 4, delay: 5`) so a first-attempt blip is not misread as a broken flow.

## Rollback

- Remove the node: `docker exec headscale headscale nodes delete -i <node-id>`.
- Revoke a leaked key: `docker exec headscale headscale preauthkeys expire …`.
- Policy changes auto-revert on probe failure (the `headscale` role restores the previous `policy.hujson` and SIGHUP-reloads).

## References

- [ADR-041](../adr/adr-041-agent-fleet-vpn-segmentation.md) — the segmentation model.
- Spec `specs/VPNACL-001-fleet-segmentation/` — implementation + verification.
- Backlog: `VPN-ACL-005` (credential rotation), `VPN-ACL-007` (codify key minting in the toolkit).
