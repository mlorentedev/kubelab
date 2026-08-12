---
spec: "OPS-022-pihole-apex-rename"
verdict: "PASS"
reviewed_sha: "7beec52"  # squash-merge of PR #1027, whose head (dbbf886) this review actually examined — same content, patch-id matched
reviewer: "claude-sonnet-5"
date: "2026-08-12"
---

## Adversarial review

**Scope**: OPS-022-pihole-apex-rename, re-reviewed against `master` (a043e77) plus open PR `mlorentedev/kubelab#1027` (`fix/homepage-pihole-domain`, head `dbbf886`, MERGEABLE, not yet merged). This is the second review pass. The first pass (not persisted to git — see Finding 1) returned **FAIL** on a Major finding; PR #1027 is the fix for that finding, submitted as this repo's convention requires (independent session/subagent, since the implementing session cannot review itself).

**Sources**:
- `specs/OPS-022-pihole-apex-rename/{proposal,tasks,verification,features}.{md,json}` at `dbbf886` (checked out on this worktree as branch `review-pr-1027`, tracking `origin/fix/homepage-pihole-domain`)
- `gh pr view/diff 1027 --repo mlorentedev/kubelab`
- Live checks from this sandbox: `dig +short pihole.kubelab.live @vita.ns.cloudflare.com`, `curl` against both pihole hostnames
- Test runs: `poetry run pytest` (targeted and full suite), `poetry run ruff check`, `poetry run mypy`, `poetry run pre-commit run markdownlint`

### Spec and task alignment

`proposal.md` frontmatter is still `status: verifying` (correct — not archived). All five acceptance criteria and both MUST-resolve risks were closed in the original implementation (`tasks.md`, all `[x]` with dates); `tasks.md` itself is untouched by PR #1027 and its `## Closing` checklist remains unticked, which is expected pre-archive, not a defect — archiving is gated on this review existing and passing, which is what this file now provides.

Grepped all four spec files for `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` — zero matches (`grep -rn` exit code 1). No stale draft tags blocking archive on that front.

Per-AC status, re-verified independently where the sandbox allowed:

| AC | Claim | This review's verification |
|----|-------|------------------------------|
| AC1 (staging e2e 200/302) | `tests/e2e/ -k pihole` — 5 passed | Not re-run live (no tailnet route from this sandbox — confirmed below). Accepted on implementer evidence in `verification.md`/`features.json`, corroborated: `dig` resolves the name correctly (see AC2) and the design intent (VPN-only reachability) matches the observed timeout. |
| AC2 (public resolution) | `dig` → `100.64.0.11` | **Re-verified live, independently**: `dig +short pihole.kubelab.live @vita.ns.cloudflare.com` → `100.64.0.11`, matches `networking.nodes.ace1.tailscale_ip` in `common.yaml:102`. |
| AC3 (prod absence / staging presence) | `tests/test_pihole_overlay_render.py` — 2 passed | **Re-run myself**: `test_staging_renders_all_three_pihole_objects` and `test_prod_renders_nothing_pihole` both PASS against the current render. |
| AC4 (target field backward-inert) | `make tf-dns-plan` → 1 add, 0 change, 0 destroy | **CANNOT CHECK** from this sandbox — `terraform init` required (no backend state / Cloudflare credentials here); this is a "cannot check, not OK" gap, not a pass. Corroborated indirectly: AC2's live `dig` confirms the record exists with the exact expected content, which is only possible if the apply described in `verification.md` actually ran. |
| AC5 (old name dark) | `curl` old name → 404 | **CANNOT CHECK live** — `curl -sk https://pihole.staging.kubelab.live/admin/` timed out from this sandbox (exit 124, no tailnet route), which is itself consistent with "VPN-only" but doesn't prove the specific 404 behavior. Accepted on implementer evidence. |

### The PR #1027 fix itself (this pass's actual subject)

