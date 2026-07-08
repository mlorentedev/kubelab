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

- [x] Branch created from main: `feat/TOOL-020-windows-safe-sync`
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

- [x] [P] [AC2] Write failing test `tests/test_core_io.py`: `write_text_lf(path, content)` writes exactly `content.encode("utf-8")` with zero `\r` bytes, regardless of host OS (tmp_path fixture, no mocking needed — the whole point is the behavior doesn't depend on the platform).
- [x] [AC2] Implement `toolkit/core/io.py::write_text_lf(path: Path, content: str) -> None` (`path.write_text(content, encoding="utf-8", newline="\n")`). New tiny module — this is a genuine 4x-duplicated concern, not a speculative abstraction.
- [x] [AC2] Wire `write_text_lf` into the 4 existing call sites: `sync_k8s_images.py:140`, `sync_oidc_hashes.py:152`, `sync_homepage_config.py:1158` and `:1206`. Refactor only the write call, nothing else.
- [x] [P] [AC2] Write failing test in `tests/test_sync.py`: `_normalize_content` treats CRLF-authored bytes and LF-authored bytes (same content) as equal.
- [x] [AC2] Implement: in `toolkit/cli/sync.py::_normalize_content`, add `text = text.replace("\r\n", "\n")` immediately after decode, before the dynamic-pattern substitutions (defense in depth per the ticket).
- [x] [P] [AC3] Write failing test in `tests/test_toolkit_init.py` (new). **Revised during implementation**: pytest's own stdout capture is already UTF-8 regardless of host OS, so asserting `sys.stdout.encoding` inside a normal test proves nothing. Rewrote as: manufacture a real `cp1252` `TextIOWrapper` via monkeypatch, prove it genuinely raises `UnicodeEncodeError` on `→` (real repro), then prove `force_utf8_stdio()` neutralizes it.
- [x] [AC3] Implement `toolkit/core/io.py::force_utf8_stdio()` (reconfigures `sys.stdout`/`sys.stderr` to UTF-8, tolerating streams without `.reconfigure`); called once at `toolkit/__init__.py` import time.
- [x] [P] [AC6] Write failing regression test in `tests/test_sync_k8s_images.py` reproducing the exact P1 repro. **Revised during implementation**: the first version built its LF baseline by calling the (buggy) `sync()` itself, so it compared the bug against itself and passed even unfixed. Rewrote so the baseline is built independently (mirroring "what's checked out from git, LF per `.gitattributes`") — verified this version genuinely fails when both the writer and comparator fixes are reverted together.
- [x] [AC4] Write failing test in `tests/test_sync.py`: an SVG payload with content vs. one with an empty payload (simulating a full mermaid.ink outage) normalize equal under `HOMEPAGE_DYNAMIC_PATTERNS`.
- [x] [AC4] Implement: **revised approach** — instead of collapsing the whole `KUBELAB_DIAGRAMS` block (which would also hide genuine SSOT drift in the ASCII sections sharing that object), made `generate_diagrams` always emit every diagram key with an empty-string fallback on fetch failure (never drops the key), and widened the existing base64-payload regex from `+` to `*` so an empty payload still normalizes.
- [x] [AC3] Harden `render_mermaid_svg` (`sync_homepage_config.py`): 2 retries with backoff before giving up; unit-tested with a mocked `urlopen` (succeeds first try / retries-then-succeeds / exhausts retries) — **more testable than anticipated**, not left network-dependent-only as originally scoped.
- [x] [AC4] Add `*.js text eol=lf` to `.gitattributes` (closes the gap: `custom.js` was the one generated-file extension not covered by the repo's existing LF policy).
- [x] [P] [AC4] Add a `windows-sync-check` job to `.github/workflows/check-config-drift.yml`: `runs-on: windows-latest`, checkout, `actions/setup-python@v6` (3.12), install Poetry, `poetry install --only main`, run `poetry run toolkit sync all --check --env staging`.
- [x] [AC2] **Found during implementation, not in the original ticket**: `kustomization.read_text()` / `file_path.read_text()` (`sync_k8s_images.py`, `sync_oidc_hashes.py`) and `open(COMMON_YAML)` (`sync_k8s_images.py`, `sync_homepage_config.py`, `sync_operators.py`) had no `encoding=`, so on a non-UTF-8-locale host (this Windows box: cp1252) reading existing UTF-8 content with em-dashes/middots silently mis-decoded it — then re-writing re-encoded the already-corrupted text (mojibake, not a crash). Same root-cause class as the write side; added `encoding="utf-8"` to all 5 call sites. Regression-tested via `test_preserves_non_ascii_comments_on_reread`.
- [x] [AC1] **Found during implementation, not in the original ticket**: `sync_homepage_config.py` resolved n8n's version via `services.get("core", {}).get("n8n", {})`, but `common.yaml` has it at `apps.services.automation.n8n` — always empty, read as permanent SSOT drift on every run (any OS, not Windows-specific). Fixed the one-line path; without it, `sync all --check` could never pass and the new CI job could never go green. Confirmed with the user before fixing (crossed the proposal's own Out-of-scope line) — approved as a blocking, obviously-correct one-liner. Unit-tested in `tests/test_sync_homepage_config.py`.
- [x] [AC5] Ran the full existing test suite + `make lint` (ruff check + format) + `mypy` locally. 345 passed, ruff clean. 2 pre-existing `mypy` errors in `generator_authelia.py` (`os.geteuid`/`os.getegid` — POSIX-only, flagged under Windows mypy stubs) confirmed present on `master` before this branch (verified via `git stash`) — unrelated, not touched.
- [x] [AC1] **Real end-to-end verification**: ran `poetry run toolkit sync all --check --env staging` directly on this Windows workstation against the actual repo (not a synthetic test). Iterated until it printed `[SUCCESS] All generated files in sync` and exited 0; confirmed `git status` clean afterward (the check's snapshot/restore left no residue).

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by at least one test
- [x] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command
- [x] Type checks pass (pre-existing unrelated errors excluded, see above)
- [x] Lint passes
- [x] No unrelated changes in the diff — two adjacent bugs (non-ASCII read encoding, n8n path) were fixed because they directly blocked this ticket's own acceptance criteria; both confirmed with the user before fixing and documented separately from the core CRLF/UTF-8 fix
- [x] `verification.md` filled in
- [x] PR opened referencing this spec folder — PR #843, `Closes #835`, all CI checks passing including the new `windows-sync-check` job

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
