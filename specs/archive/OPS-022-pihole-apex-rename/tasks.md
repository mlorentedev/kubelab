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

- [x] [P] Housekeeping: post the `target` field schema as a comment on #973 ✓ 2026-08-12
- [x] [AC4] `services.json`: added the `pihole` entry with `"target": "ace1"`; Terraform variable map `node_tailscale_ips` in `main.tf` (`services_resolved` local), absent-target records unchanged ✓ 2026-08-12
- [x] [AC4] `make tf-dns-plan` reviewed — exactly `1 to add, 0 to change, 0 to destroy`, content `100.64.0.11` ✓ 2026-08-12
- [x] [P] [AC3] `tests/test_pihole_overlay_render.py` written (model `test_grafana_alerting_render.py`) ✓ 2026-08-12
- [x] [AC3] [AC5] `pihole.yaml` moved to the staging overlay; both `kustomization.yaml`s updated; `Host()` renamed to `pihole.kubelab.live` — render test green ✓ 2026-08-12
- [x] [AC1] `expectations.py`: `skip_in_envs` shrunk to `("dev", "prod")`, prod comment rewritten ✓ 2026-08-12
- [x] Refactor for clarity — n/a, no rework needed ✓ 2026-08-12

### Deploy & verify (ADR-037: staging → verify → merge)

- [x] Housekeeping: `make tf-dns-apply` — 1 added, 0 changed, 0 destroyed ✓ 2026-08-12
- [x] Housekeeping: `make deploy-k8s ENV=staging` — applied; see verification.md for the live Argo CD selfHeal drift (#1016) hit and worked around along the way ✓ 2026-08-12
- [x] [AC1] `make test-e2e ENV=staging -k pihole` — 5 passed ✓ 2026-08-12
- [x] [AC2] `dig +short pihole.kubelab.live @vita.ns.cloudflare.com` → `100.64.0.11`, matches `networking.nodes.ace1.tailscale_ip` ✓ 2026-08-12
- [x] [AC5] `curl` against the old name → HTTP 404 (staging catch-all) ✓ 2026-08-12
- [x] [AC3] `pytest tests/test_pihole_overlay_render.py` — 2 passed ✓ 2026-08-12

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by at least one test ✓ 2026-08-12
- [x] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command ✓ 2026-08-12
- [x] Type checks pass ✓ 2026-08-12 (`poetry run mypy` on the four touched toolkit modules — clean)
- [x] Lint passes ✓ 2026-08-12 (`poetry run ruff check` on every touched file — clean; 5 pre-existing errors elsewhere in the repo are unrelated to this spec)
- [x] No unrelated changes in the diff (no scope creep) ✓ 2026-08-12 (confirmed independently in `review.md`'s Scope=A rating)
- [x] `verification.md` filled in ✓ 2026-08-12
- [x] PR opened referencing this spec folder — prod absence rides the merge via Argo CD auto-sync (`selfHeal: true`, ADR-037), nothing to deploy to prod by hand ✓ 2026-08-12 (#1017, #1028)

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
