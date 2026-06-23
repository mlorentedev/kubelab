---
tags: [spec, tasks, templates]
created: "2026-06-21"
---

# Tasks - TOOL-014-k8s-connect

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.

## Setup

- [x] Branch created from main: `feat/TOOL-014-k8s-connect`
- [x] `proposal.md` is complete and acceptance criteria are testable
- [x] No open questions left in `proposal.md` "Risks / open questions" (the one empirical unknown is a verify step, not a blocker)

## Implementation

> TDD order. Pure helpers first (unit-tested, no network), then the I/O commands, then CLI + Makefile + runbook.

- [x] SSOT: **derive** the target (no `clusters:` edit needed) — `apiserver_port` defaults to 6443 in code, overridable via `clusters.<env>.apiserver_port`
- [x] Test: position-aware mesh-target resolver — `staging->networking.nodes.ace1.tailscale_ip`, `prod->networking.vps`, `hub->networking.aws` — derives `host:apiserver_port`, never hardcodes an IP
- [x] Implement the resolver in `toolkit/features/k8s_connect.py` (`_node_block`, reuses the SSOT-014a homelab-vs-cloud lookup)
- [x] Test: transport selection — prod resolves the public endpoint (direct), staging/hub resolve ts-bridge over the mesh
- [x] Implement transport selection (capability: a node with `public_ip` -> public; else ts-bridge mesh)
- [x] Test: ts-bridge argv builder (`--target`, `--local-addr`, `--manual-mode`) + binary discovery (`TS_BRIDGE_BIN` -> default -> PATH; clear error when absent)
- [x] Implement argv builder + binary discovery
- [x] Test: transport statefile read/write/path (pid + env + local_port) drives idempotency
- [x] Implement the statefile model
- [x] Implement `access status` (pure check: statefile + `127.0.0.1:<local_port>` listening -> up/down + resolved transport)
- [x] Implement `access connect` (idempotent: no-op if up for env; else spawn detached, write statefile, healthcheck the local port)
- [x] Implement `access disconnect` (read statefile, terminate, remove statefile; no-op if already down)
- [x] Wire the `access` sub-Typer under `k8s_app` in `toolkit/cli/infra.py` (legacy `k8s status` untouched)
- [x] Add delegating `make connect|disconnect|connect-status ENV=x` targets (no inline scripts)
- [x] Write `docs/runbooks/operate-from-new-workstation.md`

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by a test (AC1 live-validation pending; code path unit-tested)
- [x] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [x] Type checks pass (my files; 2 pre-existing unrelated errors in `generator_authelia.py`)
- [x] Lint passes
- [x] No unrelated changes in the diff (no scope creep)
- [x] `verification.md` filled in
- [x] PR opened referencing this spec folder — merged via PR #732 (`3b861eb`, ADR-052, #731)

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/<feature-id>/features.json`):

```json
[
  {
    "id": "<feature-id>-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