The original pass-1 finding: `toolkit/scripts/sync_homepage_config.py` hardcoded `pihole.staging.{base}` for the Homepage dashboard's Pi-hole tile, inconsistent with its own `shared`-list siblings (Argo CD, Headscale, Uptime Kuma all use `{base}` with no env prefix). This was not just stale text — `custom.js`'s `checkHealth()` does `fetch(url, {mode: "no-cors", ...}).then(() => up)`, and `no-cors` resolves `.then()` for *any* reachable response, including the staging catch-all's 404 that this exact rename intentionally introduced. **Independently confirmed this mechanism is real** by reading `infra/k8s/base/services/homepage-config/custom.js:577-585` directly — the described false-positive path is genuine, not a theoretical concern.

**Independently reproduced the fix's own rigor check**, rather than trusting the PR description's claim:
1. Reverted `toolkit/scripts/sync_homepage_config.py` to its pre-fix content (`git show a043e77:...`), kept the new tests.
2. Ran `pytest tests/test_sync_homepage_config.py` → all 4 new tests **failed** with clear assertion diffs (`pihole.staging.kubelab.live` where `pihole.kubelab.live` was expected, stale DNS-map rows, stale mermaid edge label).
3. Restored the fixed source, re-ran → all 4 **passed**.

This proves the new tests are real regression tests, not vacuous assertions — the single most important thing to verify about a fix-for-a-review PR.

