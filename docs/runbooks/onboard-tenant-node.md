---
id: onboard-tenant-node
type: runbook
status: active
created: "2026-11-06"
owner: manu
---

# Onboard a Tenant Node (external segment, VPN-ACL-014)

> The **control-plane half** of enrolling an external organisation's node into a
> tenant segment on the shared Headscale. This fills the gap [headscale-setup
> Phase 9.3](headscale-setup.md#93-not-covered-here) declares. The **node-side
> half** — ts-bridge host-mode invocation, OS supervisor, local state — belongs to
> the tenant's own provisioning and is deliberately not documented here.
>
> The tenant's name, node names and port choices stay in the values/SOPS and in the
> tenant's records, never in this repository (public repo; segment keys in SOPS are
> neutral for the same reason). Every `<placeholder>` below is resolved at run time.

## Ownership seam

| Half | Owner | Covered by |
|---|---|---|
| Segment declaration, policy deploy, key minting, registration verification, ACL matrix | kubelab control plane (this document) | commands run from the authorized controller (OPS-051) |
| Node provisioning, ts-bridge host-mode invocation (`host serve --config <host.yaml>`), OS supervisor, local identity/state | tenant's provisioning | their runbook; this document only defines the handoff |

The seam is the handoff in the next section: this side produces three parameters,
the tenant side consumes them. Neither side reaches into the other's half.

## Handoff contract (what the tenant side receives)

Delivered through the agreed secure channel, one node at a time. Never committed,
never stored next to the node, never sent over plain chat:

1. **Login server**: `https://vpn.kubelab.live` (public by design — bootstrap
   services cannot depend on the mesh).
2. **A one-time, tagged preauth key** (step 2): carries the tag of the node's
   **role** — `hosts_tag` for a host, `clients_tag` for a client — expires in its
   `-e` window, consumed on successful registration only. Delivered as a **file**
   consumed through the binary's `auth_key_file` config, never as an argv value
   (`--authkey` leaks into process listings and shell history).
3. **The VPS SSH host key fingerprint** (host-key trust, below) for provisioning
   to pin and compare. Pinning is the tenant side's job; the fingerprint's
   provenance is this side's.
4. **Only for a node joining from a network that sinkholes or TLS-inspects the
   control plane**: the `hs-bootstrap` SSH alias definition (step 1). A client
   uses it through `ts-bridge connect --bootstrap-ssh hs-bootstrap`; a host's
   candidate equivalent is `mesh.bootstrap_ssh` in host mode — present in the
   candidate, not yet runtime-qualified, so it ships only after host-mode
   acceptance proves it.

The tenant's `host.yaml` (ts-bridge host mode, `version: 1`) is the binary's
contract, not this repository's; these parameters feed it.

## Host-key trust (VPS SSH)

Provisioning pins the VPS SSH host key and compares on every connection — never
trust-on-first-use. The source of trust on this side is the pinned known-hosts
file the dotfiles deploy (`networking.ssh_known_hosts` → `~/.ssh/known_hosts_pinned`,
ANSIBLE-066): the VPS line is version-controlled there, so its provenance is the
dotfiles history, not a message. Extract the fingerprint from that file
(`ssh-keygen -lf ~/.ssh/known_hosts_pinned -F <vps-ip>`) and deliver it through
the same trusted channel as the key. Deliver the **extracted VPS entry only**
(`ssh-keygen -F <vps-ip> -f ~/.ssh/known_hosts_pinned` prints just that host's
lines) — never the whole personal pinned file, which carries every other node's
entries. The candidate delegates verification to the
system OpenSSH — no fingerprint or known_hosts YAML of its own, no forced
`StrictHostKeyChecking` — so provisioning owns the pin (`StrictHostKeyChecking=yes`,
`BatchMode`, known_hosts under SYSTEM); this side only guarantees where the
fingerprint came from.

## Phase 0: Readiness checklist (controller only, read-only)

> Run from the authorized controller (OPS-051). Nothing in this phase changes state.

- [ ] **0.1 Headscale healthy**
  ```bash
  ssh vps-pub "docker inspect --format '{{.State.Health.Status}}' headscale"
  # → healthy  (v0.28 has no HTTP /health endpoint — do not curl it)
  ```
