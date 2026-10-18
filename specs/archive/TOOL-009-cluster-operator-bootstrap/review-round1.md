---
spec: "TOOL-009-cluster-operator-bootstrap"
verdict: "FAIL"
reviewed_sha: "7d45017dcd0ff9356aaeddc017ef12bf775873e2"
reviewer: "nan/mimo-v2.6-flash"
date: "2026-10-10"
---

## Adversarial review

**Scope**: TOOL-009-cluster-operator-bootstrap, diff `438d3fc9a1385ecde960c17b6b97fde6e5657f7b...HEAD`
(resolved by the launcher; HEAD = `7d45017d` on `chore/archive-tool-062`).

**Sources**:
- `specs/TOOL-009-cluster-operator-bootstrap/{proposal.md,tasks.md,verification.md,features.json}`
- Diff `438d3fc9...HEAD`. Note on range composition: the range spans 856 commits because HEAD
  sits on top of current master; only **two** commits carry TOOL-009's change —
  `a956ab64` (implementation, #676) and `7d45017d` (late verification/tasks/features update).
  I scoped the file-level review to those two commits plus every file they touched (Makefile,
  `toolkit/cli/infra.py`, `toolkit/cli/sync.py`, `toolkit/features/k8s_render.py`,
  `toolkit/scripts/sync_operators.py`, `infra/config/values/common.yaml`, `infra/k8s/**`,
  tests, spec docs, `docs/adr/adr-047-*.md`), and I evaluated **all acceptance criteria at
  HEAD** — so late fixes are judged against the early implementation and against ~854 later
  master commits that touched the same files (e.g. `cluster_bootstrap` grew a third entry via
  OBS-009; the argocd render site moved from aws1 in `_deploy-argocd-helm` to gcp1 in
  `argocd-repoint`).
- No `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tags in any spec contract file (grep clean).
- `reviewed_sha` is `7d45017d`, the sha the launcher resolved and this review examined. HEAD
  advanced once mid-run to `b3d4c479` (a parallel session's `wip: TOOL-062 review dispositions`,
  touching only `specs/TOOL-062-gitea-actions-secrets/verification.md`) — no TOOL-009 contract
  or code file differs between the two commits, so the reviewed state is unchanged.

### Spec and task alignment

**Evidence produced in this session** (every claim below re-run fresh, not read from `verification.md`):

| Check | Command | Result |
|---|---|---|
| AC1 / f1 | `toolkit config validate` + python set check on `cluster_bootstrap` | exit 0; entries `agent-sandbox`, `coredns-custom`, `kube-system-limitrange` |
| AC2 / f2 (greps) | `! grep -Rq _get_traefik_config_path toolkit/` ; `! grep -Eq 's/RESOLVE_\|RESOLVE_[A-Z0-9_]+/\\$' Makefile` | both clean; only `render-apply` site left is `argocd-repoint` (Makefile:697) |
| AC6 / f2 (tests) | `pytest tests/test_k8s_render.py tests/test_cluster_bootstrap.py -q` | **25 passed** |
| Full suite | `make test` | **4415 passed, 16 skipped, 2 xfailed, exit 0** (10m48s) |
| AC4 / f4 | `make sync-operators` then `git diff --exit-code infra/k8s/cluster/` | exit 0, vendored manifest byte-identical, deterministic |
| AC3 / f5 (live) | `kubectl --kubeconfig ~/.kube/kubelab-staging-config get crd sandboxes.agents.x-k8s.io` + rollout status | serves `v1beta1`; `agent-sandbox-controller 1/1`, age 114d (staging) |
| **AC5 / f6** | `cd ~/Projects/iris && KUBECONFIG=~/.kube/kubelab-staging-config go test ./internal/runtime/k8s/ -run TestK8sConformance -count=1` | **FAIL** — 7 subtests, each `Sandbox ... metadata.labels: Invalid value: "<64 hex>": must be no more than 63 characters` (iris at `748d2f1`, the sha `verification.md` cites) |

- **AC1–AC4, AC6 verified.** The SSOT list, the greps proving the dead traefik branch and the
  inline `dig|sed|kubectl` shell are gone, the vendored operator, the deterministic
  `sync-operators`, and the 25 targeted tests all reproduce.
- **AC5 is red.** I reproduced it myself against the live staging cluster — this is not the
  implementer's claim, it is my own failing run. `tasks.md` T9 and `features.json` f6
  (`state: "blocked"`) honestly record it, and `verification.md` leaves AC5 unticked; the
  spec's own artifacts say "not done" on this criterion.
- **T1–T8 `[x]` are backed by diff evidence**; T9 is correctly left `[ ]`.
- **AC6 is only partly backed**: the render primitive is covered (22 named tests in
  `tests/test_k8s_render.py`), the SSOT loader is covered (3 tests in
  `tests/test_cluster_bootstrap.py`), but the *apply loop* `_apply_cluster_bootstrap` — which
  T3 says has "a unit test [that] asserts the loop applies every declared entry" — has **no**
  test: the only references in `tests/` are `mocker.patch.object(infra, "_apply_cluster_bootstrap", ...)`
  in `tests/test_infra_k8s_deploy_rollout.py:34` and `tests/test_deploy_impersonation.py:37`,
  which bypass it entirely.
- **Test deletions:** none — the spec's two commits delete no tests.
- **Security walkthrough of the diff:** no shell interpolation (manifest goes to `kubectl` via
  stdin with argv lists; `dig` invoked with argv), no secrets, `--server-side --force-conflicts
  --field-manager kubelab-toolkit` is the documented toolkit convention with a named manager.
  No finding in injection/secrets/auth.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | REAL | acceptance | **AC5 unmet**: iris `TestK8sConformance` fails against staging — the proposal's fifth acceptance criterion is red today | reproduced in this session at iris `748d2f1` (7 subtests fail on the 64-char `iris.spec-hash` label); matches `verification.md`'s own 2026-10-10 run; ticket `mlorentedev/iris#30` open since 2026-06-18 | `TestK8sConformance` (iris repo) — currently FAILING | external repo (`iris#30`) → then re-review; or owner amends AC5 in `proposal.md` (contract set → new round) |
| Major | THEORETICAL | resilience / fail-closed | `render_and_apply` only calls `render_text` `if entry.render:` — an entry whose manifest contains a `RESOLVE_*` placeholder but declares **no** `render:` map is applied **verbatim**, defeating the module's own documented fail-closed invariant ("a half-substituted manifest is never returned … typo / config drift") | reproduced in-session: `BootstrapEntry(render={})` + manifest containing `RESOLVE_RPI4_TAILSCALE_IP` → `render_and_apply` returned `True` and handed `kubectl` the literal string. No live entry triggers it today (all 3 `cluster_bootstrap` entries are consistent), no incident observed — hence THEORETICAL | UNTESTED (`test_no_render_map_applies_verbatim` uses placeholder-free text; no test covers placeholder-with-empty-map) | code + tests: call `render_text` unconditionally (empty map then fails closed on any placeholder), add a named regression test |
| Major | THEORETICAL | tests / AC6 | The `cluster_bootstrap` apply loop `_apply_cluster_bootstrap` is never executed by any test, though T3 and AC6 both claim loop coverage; fail-fast and declared-order behavior rest on inspection only | `grep -rn "_apply_cluster_bootstrap" tests/` → only the two mock-outs quoted above; no `k8s bootstrap` CLI test | UNTESTED | tests: a test that drives the loop (every entry applied in order; first hard failure aborts) |
| Minor | REAL | spec-vs-code drift | proposal §What(2) and tasks T2 specify `--dry-run=server` before apply; the primitive validates with `--dry-run=client` (rationale documented in `_kubectl_apply`: server dry-run can't create a namespace it validates against). Worse, `k8s_dry_run`'s comment claims "Server-side dry-run validates each rendered manifest against the live API" — false | `toolkit/cli/infra.py` (`k8s_dry_run` comment) vs `toolkit/features/k8s_render.py::_kubectl_apply` | n/a (comment/text) | code comment now; the proposal/tasks wording is contract set — disposition in `verification.md` or a follow-up ticket, not an edit alongside this verdict |
| Minor | REAL | doc drift | `Makefile:716-721` comment says the EndpointSlice render "moved to `toolkit infra k8s render-apply` inside `_deploy-argocd-helm`"; at HEAD the only `render-apply` call is `argocd-repoint` (Makefile:697) and `_deploy-argocd-helm` contains none — later hub migration (aws1→gcp1) invalidated the comment | `grep -n "render-apply" Makefile` → 3 hits, none inside `_deploy-argocd-helm` | n/a (comment) | code (comment) |
| Question | — | process | `features.json` f6 carries `state: "blocked"` and AC5 is unticked: does the owner archive with AC5 tracked on `iris#30`, or hold? This is the decision the verdict below encodes | `features.json`, `tasks.md` T9 | — | owner decision (contract set only if AC5 is amended) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | C | 5 of 6 acceptance criteria verified in-session; AC5 (iris conformance) demonstrably fails — "criteria partially met" |
| Verification       | A | Every feature ships a reproducible command; I re-ran f1–f5 myself (all exit 0 / live cluster verified) and the one red item is honestly recorded as red |
| Scope              | B | The spec's own two commits match the proposal with no creep (9 impl/spec files + ADR + Makefile/common), but the launcher-specified range mixes in ~854 unrelated master commits, so scope had to be established file-by-file |
| Reliability        | B | Error paths of the primitive are well handled (missing manifest, unmapped placeholder, unresolvable host, dry-run/apply failure all tested), but the empty-render-map fail-open and an untested apply loop remain |
| Maintainability    | A | Small functions, precise docstrings explaining *why*, table-clear test names, 100% coverage claimed for `k8s_render` and consistent with the run |
| Handoff-readiness  | A | ADR-047 written and accepted, `verification.md` filled with fresh re-run evidence, doc drift fixed, downstream blockage ticketed (`iris#30`) |

### Verdict

**FAIL.**

One **REAL Major** (AC5 — iris `TestK8sConformance` fails; reproduced by me in this session
against staging) forces FAIL under `severity × reality`, and Correctness grades C. The rubric
alone would sit at PASS-WITH-GAPS; the severity axis is the more severe of the two and wins.
The two THEORETICAL Majors (fail-open render guard, untested apply loop) are tracked alongside
it and need named regression tests before a plain PASS is available.

### Recommended next steps

On FAIL the contract set is the point — a `proposal.md` edit and a re-review follow, and this
verdict must not be patched around by editing contract files alongside it:

1. **Decide AC5 (contract set — triggers a new review round either way):**
   a. preferred — land the `iris#30` fix (truncate `iris.spec-hash` to ≤63 chars at write and
   drift-compare), re-run the conformance command from the evidence table, attach the passing
   output to `verification.md`, then re-run `dotf spec review TOOL-009-cluster-operator-bootstrap`; or
   b. owner amends AC5 in `proposal.md` to record "substrate validated by API-server rejection
   of the consumer's label; conformance tracked on `iris#30`" — a contract edit, so a fresh
   review is required before archive.
2. **Fail-closed render guard (code + tests):** call `render_text` unconditionally in
   `render_and_apply` and add a test asserting a manifest containing `RESOLVE_*` with no
   declared map fails (skips for `optional`, errors otherwise). Outside the contract set —
   can land with the re-review round.
3. **Apply-loop test (tests):** make T3's stated verification real — one test driving
   `_apply_cluster_bootstrap` over the live `common.yaml`, asserting order and fail-fast.
   Outside the contract set.
4. **Comment/text drift (code):** fix the false "Server-side dry-run" comment in `k8s_dry_run`
   and the stale `_deploy-argocd-helm` comment in the Makefile; disposition the
   `--dry-run=server` wording in `verification.md` (contract wording untouched).
5. Not before archive: these recommendations are written for disposition
   (`verification.md`: applied / ticketed / declined with a reason); items 2–4 do not gate the
   verdict — item 1 does.

**Is `dotf spec archive` advisable now?** No — the verdict is FAIL; the archive gate would (and
should) refuse. Minimum to flip to PASS: AC5 resolved per 1a or 1b plus a re-review; items 2–3
should land as named regression tests in that same round so the follow-up PASS is not itself
UNTESTED.
