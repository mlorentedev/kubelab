---
id: "TOOL-020-windows-safe-sync"
type: spec
status: verifying # draft | implementing | verifying | archived
created: "2026-07-08"
issue: "kubelab#835"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# TOOL-020: Windows-safe sync lane

> **Naming**: file lives at `<repo>/specs/<feature-id>/proposal.md`. `<feature-id>` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #835: TOOL-020: Windows-safe sync lane — CRLF false drift + charmap crash break validate-sync -->

Windows is an explicitly supported operator platform per ADR-052 (`operate-from-new-workstation.md` onboards a non-admin Windows box through the full deploy lane). On Windows, `toolkit sync all --check` — and therefore `make validate-sync`, `make check`, and the `make deploy-k8s` prerequisite chain — permanently fails on a clean tree: `sync_k8s_images.py` writes CRLF via `write_text()` with no `newline=`, which the byte-level comparator reports as false drift, and the homepage sync crashes encoding `→` under cp1252. Without this fix, every Windows-based operator or agent is stranded at the exact step ADR-052 was written to unblock, and the tool's own suggested remediation ("run sync, then commit") would commit CRLF-polluted files.

## What

After this change, `toolkit sync all --check` (and everything that depends on it: `make validate-sync`, `make check`, `make deploy-k8s`) passes on a clean tree **on both Windows and Linux** — this is a cross-platform fix, not a Windows-only patch that could regress the existing Linux/CI lane. Concretely: (1) all sync writers emit LF-only content regardless of host OS, (2) the drift comparator normalizes newlines so any pre-existing CRLF-vs-LF difference doesn't cause spurious drift on either OS, (3) homepage sync no longer crashes on non-ASCII characters (forced UTF-8 I/O, verified on both platforms), (4) a `windows-latest` CI job runs alongside the existing Linux CI (not replacing it) so both platforms are continuously proven green.

## Out of scope

Things this PR explicitly does NOT include. Forces a sharp boundary and prevents scope creep.

- The other P-findings from the process audit (preflight doctor, Ansible transport for non-mesh controllers, machine-readable CLI output, strict deploy exit semantics) — tracked as separate tickets (#834 OPS-013 second pass, and the missing-process backlog items).
- Migrating `toolkit sync` off Rich/stdout logging — that is TOOL-022 (#839).
- The actual image-tag or homepage content logic — only the write/compare/encode mechanics change.

## Risks / open questions

Failure modes, dependencies, and unknowns to clarify before implementation. If any item here is unresolved, do not move to `tasks.md` yet.

- ~~**MUST resolve before coding:** does forcing `PYTHONUTF8=1` / explicit `encoding="utf-8"` on all toolkit I/O have any unintended effect on other CLI output?~~ **RESOLVED:** the actual crash is a bare `print()` in `sync_homepage_config.py:1208` that bypasses the Rich-backed `PlatformLogger` and writes straight to `sys.stdout`, which defaults to the Windows console codepage (cp1252). Rich's `Console` manages its own encoding and is unaffected. Forcing `PYTHONUTF8=1` (or `sys.stdout.reconfigure(encoding="utf-8")`) at the entry point only widens the 4 bare `print()` calls in `toolkit/scripts/*.py`. Worst case on a legacy non-Unicode Windows console: an unsupported glyph renders as a placeholder box — a visual nit, not a crash or functional regression.
- ~~**MUST resolve before coding:** does any generated file legitimately need CRLF?~~ **RESOLVED:** none. `.gitattributes` already declares an LF-only policy for `*.yaml`/`*.yml`/`*.md` repo-wide (comment: "Windows core.autocrlf=true would otherwise check these out as CRLF, which breaks yamllint"). This fix is consistent with, not a departure from, existing repo policy — it extends the same LF guarantee from git-checkout time to script-write time. One gap found: `custom.js` (homepage output) has no `.gitattributes` entry — add `*.js text eol=lf`.
- Risk (not blocking): `windows-latest` GitHub Actions runner availability — ADR-030 routes CI to a self-hosted Linux runner via `fromJSON(vars.RUNNER_DOCKER)`; there is no self-hosted Windows runner, so this new job needs an explicit `windows-latest` (GitHub-hosted) runner reference rather than the shared routing variable. Confirm the workflow can mix runner types per job.

## Acceptance criteria

Observable outcomes. Each must be testable.

- [x] `toolkit sync all --check --env staging` exits 0 on a clean Windows tree with no prior sync run (reproduces and resolves the P1 repro in `process-audit-2026-07-07.md`) — verified with a real run on this Windows workstation, see `verification.md`
- [x] All generated-file writers in `toolkit/scripts/` write with `newline="\n"` (or equivalent), verified by a unit test asserting zero `\r` bytes in output
- [x] Homepage sync completes without a `UnicodeEncodeError` when non-ASCII characters (e.g. `→`) are present in source content
- [x] A `windows-latest` CI job runs `toolkit sync all --check` on every PR and is green, running **alongside** (not instead of) the existing Linux CI job — confirmed on PR #843: "Sync check (Windows)" passed in 2m1s
- [x] The existing Linux CI lane continues to pass `toolkit sync all --check` with no regression — confirmed on PR #843: "Drift / staging" and "Drift / prod" both passed (41s / 44s)
- [x] `sync all --check` leaves the working tree byte-identical before/after on both Windows and Linux (idempotency, extended from the existing Linux-only guarantee) — Windows side verified directly; Linux side verified by construction (same code path, no OS branch) and pending CI confirmation

## References

- Bitácora board: the GitHub issue / Project item tracking this spec (see the `issue:` frontmatter field)
- Related ADR: `<repo>/docs/adr/adr-XXX.md` (if any)
- Related patterns: `00_meta/patterns/<pattern>.md` (if any)
