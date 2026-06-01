---
tags: [spec, tasks]
created: "2026-05-31"
---

# Tasks - VPNACL-001-fleet-segmentation

> One task = one focused commit. Tick as you go. Reorder freely while `draft`; freeze on `implementing`.
> BLOCKER before implementation: resolve the `[AGENT-DRAFT]` open questions in `proposal.md` (esp. the `tag:hermes` dst matrix).

## Setup

- [x] Branch created from master: `feature/vpn-acl-fleet-segmentation` ✓ 2026-05-31
- [x] `proposal.md` complete; `[AGENT-DRAFT]` items in "Risks / open questions" resolved ✓ 2026-05-31
- [x] Confirm on the live v0.28.0 VPS: `headscale nodes tag --help`, `headscale preauthkeys create --help` (exact tag flags) ✓ 2026-05-31 — `nodes tag -i <ID> -t <tag>`; `preauthkeys create -u <ID> --tags <tag> --reusable -e <expiry>` (default 1h); `policy check` present; users manu(1)/kubelab(2)/work(3), no `agents` yet

## VPN-ACL-001 — Parameterize the headscale role ✓ 2026-05-31

- [x] Test: a generated `config.yaml` renders `policy.path` from a role var (not hardcoded `""`); default var = `""` keeps current allow-all (no-op refactor) — `tests/test_headscale_role.py::TestPolicyPathParameterized`
- [x] Test: handler reloads via **SIGHUP** (`docker kill --signal=HUP headscale`), NOT a restart; policy-file change notifies the reload handler, config.yaml change keeps the restart path (SEPARATE — finding #1) — `TestReloadHandler` + `TestPolicyFileDeploy`
- [x] Expose `headscale_policy_path` in `roles/headscale/defaults/main.yml`; template it in `config.yaml.j2`
- [x] Task: render `policy.hujson.j2` to the VPS config dir (bind-mounted `./config` → `/etc/headscale`, `:ro`) idempotently, conditional on `headscale_policy_path` set (permissive-first seed; baseline content authored in VPN-ACL-002)
- [x] Handler: `docker kill --signal=HUP headscale` (Docker Compose, NOT systemd; NOT restart) triggered on policy-file change only
- [x] Fix in passing: collapse the redundant double health-wait (removed the `wait for headscale` handler + its notify; the always-run inline health gate remains) — finding #5
- [x] Wire deploy through the Makefile/toolkit — satisfied by existing `deploy-vps.yml:129` role invocation (`make deploy TARGET=vps ENV=prod`); dormant until VPN-ACL-002 sets `headscale_policy_path`

## VPN-ACL-002 — Author policy.hujson (permissive-first) + probe + CI gate ✓ 2026-05-31 (code)

- [x] Author `policy.hujson.j2`: `tagOwners` (`tag:hermes` owned by `kubelab@`), permissive-first `acls` baseline (existing users keep allow-all; tag replaces user → agents excluded) + `tag:hermes` node-like egress (`vps:443`, `beelink:9000`); hosts rendered from the networking SSOT (no hardcoded IPs)
- [x] `headscale policy check` passes locally (`make check-headscale-policy` → "Policy is valid", real v0.28 binary) + CI gate in `check-config-drift.yml` (prod, via `toolkit infra headscale policy-check`)
- [x] External connectivity-probe harness (`toolkit infra headscale probe`): declarative preserved-flow checks (admin SSH, hub→spoke `:6443`, rpi4 route, intra-K3s, monitoring); required flows must hold, optional homelab flows skip when source is down
- [x] Auto-revert: role backs up `.prev`, probes after SIGHUP reload (block), restores + reloads + fails on probe failure (rescue)
- [x] Probe assertions authored as `(src, dst, port)` Flow tuples → migrate 1:1 into the v0.29 `tests` block (VPN-ACL-006)
- [ ] **ACTIVATE on prod**: set `headscale_policy_path` + `make deploy TARGET=vps ENV=prod` (renders policy, SIGHUP reload, probe confirms) — pending go-live

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
