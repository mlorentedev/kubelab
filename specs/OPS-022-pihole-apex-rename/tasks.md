---
tags: [spec, tasks]
created: "2026-08-11"
---

# Tasks - OPS-022-pihole-apex-rename

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once `implementing` starts.

## Setup

- [x] Branch created from master: `feat/OPS-022-pihole-apex-rename` ✓ 2026-08-11
- [x] `proposal.md` reviewed; no open questions ✓ 2026-08-11
- [x] Both MUST-resolve risks closed (target field = node-name reference; prod-absence = static render test) ✓ 2026-08-11

## Implementation

- [ ] [P] Housekeeping: post the `target` field schema as a comment on #973 (node-name key, resolved via a Terraform variable map, absent → `var.vps_ip`) — coordination step, not itself AC-testable; shared-state action, confirm with the user before posting
- [ ] [AC4] `services.json`: add the `pihole` entry with `"target": "ace1"`. Terraform: variable map in `dns.tfvars` resolving node name → `networking.nodes.ace1.tailscale_ip` (same indirection as `vpn_extra_records`'s `node:` key), absent-target records keep resolving to `var.vps_ip`
- [ ] [AC4] `make tf-dns-plan` — review the plan output (the review gate; apply runs `-auto-approve`), confirm exactly `1 to add, 0 to change, 0 to destroy`
- [ ] [P] [AC3] Write failing test `tests/test_pihole_overlay_render.py`: `kubectl kustomize` both overlays, assert pihole Service/EndpointSlice/IngressRoute present (>0) in staging's render and absent (==0) in prod's — model `test_grafana_alerting_render.py` (subprocess kubectl, skip-loudly-if-missing), not `test_spoke_rbac_covers_manifests.py` (reads files, not the render)
- [ ] [AC3] [AC5] Move `infra/k8s/base/external/pihole.yaml` to the staging overlay (model: prod's `headscale.yaml` overlay-only pattern); update both overlays' `kustomization.yaml` resource lists; rename the `Host()` rule from `pihole.staging.kubelab.live` to `pihole.kubelab.live` — render test goes green
- [ ] [AC1] `expectations.py`: shrink `pihole`'s `skip_in_envs` to `("dev", "prod")`; rewrite the prod entry's inline comment — no longer "domain doesn't resolve outside VPN" (it does now), instead "absence asserted by `tests/test_pihole_overlay_render.py`, not the e2e HTTP suite"
- [ ] Refactor for clarity (extract, rename, dedupe)

### Deploy & verify (ADR-037: staging → verify → merge)

- [ ] Housekeeping: `make tf-dns-apply` — creates the new `pihole.kubelab.live` A record (after the plan reviewed above); enables AC2/AC5 verification below, not itself an AC
- [ ] Housekeeping: `make deploy-k8s ENV=staging` — ships the overlay move; enables AC1/AC5 verification below, not itself an AC
- [ ] [AC1] `make test-e2e ENV=staging` observes 200/302 for Pi-hole, asserted live (not carried over from the 2026-08-11 measurement — #959's trigger is unreproduced; a reappearing 502 blocks this spec)
- [ ] [AC2] `dig +short pihole.kubelab.live @vita.ns.cloudflare.com` returns `networking.nodes.ace1.tailscale_ip` (authoritative NS, not a public resolver — TTL caching)
- [ ] [AC5] `curl -sk https://pihole.staging.kubelab.live/admin/` from a tailnet client returns the staging catch-all 404 — not 502, not Pi-hole
- [ ] [AC3] `make test` (workstation, homelab may be off) confirms the render test passes — no CI workflow runs pytest, so this AC is workstation-verified

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder — prod absence rides the merge via Argo CD auto-sync (`selfHeal: true`, ADR-037), nothing to deploy to prod by hand

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state.

```json
[
  {
    "id": "OPS-022-pihole-apex-rename-f1",
    "behavior": "Staging e2e asserts Pi-hole 200/302 instead of skipping it",
    "verification": "make test-e2e ENV=staging -- -k pihole",
    "state": "pending",
    "evidence": ""
  },
  {
    "id": "OPS-022-pihole-apex-rename-f2",
    "behavior": "pihole.kubelab.live resolves publicly to ace1's tailnet address",
    "verification": "test \"$(dig +short pihole.kubelab.live @vita.ns.cloudflare.com)\" = \"$(yq '.networking.nodes.ace1.tailscale_ip' infra/config/values/common.yaml)\"",
    "state": "pending",
    "evidence": ""
  },
  {
    "id": "OPS-022-pihole-apex-rename-f3",
    "behavior": "Prod render has zero pihole objects, staging render has all three",
    "verification": "pytest tests/test_pihole_overlay_render.py",
    "state": "pending",
    "evidence": ""
  },
  {
    "id": "OPS-022-pihole-apex-rename-f4",
    "behavior": "target field is backward-inert for the other 11 records",
    "verification": "make tf-dns-plan | grep -q '1 to add, 0 to change, 0 to destroy'",
    "state": "pending",
    "evidence": ""
  },
  {
    "id": "OPS-022-pihole-apex-rename-f5",
    "behavior": "Old staging-scoped name is dark, not aliased",
    "verification": "test \"$(curl -sk -o /dev/null -w '%{http_code}' https://pihole.staging.kubelab.live/admin/)\" = \"404\"",
    "state": "pending",
    "evidence": ""
  }
]
```
