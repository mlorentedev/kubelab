---
tags: [spec, tasks, templates]
created: "2026-11-13"
id: "EDGE-001-registry-derived-dns"
type: spec-tasks
status: active
owner: manu
---

# Tasks - EDGE-001-registry-derived-dns

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch `feat/registry-derived-edge-dns` (worktree), gate #3495
- [x] Owner rulings 2026-11-13: zones.json grant, #3489 separate PR, `infra/config/products/edge.json`, EDGE-001 over WIP limit
- [ ] Confirm the other session's imagesensortool VPS/DNS applies landed (baseline for AC2 live check)

## Implementation (PR 1: #3495 + #3482)

Characterization first, so the live-edge zero diff is pinned before anything moves.

- [x] [AC2] `tests/test_edge_dns_zero_diff.py`: render Corefile, `pihole-forwarding.conf` and Headscale `split` from master's `networking.staging_zones` and store the expected text. Expected: PASS on master (characterization).
- [x] [P] [AC1][AC3] `tests/test_edge_dns.py` (failing): `derive_staging_zones(registry, snapshots, zones_json, declared)` returns today's three zones in order; dedup keeps first position (web's `staging.mlorente.dev`); a host under `staging.kubelab.live` contributes nothing; a fixture product on a new declared apex adds its zone, and removing it drops it; a host whose apex is not in `zones.json` is refused, naming `zones.json`; a product with no staging lane contributes nothing. Expected: FAIL, `ModuleNotFoundError: toolkit.features.edge_dns`.
- [x] [AC1][AC3] `toolkit/features/edge_dns.py`: `apex_of`, `derive_staging_zones`, `build_manifest`, `sync(check)`, `staging_zones()` accessor reading `edge.json`. Expected: tests PASS.
- [x] [AC1] `toolkit sync edge-dns [--check]` plus a step in `sync all`; generate `infra/config/products/edge.json`; remove `staging.imagesensortool.com` from `common.yaml`. Expected: `make validate-sync ENV=staging` and `ENV=prod` exit 0; a hand edit of `edge.json` makes them exit 1.
- [x] [AC2] Point consumers at the manifest: `coredns/defaults/main.yml`, `deploy-vps.yml`, `product_guards.staging_zones` (accessor), `cli/infra.py`. Expected: the characterization test still PASSES with the effective list.
- [x] [AC3] D8 on the grant: `check_staging_hostname` accepts a `staging.` host whose apex is in `zones.json`, or one label under a declared platform zone, and refuses otherwise, naming `zones.json`. Update `test_product_staging_hostname.py` and `test_product_contract_drift.py`. Expected: PASS.
- [x] [AC2] Move every test that read `networking.staging_zones` as the effective list to the accessor (`test_coredns_*`, `test_headscale_runbook_compose`, `test_dns_zones_map`). Expected: `make test` PASS.
- [x] [P] [AC4] Failing test in `tests/test_acme_token_scope.py`: `acme_probe_zones(env_configs, registry)` includes the apex of each registered product hostname per env, and a registered hostname's apex missing from the probe set fails. Then implement and wire it into `cli/secrets.py`. Expected: PASS.
- [x] [AC5] Receiver: run `toolkit sync edge-dns` after render and `git add infra/config/products/edge.json`; add a static test asserting both. Expected: PASS.
- [x] Docs: `docs/runbooks/headscale-setup.md` §6.1, the `coredns-custom.yaml` comment, CLAUDE.md gotcha, the ADR-067 line 91 amendment, the IDP-053 D8 note and the monitors.json description.
- [x] [AC6] `make mutate` on one derivation line, red; `make test` in full; `make validate-sync` for both envs. ✓ 2026-11-14
- [x] [AC3] The derivation refuses a host that is not `staging.<domain>` (a bare apex would capture prod for VPN clients); mutant red. ✓ 2026-11-14

## Implementation (PR 2: #3489)

- [ ] Derive `prod_records` into `edge.json`; Terraform `local.records` reads it; the coredns hairpin reads it; web's apex record moves; `proxied` defaults to false; the guard is inverted. Owner runs `make tf-dns-plan`: no changes.
- [ ] `tests/test_dns_contract_hostnames.py` reads prod hostnames from the staging snapshots (`contracts/*.yaml`), not `contracts/prod/`, which is what prod deploys; PR 2 replaces that guard, so it reads the prod snapshots there.
- [ ] #3511: the rendered Corefile header still names `networking.staging_zones` (kept for the AC2 zero diff).

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/EDGE-001-registry-derived-dns/features.json`):

```json
[
  {
    "id": "EDGE-001-registry-derived-dns-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
