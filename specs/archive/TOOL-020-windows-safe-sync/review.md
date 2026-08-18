---
spec: "TOOL-020-windows-safe-sync"
verdict: "PASS"
reviewed_sha: "c18c3503bd716dcc16cb52d1d24b278fa8e8da8c"
reviewer: "nan/deepseek-v4-flash"
date: "2026-08-17"
---

## Adversarial review

**Scope**: TOOL-020-windows-safe-sync — PR #843 (`feat/TOOL-020-windows-safe-sync` → `master`, merged as `06f3102`, `Closes #835`)
**Sources**: `specs/TOOL-020-windows-safe-sync/{proposal,tasks,verification,features}.json`; `git show 06f3102` (full diff); working-tree reads at HEAD `c18c350`; live test/lint/mypy runs below.

### Spec and task alignment

- All 6 acceptance criteria (AC1–AC6) are ticked in `proposal.md`, each maps to ≥1 named test in `verification.md`, and each has a `features.json` entry with a non-vacuous `verification` command and non-empty `evidence`. No `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tags remain in any spec file.
- Two pre-existing bugs were fixed beyond the ticket's literal scope (non-ASCII read `encoding=`, n8n `common.yaml` path). Both are documented in `tasks.md`/`verification.md`, and both were confirmed with the maintainer before being included; both directly blocked AC1/AC4. This is a declared, human-approved exception, not silent scope creep.
- Spec says "no OS branch in the sync path" (AC6, "Linux side verified by construction"); code confirms — `write_text_lf`, `_normalize_content` newline normalization, and `force_utf8_stdio` are platform-agnostic, with the only OS-specific artifact being the new CI job. Consistent.
- `features.json` contains no `passing` entry with empty `evidence`. All six carry concrete outputs (local runs + CI job IDs/times).

### Verification runs performed during this review (Linux, HEAD c18c350)

- `pytest -q --no-cov` → **592 passed, 142 deselected, 0 failed** (full suite; supersedes the 345-passed figure from review time, which was then accurate).
- `pytest tests/test_core_io.py tests/test_sync.py tests/test_sync_homepage_config.py tests/test_sync_k8s_images.py tests/test_toolkit_init.py -q` → 47 passed.
- `mypy toolkit/` → Success, no issues (the two pre-existing `generator_authelia.py` errors cited in `verification.md` are gone at HEAD — fixed by later commits; the claim was correct for the reviewed sha).
- `ruff check toolkit/` → clean; `ruff format --check toolkit/` → 64 files formatted.
- `toolkit sync all --check --env staging` (live, real repo) → `[SUCCESS] All generated files in sync`, exit 0.
- **Mutation test (writer + comparator reverted together):** injected `newline="\r\n"` into `write_text_lf` *and* removed the `\r\n → \n` normalization in `_normalize_content`; `tests/test_sync_k8s_images.py::TestWindowsSafeCheckIdempotency::test_check_reports_in_sync_after_its_own_write` then **fails** ("drift detected in 1 file(s)"). Restored both; suite green again. The `verification.md` claim that the idempotency test is a genuine regression guard is **independently confirmed**. Working tree left clean.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | THEORETICAL | test coverage | `generate_diagrams`' "always emit every key on fetch failure" behavior (`svgs[name] = svg` moved before the `if svg:` check) has **no direct unit test** — only the retry logic of `render_mermaid_svg` and the *normalization* of an already-empty payload are tested. A future refactor that reverts the move (dropping the key again) would pass every unit test; only the end-to-end CI drift gate would catch it. | Code read of `toolkit/scripts/sync_homepage_config.py` (line moved, `svgs[name] = svg` unconditional); grep for `generate_diagrams` in `tests/` finds no direct caller. | UNTESTED — nearest coverage is `tests/test_sync.py::TestNormalizeContent::test_svg_payload_normalizes_regardless_of_length` (assumes the empty payload exists, does not prove the code produces it) and `TestRenderMermaidSvgRetries` (tests the helper, not the loop). | tests — add a case mocking `render_mermaid_svg` to fail and asserting the rendered output contains every diagram key. Not archive-blocking (end-to-end + Windows CI cover it). |
| Minor | THEORETICAL | test design | The CRLF regression tests are **false positives on Linux/CI**: `test_writes_lf_only_regardless_of_host_os` (asserts `b"\r" not in raw`) and `test_check_reports_in_sync_after_its_own_write` pass even with `write_text_lf` writing CRLF, because on Linux `os.linesep` is `\n` (verified by mutation: injected `newline="\r\n"` and both still passed). The real guard is the new `windows-latest` CI job, not these unit tests. `verification.md` presents them as proof without disclosing the platform limitation. | Mutation run above: CRLF-injecting `write_text_lf` → `TestWindowsSafeCheckIdempotency` still green on Linux. | spec artifacts — document in `verification.md` that these two tests are Windows-gated in effect; consider a `sys.platform == "win32"`-conditioned assertion. Not a defect: the Windows CI job does close the loop. |
| Minor | THEORETICAL | adjacent code | Same root-cause class (locale-default `open()`/writes) persists in `toolkit/features/promotion.py`: `_promote_errors` and `promote` write SSOT files (`common.yaml`, `values/<env>.yaml`) via `open(path, "w")` with no `encoding=` / `newline="\n"` — CRLF + cp1252 corruption risk for a Windows operator running `deployment promote --app errors`. Outside this spec's declared scope (`toolkit/scripts/` writers) and not part of the `sync all --check` chain, so it does not block TOOL-020; flagged as follow-up debt. | `grep -n "open(" toolkit/features/promotion.py` → lines 135, 187 without `encoding=`. | UNTESTED | code (fix `promotion.py` writes) + a ticket; out of scope here. |
| Minor | SPECULATIVE | comparator | `_normalize_content` normalizes `\r\n` but not a lone `\r` (old Mac-style). No modern tooling in this repo's lane emits bare `\r`; unobserved. | Direct probe: `_normalize_content(b'images:\r  - name: foo\n', [])` returns input unchanged. | UNTESTED | spec artifacts (note as known limitation); do not gate. |

No Blocker or Major findings. The two REAL-class claims in `verification.md` (test genuinely fails when both fixes are reverted; the cp1252 test reproduces the crash before the fix) were independently reproduced or are directly corroborated by the code and test construction.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness | B | All 6 ACs met; happy paths verified end-to-end; negative-path gap is narrow (one untested loop branch), no observed defects. |
| Verification | B | Evidence reproducible (I re-ran it); slight overstatement on platform-dependence of the CRLF tests. |
| Scope | B | Two adjacent-but-blocking bugs fixed; both pre-approved by the maintainer and documented — a disclosed exception, not creep. |
| Reliability | B | Retry-with-backoff, graceful SVG degradation, snapshot restore on error, no new error paths unhandled; same-class gap noted in `promotion.py` (out of scope). |
| Maintainability | A | `toolkit/core/io.py` collapses a 4x-duplicated concern; ≤40-line functions, comments explain WHY; no dead code. |
| Handoff-readiness | B | Spec complete, lessons already captured (`8518a5b`), archive checklist present; minor deferred test gaps tracked above. |

### Verdict
PASS

### Recommended next steps (before archive)
- Optional (not blocking): add the `generate_diagrams` always-emit-every-key unit test so the behavior is not solely guarded by end-to-end CI.
- Optional: disclose in `verification.md` that the CRLF unit tests are effectively Windows-gated and the `windows-sync-check` job is the cross-platform proof.
- File a follow-up ticket for the `promotion.py` locale-default write gap (same root-cause class, outside TOOL-020 scope).
- `dotf spec archive TOOL-020-windows-safe-sync` is **advisable** in the current state: review fresh, no draft tags, all six `features.json` entries passing with evidence, no blocker/major findings, rubric all B or above.