- [ ] **0.2 Segment declared and deployed.** The proof is the deploy that rendered
  it: `make deploy TARGET=vps ENV=prod` completed without the role's segment
  refusals (malformed, private owner, tag reuse — see [headscale-setup 9.2](headscale-setup.md#92-declare-or-change-a-segment)).
  The rendered policy is the only artifact that names the tags; SOPS is the only
  SSOT for `ports`.
- [ ] **0.3 Segment owner user exists** (the role creates it at deploy if missing):
  ```bash
  ssh vps-pub "sudo docker exec headscale headscale users list"
  # note the owner's numeric ID — v0.28 CLI takes numeric IDs, not names
  ```
- [ ] **0.4 (joins from filtered networks only) `hs-bootstrap` deployed and
  this machine's key registered** —
  [headscale-setup 10.2](headscale-setup.md#102-enrol-a-machine). Skip if the
  node's network reaches `vpn.kubelab.live` directly. A **host** on a filtered
  network has a candidate path (`mesh.bootstrap_ssh` in ts-bridge host mode) but
  no runtime qualification yet: treat it as unqualified, not unavailable — it
  gates on host-mode acceptance, not on this runbook.
- [ ] **0.5 DNS residual accepted FOR THIS NODE.** The split-zone resolver address
  is visible to every node but unreachable under the policy. The acceptance recorded
  for the first tenant node does **not** carry over — each additional node needs the
  decision repeated (VPN-ACL-014 risk register). Retirement is OPS-019.
- [ ] **0.6 (hosts only) A qualified ts-bridge host-mode build exists** for the
  node's OS, with its checksum recorded by the lane that produced it. An
  unqualified build is a stop, not a workaround. Clients do not use host mode;
  this item does not gate them.

## Steps

### 1. Register the node's bootstrap SSH key (client joins from filtered networks only)

Follow [headscale-setup 10.2](headscale-setup.md#102-enrol-a-machine) verbatim: one
dedicated ed25519 key per machine, public line into
`apps.services.core.headscale.bootstrap_ssh_keys.client-<N>` (SOPS), then
`make deploy TARGET=vps ENV=prod`. One key per machine is what makes revocation per
machine. Verify from the machine: `ssh hs-bootstrap` gets no shell (the key
authenticates and is restricted), and the SOCKS forward to `vpn.kubelab.live:443`
is permitted. `READY` is not reachable yet — the tenant key does not exist until
step 2; the join in step 3 is where `READY` is checked.

Enforcement has two independent layers, and only the first is guaranteed by the
key itself: every authorized_keys line carries
`restrict,port-forwarding,permitopen=vpn.kubelab.live:443`, which sshd enforces
whenever that key authenticates. The `Match User hs-bootstrap` block in
sshd_config is defense in depth and lands with the first `ssh_hardening` run on
the VPS — until that run, do not describe the global block as live.

### 2. Decide the node's role, then mint its one-time tagged preauth key

The role is decided before minting — a key carries exactly one tag and cannot be
repurposed:

- **host** — serves the segment's services; joins with `hosts_tag`; is reached by
  clients on `<ports>` and originates nothing.
- **client** — consumes the segment's services; joins with `clients_tag`; reaches
  hosts on `<ports>` and is reached by nothing.

```bash
# <owner-id> from checklist 0.3; <hosts_tag> or <clients_tag> from the segment
# entry in SOPS — the tag matches the role decided above. SOPS values already
# carry the tag: prefix; pass them as-is (never write tag:<...> again here).
ssh vps-pub "sudo docker exec headscale headscale preauthkeys create \
  -u <owner-id> -e 1h --tags <hosts_tag-or-clients_tag>"
```

- **Record the key's ID at mint**: `preauthkeys list` shows it in the ID column;
  the tenant inventory keeps it (step 7) — revocation expires by ID, not by owner.
- **One-time**: consumed by a *successful* registration; a rejected attempt does
  not consume it. Expire an unused or compromised key by its ID:
  `headscale preauthkeys expire --id <preauth-key-id>` — v0.28 `expire` takes
  `--id`, not `-u` (there is no `-u` on expire; `-u` belongs to `create`).
- **The key carries the tag** — the node must NOT pass `--advertise-tags` (two
  tagging paths fail together; see [onboard-vpn-fleet-agent](onboard-vpn-fleet-agent.md) gotchas,
  which apply verbatim here).
- **TTL**: the shortest window that covers the enrolment session. A leaked unused
  key dies on its own; a long-lived one is a standing invitation.
- Minting is per node and per session. There is no reusable tenant key by design;
  codifying this step in the toolkit is VPN-ACL-016.

### 3. Hand off and let the tenant side join

Not documented here (Phase 9.3's boundary). Deliver the handoff contract: login
server, the key as a **file** for the binary's `auth_key_file` (never `--authkey`
on argv), the VPS host-key fingerprint to pin, and — client on a filtered network
only — the bootstrap SSH alias. The tenant side provisions and joins; a host runs
`host serve --config <host.yaml>` under its supervisor, a client connects
natively. When it succeeds, the node appears in `nodes list` under `tagged-devices`
with its role's tag — a tagged node has no user; the owner binding happened at
mint (the key was created with `-u <owner-id>` and the tag is owned by `owner@`
in tagOwners).

### 4. Verify registration and issue the receipt

The binary accepts any tagged key — it only rejects tagless ones — so a successful
enrollment proves nothing about the role. The control plane is where the role is
verified; this receipt is what the tenant side's acceptance cites:

| Field | Source | PASS condition |
|---|---|---|
| Owner | `nodes list`, User column | `tagged-devices` — a tagged node has no user; the owner binding is the mint (`-u <owner-id>` + tagOwners), not this column |
| Node identity | `nodes list`, ID + hostname | exactly one node for the expected machine — no duplicate registration |
| Tag | `nodes list`, Tags column | exactly the role's tag (`hosts_tag` for a host, `clients_tag` for a client) — not merely any tag |

```bash
ssh vps-pub "sudo docker exec headscale headscale nodes list"
toolkit infra headscale probe
# every preserved private flow still holds — a segment must never disturb rule 1
```

FAIL on any cell: expire the key, delete the node, re-mint with the correct tag.
`READY`/`enrolled=true` on the node side is necessary, never sufficient.

### 5. Approve subnet routes (only if the node advertises any)

Tenant endpoint nodes normally advertise nothing. If one does:

```bash
ssh vps-pub "sudo docker exec headscale headscale nodes list-routes"
ssh vps-pub "sudo docker exec headscale headscale nodes approve-routes \
  -i <NODE_ID> --routes <prefix>"
# --routes is a SET operation: it replaces all approved routes, not additive
```

A tenant route reaching the private LAN would defeat the segment — approve only
after the ACL matrix proves the direction is intended, and record the approval in
the tenant's own inventory.

### 6. Run the ACL matrix

Next section. The enrolment is not done until every cell is proven.

### 7. Record for revocation

The tenant's inventory keeps: node identity, node ID from `nodes list`, preauth
key ID (from `preauthkeys list` at mint — revocation expires by ID), bootstrap
key serial (`client-<N>`), mint date. This repository keeps nothing (tenant data
rule). Revocation then needs no archaeology: [Revoke](#revoke-a-tenant-node).

## The ACL matrix

Derived from the rendered policy: rule 3 grants exactly
`clients_tag → hosts_tag:<ports>`; rule 1 names its destinations and no segment tag
is among them. `<ports>` is the segment's `ports` list in SOPS — the only SSOT for
what is allowed. Cells marked **tenant** run from the tenant's node (their lane
executes; this table fixes the expected result so verification is mechanical, not
interpretive). Cells marked **mesh** run from any private node over the tailnet.

| # | Source | Destination | Expected | Runner |
|---|---|---|---|---|
| A1 | segment client | segment host, port in `<ports>` | connects | tenant |
| A2 | segment client | segment host, port NOT in `<ports>` | refused / timeout | tenant |
| D1 | segment host (outbound) | any peer, any port | no outbound connection originates — hosts originate nothing | tenant |
| D2 | segment node (either role) | any private node (`kubelab@`, `manu@`, `work@`, `agents@`, `tag:hermes`) or `lan-rpi4` | unreachable | tenant |
| D3 | private node (any private identity) | segment node (either role) | unreachable — rule 1 names destinations, segment tags are not among them | mesh |
| D4 | any peer | segment client (inbound) | unreachable — nothing reaches a segment's clients | mesh |
| R1 | segment node (either role) | split-zone resolver address | address visible (DNS answer), connection unreachable | tenant |

Notes:

- A **host is a destination only; a client is a source only**. Each cell names the
  role it applies to; a node that must switch roles must be deleted first
  (`nodes delete -i <NODE_ID>`) and re-enrolled fresh with a new key carrying the
  other tag — re-registering a tagged node keeps its old tag and silently consumes
  the new key (upstream headscale #3370). Never a policy change.
- D3/D4 are policy-level facts (no rule grants them); the network probes make them
  observable rather than trusted. If any deny cell connects, stop: the rendered
  policy is not the one this document describes — re-run
  `make check-headscale-policy` and re-deploy before anything else.
- A1/A2 use the tenant node's own tooling (their lane chooses the commands); the
  matrix fixes only the expected outcome per cell.
- R1 is the accepted residual, decided per node (checklist 0.5). It is visibility,
  not reachability — do not "fix" it by widening the policy.

## Revoke a tenant node

Three independent revocations; do all that apply:

```bash
# 1. The node itself (headscale-setup 9.4)
ssh vps-pub "sudo docker exec headscale headscale nodes delete -i <NODE_ID>"

# 2. An unused/leaked preauth key (ID from the tenant inventory, recorded at mint)
ssh vps-pub "sudo docker exec headscale headscale preauthkeys expire --id <preauth-key-id>"

# 3. The bootstrap SSH key (headscale-setup 10.3): remove the SOPS entry and
#    deploy — that blocks every NEW session authenticated with it. Live sessions
#    are not re-checked; end only this node's, by PID resolved from its source
#    address — never the whole account:
ssh vps-pub "sudo ss -tnp | grep '<node-source-ip>'"         # find this node's PID(s)
ssh vps-pub "sudo kill <PID>"                                # end those sessions only
```

Killing every session on the account (`pkill -u hs-bootstrap sshd`) drops **all**
tenant nodes' tunnels at once and is reserved for a globally authorized window,
not a per-machine revocation. If the node's source IP is shared (several tenant
nodes behind one NAT), the IP alone is ambiguous: identify the node's session
from the sshd journal (`journalctl -u ssh`) by its accepted-publickey line — one
key per machine makes the key fingerprint identify the machine — before killing.
A revoked node loses its tag and its grants immediately; a running tunnel keeps
forwarding until its own session is ended.

## Gotchas

- **v0.28 CLI takes numeric user IDs** (`-u 2`), not names — resolve with
  `users list` first.
- **No top-level `routes` command**: routes live under `nodes`
  (`list-routes`, `approve-routes`), and `--routes` is a SET, not additive.
- **One-time keys are consumed by success, not by attempt** — a failed join leaves
  the key valid until its `-e` window; expire it if the join is abandoned.
- **The key carries the tag; the node must not advertise it** — combining both
  paths fails registration (fleet-agent gotcha, verbatim).
- **A key carries one role's tag** — minting with the wrong tag puts the node in
  the wrong role; there is no retag without a new key.
- **`READY`/`enrolled=true` accredits nothing** — the binary only rejects tagless
  nodes and accepts any tagged key; only the control-plane receipt (step 4)
  verifies owner, identity and the role's tag.
- **Never pass the key on argv** — `--authkey` lands in process listings and
  shell history; `auth_key_file` exists for this.
- **Per-key options vs the Match block** — the authorized_keys line restricts by
  itself; the sshd_config block is a second layer that only exists after the
  first `ssh_hardening` run. Cite the layer you mean.
- **Post-reload propagation window**: right after a policy SIGHUP, the new network
  map takes a few seconds to reach clients; a first-attempt blip right after a
  deploy is not a broken flow (the deploy probe already retries).
- **The DNS residual is per node**: the first node's acceptance does not extend to
  the next one. Decide it again at checklist 0.5, every time.
- **Tenant data never enters this repository**: not the tenant's name, not node
  names, not port choices. SOPS keys are neutral; placeholders here are resolved at
  run time.

## References

- [headscale-setup.md](headscale-setup.md) — Phases 8–10: policy management, tenant
  segments, control-plane bootstrap over SSH.
- [onboard-vpn-fleet-agent.md](onboard-vpn-fleet-agent.md) — tagged-key mechanics
  (agents, not tenants; gotchas apply verbatim).
- Specs: `specs/archive/VPN-ACL-014-tenant-segments/` (segments),
  `specs/VPN-ACL-015-ssh-bootstrap-path/` (bootstrap account).
- ADR-041 — the segmentation model. VPN-ACL-016 — codifying key minting (open).