Also independently verified, all with command output in hand:
- `poetry run pytest` (full suite, `--no-cov`): **472 passed, 111 deselected**, matching the PR's stated count exactly.
- `poetry run ruff check` / `poetry run mypy` on the changed toolkit/test files: clean.
- `poetry run pre-commit run markdownlint` on all four changed `.md` files: passed.
- Grepped the entire repo for `pihole.staging` / `pihole\.staging`: every remaining hit is either a negative-assertion test, an intentional historical note (annotated as such), or a spec artifact describing the *retired* name — no live functional code still points at it.
- `gh pr checks 1027`: all 10 checks green (Tests, Validate, Sync check, Drift ×2, GitGuardian, etc.). No CodeRabbit/Codex review landed (both hit rate limits) — this adversarial pass is effectively the only substantive review this PR has received.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|----------|---------|------|---------|----------|---------------------------|---------------|
| Minor | REAL | process/traceability | The pass-1 review was never persisted to git. PR #1027's body, its commit message, and its own diff to `verification.md` all say "Full review at `specs/OPS-022-pihole-apex-rename/review.md`" — that file exists in neither `master` nor the PR branch (`git show master:...review.md` → "does not exist"; file absent from PR #1027's changed-files list). This violates the skill's own "persist the verdict, do not only print it" rule. The *substance* of the pass-1 finding was independently re-verified above, so this doesn't reopen the underlying bug — but the audit trail was broken until this file. | `git show master:specs/OPS-022-pihole-apex-rename/review.md` → fatal: does not exist; `gh pr view 1027 --json files` has no `review.md` entry | UNTESTED (process gap, not a code path) | spec (this file resolves it going forward) |
| Minor | THEORETICAL | generated-artifact drift | The 4 new tests pin `build_service_tables()` / `build_dns_map()` / `build_mermaid_dns()` — the *generator* — but nothing compares the **committed** `custom.js` against fresh generator output. The exact drift class that caused the pass-1 Major (generator changes, `make sync-homepage` not re-run) remains structurally possible in the reverse direction: fix the generator correctly, forget to regenerate, ship stale `custom.js` again. `docs/lessons.md`'s new entry names this shape ("A generated file that's committed instead of built-on-demand can silently outlive the source of truth") but no ticket or test closes the gap it describes. | Read of `sync_homepage_config.py` + `custom.js`; no test asserts `custom.js` content == `build_service_tables(config)` output | UNTESTED | tests (e.g. a `test_custom_js_matches_generator_output` that extracts the `KUBELAB_SERVICES_SHARED` JSON block from the committed file and diffs it against a fresh `build_service_tables()` call) |
| Minor | REAL, tracked (#964) | doc accuracy, out of scope | `build_mermaid_dns()`'s `extra_records → jetson` edge (line 461) still depicts a mechanism `CLAUDE.md`'s own gotcha says has never resolved for *any* host, including jetson (MagicDNS is what actually names it). PR #1027 touched this exact line — dropping `pihole` from the label — without correcting the still-inaccurate claim about jetson. Pre-existing, not introduced by this PR, and #964 already tracks the retirement of `extra_records` generally. | `infra/k8s/base/services/homepage-config/custom.js` line 461 / `sync_homepage_config.py` line 461; CLAUDE.md's "Headscale `extra_records` is NOT a second path..." gotcha, verified `jetson.kubelab.live → NXDOMAIN` | UNTESTED | docs/toolkit, whenever #964's retirement work happens |
| Minor | SPECULATIVE | clarity | The new DNS-map row for `pihole.kubelab.live` is grouped under the `PROD (public DNS via Cloudflare)` header. The Cloudflare-record part is accurate, but the backend it routes to is staging Traefik/RPi4, not a prod service — a future reader skimming just the header could misread this as "Pi-hole is a prod service." The inline annotation (`public record, VPN-reachable only — OPS-022`) largely mitigates this. | `toolkit/scripts/sync_homepage_config.py` line 600, `build_dns_map()` | UNTESTED | docs (optional relabel, e.g. a third header, if this ever causes real confusion) |

No Blocker or Major findings in this pass. The Major from pass 1 is fixed, independently reproduced as fixed, and covered by 4 named regression tests each proven non-vacuous.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | A | All 5 spec ACs hold (2 re-verified live/by test here, 2 CANNOT CHECK-but-corroborated, 1 accepted on evidence); the pass-1 defect is fixed and its mechanism independently confirmed via direct code read. |
| Verification       | A | Reproduced the fix's own rigor check from scratch (revert → 4 fail, restore → 4 pass), reran the full suite (472/472) and lint/type/markdownlint myself with command output, not just trusted the PR description. |
| Scope              | A | Diff touches exactly the Pi-hole tile bug and its direct documentation footprint (CLAUDE.md, dash-001 doc, lessons.md); no unrelated changes found in the full diff read. |
| Reliability        | A | Fix is a deterministic generator correction with no new error paths; regeneration (`make sync-homepage`) is idempotent and the change is trivially revertible. |
| Maintainability    | A | Clear naming, well-commented tests explaining *why* (not just what), consistent with the file's existing style; no dead code. |
| Handoff-readiness  | B | `verification.md` updated and 3 lessons captured, but the review-persistence gap (Finding 1) is itself a handoff miss this PR's own text assumed away. |

### Verdict
PASS

Per the skill's mechanical aggregation rule ("all B or above → PASS"), all six rubric dimensions clear the bar and no Blocker/Major finding exists, so the severity axis does not escalate past PASS. The four Minor findings are surfaced per the skill's guardrail against silent gaps but do not gate — none is REAL+high-severity, and the one REAL minor (unpersisted pass-1 review) is resolved going forward by this file's own existence.

### Recommended next steps (before archive)

- Merge PR #1027 to `master` — the fix is verified, tested, and does not conflict with `master` (`mergeable: MERGEABLE`).
- Commit this `review.md` (currently written to the worktree checked out at PR #1027's head, `dbbf886` — it rides neither `master` nor the open PR until someone commits/pushes it; land it as a small follow-up or fold it into the merge).
- Optional, non-blocking: file the generated-artifact-drift test (Finding 2) as a small ticket rather than leaving it only in `docs/lessons.md` prose.
- Archive (`/spec archive`) is advisable only *after* #1027 merges — until then the PR is the unmerged fix for the defect that made pass 1 FAIL, and `master` alone still carries the bug this review re-confirmed is fixed on the PR branch.
