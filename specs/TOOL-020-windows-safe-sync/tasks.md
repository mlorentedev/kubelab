---
tags: [spec, tasks, templates]
created: "2026-07-08"
---

# Tasks - TOOL-020-windows-safe-sync

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [ ] Branch created from main: `feat/TOOL-020-windows-safe-sync`
- [x] `proposal.md` is complete and acceptance criteria are testable
- [x] No open questions left in `proposal.md` "Risks / open questions" (both MUST-resolve items closed via source investigation)

> AC numbers below map to `proposal.md` Acceptance criteria in order:
> AC1 = `sync all --check` exits 0 on a clean Windows tree
> AC2 = all writers use `newline="\n"`, unit-tested
> AC3 = homepage sync survives non-ASCII without crashing
> AC4 = `windows-latest` CI job runs alongside the existing Linux job
> AC5 = existing Linux CI continues to pass, no regression
> AC6 = `sync all --check` is byte-identical idempotent on both OSes

## Implementation

- [ ] [P] [AC2] Write failing test `tests/test_core_io.py`: `write_text_lf(path, content)` writes exactly `content.encode("utf-8")` with zero `\r` bytes, regardless of host OS (tmp_path fixture, no mocking needed — the whole point is the behavior doesn't depend on the platform).
- [ ] [AC2] Implement `toolkit/core/io.py::write_text_lf(path: Path, content: str) -> None` (`path.write_text(content, encoding="utf-8", newline="\n")`). New tiny module — this is a genuine 4x-duplicated concern, not a speculative abstraction.
- [ ] [AC2] Wire `write_text_lf` into the 4 existing call sites: `sync_k8s_images.py:140`, `sync_oidc_hashes.py:152`, `sync_homepage_config.py:1158` and `:1206`. Refactor only the write call, nothing else.
- [ ] [P] [AC2] Write failing test in `tests/test_sync.py`: `_normalize_content` treats CRLF-authored bytes and LF-authored bytes (same content) as equal.
- [ ] [AC2] Implement: in `toolkit/cli/sync.py::_normalize_content`, add `text = text.replace("\r\n", "\n")` immediately after decode, before the dynamic-pattern substitutions (defense in depth per the ticket).
- [ ] [P] [AC3] Write failing test in `tests/test_toolkit_init.py` (new): after importing `toolkit`, `sys.stdout.encoding` and `sys.stderr.encoding` report `utf-8` (case-insensitive), guarded so the test still passes if the stream doesn't support `reconfigure` (e.g. some pytest capture stream — skip in that case).
- [ ] [AC3] Implement in `toolkit/__init__.py`: on import, `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` and same for `sys.stderr`, wrapped in `try/except (AttributeError, ValueError)` for streams that don't support it.
- [ ] [P] [AC6] Write failing regression test in `tests/test_sync_k8s_images.py` reproducing the exact P1 repro: run `sync_k8s_images.sync()` against a tmp `kustomization.yaml` via `_run_with_check` twice in a row; assert "in sync" both times (no false drift from the write itself).
- [ ] [AC4] Write failing test in `tests/test_sync.py`: two `custom.js` contents — one with all 6 `KUBELAB_DIAGRAMS` entries, one with zero (simulating a full mermaid.ink outage) — normalize equal under `HOMEPAGE_DYNAMIC_PATTERNS`. (A per-value regex can't do this: a failed fetch drops the whole `name: "data:..."` line, not just its payload.)
- [ ] [AC4] Implement: replace the single base64-payload pattern with one that collapses the entire `var KUBELAB_DIAGRAMS = {...};` block to a placeholder in `HOMEPAGE_DYNAMIC_PATTERNS` (`toolkit/cli/sync.py`).
- [ ] [AC3] Harden `render_mermaid_svg` (`sync_homepage_config.py:717-727`): add 2 retries with short backoff before giving up; keep the existing graceful degrade (empty SVG + stderr warning) as the final fallback. Best-effort resilience for the new CI dependency on `mermaid.ink` — not unit-tested (network-dependent), flagged as a residual risk in `verification.md`.
- [ ] [AC4] Add `*.js text eol=lf` to `.gitattributes` (closes the gap: `custom.js` was the one generated-file extension not covered by the repo's existing LF policy).
- [ ] [P] [AC4] Add a `windows-sync-check` job to `.github/workflows/check-config-drift.yml`: `runs-on: windows-latest` (GitHub-hosted — no self-hosted Windows runner exists per ADR-030), checkout, `actions/setup-python@v6` (3.12), install Poetry, `poetry install --only main`, run `poetry run toolkit sync all --check --env staging`. No SOPS/age key needed — `oidc` gracefully skips when SOPS is unavailable.
- [ ] [AC5] Run the full existing test suite + `make lint` locally before opening the PR; confirm no Linux-specific behavior regressed (the fix is additive — explicit `newline=`/`encoding=` instead of platform defaults — not a platform branch).

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
