---
tags: [spec, verification, templates]
created: "2026-07-08"
---

# Verification - TOOL-020-windows-safe-sync

## Evidence

- **AC1** (`sync all --check` exits 0 on a clean Windows tree) -> real end-to-end run on this Windows workstation: `poetry run toolkit sync all --check --env staging` printed `[SUCCESS] All generated files in sync`, exit code 0; `git status --short` clean afterward. Not a synthetic test — the actual repo, actual OS.
- **AC2** (writers use `newline="\n"`, unit-tested) -> `tests/test_core_io.py::TestWriteTextLf` (3 tests), `tests/test_sync.py::TestNormalizeContent::test_crlf_and_lf_normalize_equal`, `tests/test_sync_k8s_images.py::TestWindowsSafeCheckIdempotency` (2 tests, includes the non-ASCII read-encoding regression).
- **AC3** (homepage sync survives non-ASCII without crashing) -> `tests/test_toolkit_init.py::TestForceUtf8Stdio` (4 tests, real `cp1252` stream repro + fix proof) and `tests/test_sync_homepage_config.py::TestRenderMermaidSvgRetries` (3 tests).
- **AC4** (`windows-latest` CI job alongside Linux) -> `.github/workflows/check-config-drift.yml` `windows-sync-check` job (added, not yet run in CI — will confirm green on the PR).
- **AC5** (no regression) -> full suite 345 passed / 108 deselected; `ruff check` + `ruff format --check` clean; `mypy` shows only the 2 pre-existing, unrelated `generator_authelia.py` errors confirmed present on `master` via `git stash`.
- **AC6** (idempotent on both OSes) -> `tests/test_sync_k8s_images.py::TestWindowsSafeCheckIdempotency::test_check_reports_in_sync_after_its_own_write`, and the AC1 real-run evidence above (Windows). Linux side not independently re-verified on this branch — CI (AC4) is the cross-platform proof once the PR runs.

## Test status

- Test suite: `poetry run pytest -q --no-cov` -> 345 passed, 108 deselected (slow/e2e/integration markers), 0 failed.
- Lint: `poetry run ruff check toolkit` -> all checks passed. `poetry run ruff format --check toolkit` -> 59 files already formatted.
- Type check: `poetry run mypy toolkit` -> 2 errors, both pre-existing and unrelated (`generator_authelia.py:25`, `os.geteuid`/`os.getegid` under Windows mypy stubs — confirmed present on `master` before this branch via `git stash`/`git stash pop`).
- Manual smoke test: ran `poetry run toolkit sync all --check --env staging` directly against the real repo on this Windows workstation, iterating until green (see AC1 evidence). Also ran `toolkit sync homepage` / `toolkit sync images` (non-check) once each to diagnose the two adjacent bugs found, then reverted the resulting working-tree changes with `git checkout --`.
- No regressions in existing test suite: yes — same 338 pre-existing tests all still pass, plus 7 new test modules/additions (test_core_io.py, test_toolkit_init.py, test_sync_homepage_config.py, plus additions to test_sync.py and test_sync_k8s_images.py).

## Decisions made during implementation

- **AC3 test redesign**: the originally planned test ("after importing toolkit, `sys.stdout.encoding` reports utf-8") is a false positive — pytest's own capture is already UTF-8 regardless of host OS, so it can't detect the real bug. Rebuilt around a manufactured `cp1252` `TextIOWrapper`, which genuinely reproduces `UnicodeEncodeError` on `→` before the fix and is neutralized by `force_utf8_stdio()` after.
- **AC6 test redesign**: the first regression test built its "before" baseline by calling the (buggy) `sync()` itself, so it compared the CRLF bug against itself and passed even unfixed — a tautology, not a regression guard. Rebuilt with an independently-authored LF baseline (mirroring a real git checkout under `.gitattributes`); verified by reverting both the writer and comparator fixes together and confirming the test then fails.
- **HOMEPAGE_DYNAMIC_PATTERNS approach changed mid-implementation**: originally planned to collapse the entire `KUBELAB_DIAGRAMS` block to a placeholder to tolerate a partial mermaid.ink outage. Rejected because that would also mask genuine SSOT drift in the ASCII sections sharing the same object. Instead made `generate_diagrams` always emit every key (empty string on fetch failure, never a dropped key) and widened the existing per-value base64 regex from `+` to `*` — narrower, preserves real drift detection elsewhere.
- **Two adjacent, pre-existing bugs found and fixed, both confirmed with the user first** (crossed the proposal's own "Out of scope" line, so treated as a deliberate exception rather than silent scope creep):
  1. Five `open()`/`read_text()` calls across the sync scripts had no `encoding=`, so on this Windows box (cp1252 locale) reading existing UTF-8 content with em-dashes/middots silently corrupted it (mojibake, not a crash) before ever reaching the CRLF issue. Same root-cause class as the ticket's write-side fix; not previously visible because nobody had run the full `sync all --check` on Windows before this ticket.
  2. `sync_homepage_config.py` resolved n8n's version from the wrong `common.yaml` path (`services.core.n8n` instead of `services.automation.n8n`), always producing an empty version and reading as permanent SSOT drift — a pre-existing, OS-independent bug that blocked AC1/AC4 from being achievable at all in this repo's current state.
- **mermaid.ink retry hardening** ended up fully unit-testable (mocked `urlopen`), not left as an untested "best-effort" item as originally scoped in `tasks.md`.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons.md`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/<feature-id>/` -> `specs/archive/<feature-id>/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
