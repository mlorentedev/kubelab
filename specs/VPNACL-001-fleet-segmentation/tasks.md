---
tags: [spec, tasks]
created: "2026-05-31"
---

# Tasks - VPNACL-001-fleet-segmentation

> One task = one focused commit. Tick as you go. Reorder freely while `draft`; freeze on `implementing`.
> BLOCKER before implementation: resolve the `[AGENT-DRAFT]` open questions in `proposal.md` (esp. the `tag:hermes` dst matrix).

## Setup

- [ ] Branch created from master: `feature/vpn-acl-fleet-segmentation`
- [ ] `proposal.md` complete; `[AGENT-DRAFT]` items in "Risks / open questions" resolved
- [ ] Confirm on the live v0.28.0 VPS: `headscale nodes tag --help`, `headscale preauthkeys create --help` (exact tag flags)

## VPN-ACL-001 — Parameterize the headscale role

- [ ] Test: a generated `config.yaml` renders `policy.path` from a role var (not hardcoded `""`)
- [ ] Expose `headscale_policy_path` in `roles/headscale/defaults/main.yml`; template it in `config.yaml.j2`
- [ ] Task: copy/mount the HuJSON policy file to the VPS (`/etc/headscale/`) idempotently
- [ ] Handler: `systemctl reload headscale` (NOT restart) triggered on policy file change
- [ ] Wire deploy through the Makefile/toolkit (no manual VPS edits)

## VPN-ACL-002 — Author policy.hujson (permissive-first) + probe + CI gate

- [ ] Author `policy.hujson`: `groups`/`tagOwners` (`tag:hermes` owned by admin), `agents` identity, and a permissive-first `acls` baseline preserving ALL current flows (admin→all, ArgoCD hub→spoke `:6443`, rpi4 `172.16.1.0/24`, intra-K3s, monitoring)
- [ ] `headscale policy check` passes locally and as a CI gate (syntax)
- [ ] External connectivity-probe harness (toolkit/Ansible): asserts each preserved flow post-reload
- [ ] Auto-revert: on probe failure, reload the prior known-good policy
- [ ] Author the probe assertions in a form that migrates into a v0.29 `tests` block later (VPN-ACL-006)

## VPN-ACL-003 — Onboard hermes (zero-trust)

- [ ] Create Headscale user `agents` on the VPS; mint a `tag:hermes` preauth key (non-ephemeral)
- [ ] On the agent host: `tailscale up --login-server=https://vpn.kubelab.live --advertise-tags tag:hermes --authkey=<KEY>`
- [ ] Record assigned IP in `networking.nodes` SSOT (`common.yaml`); regenerate inventory
- [ ] Provision hermes's per-service scoped credential(s) via toolkit + SOPS (SSH key / API token) — C6 zero-trust
- [ ] Verify: SSH to hermes over VPN; `headscale nodes list` shows `tag:hermes`; hermes authenticates to a target service with its own credential

## Closing

- [ ] Every acceptance criterion in `proposal.md` covered by a test or documented smoke check
- [ ] `headscale policy check` green in CI; existing test suite has no regressions
- [ ] No unrelated changes in the diff (no scope creep into VPN-ACL-004/005/006)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder

## Machine-readable features

See `features.json` (sibling). Each acceptance criterion → ≥1 feature with executable `verification`. The agent CANNOT set `"state": "passing"` — only the harness may, after capturing exit 0 + `evidence`.
