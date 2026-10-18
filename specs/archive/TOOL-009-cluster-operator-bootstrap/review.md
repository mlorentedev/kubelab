---
spec: "TOOL-009-cluster-operator-bootstrap"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "bb811962d86d88c4f7fe22467dd57be47ca9cadc"
reviewer: "nan/glm5.3-flash"
date: "2026-10-18"
---

## Adversarial review

**Scope**: TOOL-009-cluster-operator-bootstrap, diff `438d3fc9a1385ecde960c17b6b97fde6e5657f7b...HEAD`
(resolved by the launcher; HEAD = `bb811962` on `chore/archive-tool-009`).

**Sources**:
- `specs/TOOL-009-cluster-operator-bootstrap/{proposal.md,tasks.md,verification.md,features.json}`
- Diff `438d3fc9...HEAD`. Range composition: the range spans 1045 commits because HEAD sits on
  top of current master; the TOOL-009 change is carried by **five** commits — `a956ab64`
  (implementation, #676), `d10d315e` (bootstrap-layer guard, #2164), `518a38fa` (round-1 fixes
  2–4, #2167), `40adf94e` (round-1 review recorded, #2174) and `bb811962` (AC5 amendment). I
  scoped the file-level review to those commits plus every file they touched (`Makefile`,
  `toolkit/cli/infra.py`, `toolkit/features/k8s_render.py`, `toolkit/scripts/sync_operators.py`,
  `infra/config/values/common.yaml`, `infra/k8s/cluster/**`, `tests/test_k8s_render.py`,
  `tests/test_cluster_bootstrap.py`, spec artifacts, `docs/adr/adr-047-*.md`), and I evaluated
  **all acceptance criteria at HEAD**, so the late fix `518a38fa` is judged against the early
  implementation `a956ab64` and against later master commits touching the same files
  (`cluster_bootstrap` grew a third entry, `kube-system-limitrange`, via OBS-009; the argocd
  render site is now `argocd-repoint` targeting gcp1).
- No `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tags in any spec contract file (grep clean; the only
  hits for those tokens are the recorded round-1 review and its transcript, which quote them).
- No tests deleted by any of the five commits (verified against `git show --stat`).

### Spec and task alignment

**Evidence produced in this session** (every claim re-run fresh at `bb811962`, not read from
`verification.md`):

| Check | Command | Result |
|---|---|---|
| AC1 / f1 | `toolkit config validate` + python parse of `cluster_bootstrap` | exit 0; entries `agent-sandbox`, `coredns-custom`, `kube-system-limitrange` |
| AC2 / f2 (greps) | `! grep -Rq _get_traefik_config_path toolkit/`; `grep -Eq 's/RESOLVE_\|dig .*sed' Makefile` | both clean; dead branch gone, no inline substitution shell; only render site is `argocd-repoint` (Makefile:753) |
| AC6 / f2 (tests) | `poetry run pytest tests/test_k8s_render.py tests/test_cluster_bootstrap.py -q` | **34 passed** (25 pre-#2167 + 9 new loop/fail-closed tests) |
| Full suite | `make test` | **5901 passed, 20 skipped, exit 0** (12m04s) |
| AC4 / f4 | `make sync-operators` then `git diff --exit-code infra/k8s/cluster/` | exit 0 — vendored manifest byte-identical to the SSOT-pinned `v0.5.0rc1` |
| AC3 / f5 (live) | `kubectl --kubeconfig ~/.kube/kubelab-staging-config get crd sandboxes.agents.x-k8s.io` + `get deploy -n agent-sandbox-system` | CRD serves `v1beta1` (`served: true`); `agent-sandbox-controller 1/1` (age 122d, staging) |
| **AC5 as amended** (cluster half) | fresh `cd ~/Projects/iris && KUBECONFIG=~/.kube/kubelab-staging-config go test ./internal/runtime/k8s/ -run TestK8sConformance -count=1` at current iris HEAD | **FAIL, reproduced by me**: every Start-based subtest rejects the `Sandbox` create with `metadata.labels: Invalid value: "<64 hex>": must be no more than 63 characters` |
| AC5 premise | `gh issue view 30 --repo mlorentedev/iris` | `OPEN` — "k8s runtime: Sandbox CR rejected — iris.spec-hash label value exceeds 63 chars", untouched since 2026-06-18 |
| **Mutation** (round-1 finding 2's fix is real) | restored the old `if entry.render:` guard in `render_and_apply` and ran the named test | `test_a_placeholder_with_no_render_map_is_never_applied` **went red** (both param cases); reverted; tree clean apart from the launcher's `review-request.json` |

- **AC1–AC4 and AC6 verified.** The SSOT list, the greps proving the dead `_get_traefik_config_path`
  branch and the inline `dig|sed|kubectl` shell are gone, the vendored operator, the deterministic
  `sync-operators`, and the (now 34) targeted tests all reproduce.
- **Round-1 findings 2–5 are fixed and each fix verified**: the render guard is unconditional with
  the fail-closed rationale in-code (and my mutation proved the regression test guards it); the
  apply loop is driven by `test_the_loop_applies_every_entry_in_declared_order` (order + dry-run
  propagation, over the real `common.yaml`) and `test_the_loop_stops_at_the_first_hard_failure`
  (fail-fast, with a self-guard asserting ≥2 entries); the false "Server-side dry-run" comment in
  `k8s_dry_run` is gone (now "Generate manifests and validate with dry-run (no apply)"), and the
  Makefile comments name `make argocd-repoint` (Makefile:740, 776–777).
- **AC5, amended 2026-10-18 (`bb811962`, owner ruling kubelab#2443), is accepted as amended.**
  Round 1 offered exactly this path (its recommendation 1b). I re-reproduced the failing conformance
  run myself at current iris HEAD, confirmed iris#30 is still open, and confirmed the cluster half
  live: the CRD serves `v1beta1` and a `Sandbox` create reaches the API server's validation for that
  kind — which only happens because this spec's CRD is installed. `tasks.md` T9 correctly stays `[ ]`
  and `features.json` f6 stays `state: "blocked"` — the artifacts do not overclaim.
- All six `features.json` verification commands are non-vacuous (round 1's precursor finding):
  f1–f5 re-run exit 0 in this session; f6 is the command I re-ran and it fails for exactly the
  documented reason.
- Security walkthrough of the spec's commits: manifests reach `kubectl` via stdin with argv lists,
  `dig` is invoked with argv, no shell interpolation of rendered content, no secrets in the diff,
  `--server-side --force-conflicts --field-manager kubelab-toolkit` is a named, traceable manager,
  and `render-apply`'s `--render KEY=VALUE` args never reach a shell. No injection/secrets/auth
  finding.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | spec-wording precision | The AC5 amendment (proposal.md) and `features.json` f6 say the API server refused iris's 64-char label *“by that CRD's schema”*. The 63-character label-value cap is the API server's **built-in ObjectMeta validation**, not the CRD's OpenAPI schema. The cluster-side conclusion still holds — a `Sandbox` create reaches that validation only because the CRD is served (otherwise the request 404s on the unknown kind) — but the attribution is imprecise | proposal.md AC5 amendment; f6 evidence line; reproduced run in this session shows the error source is `metadata.labels` validation | n/a (text) | verification.md disposition row (the contract set is closed under a passing verdict — do not edit it now) |
| Question | — | process / contract | `tasks.md` T9 remains `[ ]` “blocked on mlorentedev/iris#30” while AC5 is amended to be owned by iris; `tasks.md` was not amended in step with `proposal.md`. Whether the archive gate accepts an unticked task alongside an amended criterion — or T9 needs rewording in a later round — is the owner's call. Relatedly, tracking issue mlorentedev/knowledge#118 is **already CLOSED** (title “TOOL-011…”), while `verification.md`'s archive checklist still lists “issue #118 closed with the PR link” as an open step | `tasks.md` T9; `gh issue view 118 --repo mlorentedev/knowledge` → CLOSED; `verification.md` archive checklist | n/a | contract set only if T9 is reworded (→ re-review); otherwise disposition in `verification.md` before archiving |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | Every acceptance criterion verified in-session as amended (AC5's cluster half proven live, consumer half honestly externalized to iris#30); no defects observed, but one criterion is met only via a same-day amendment and the tasks file lagged it |
| Verification       | A | Every feature carries a reproducible command; I re-ran f1–f6 equivalents fresh, including the live cluster, the failing iris run and a mutation that turned the new regression test red |
| Scope              | B | The spec's five commits match the proposal with no creep, but the launcher range mixes in ~1040 unrelated master commits, so scope had to be established commit-by-commit (same caveat as round 1) |
| Reliability        | A | Fail-closed render guard now unconditional and mutation-verified; loop is fail-fast and order-stable with named tests; missing-manifest, unresolvable-host, dry-run-failure and optional-skip paths all covered |
| Maintainability    | A | Small functions, docstrings explain *why* (e.g. the client-side dry-run rationale), test names read as sentences, complexity well under limits |
| Handoff-readiness  | A | ADR-047 accepted, `verification.md` filled with fresh evidence and per-finding dispositions of round 1, lesson-547 recorded, downstream blockage ticketed (iris#30) — the T9/AC5 wording gap is tracked above |

### Verdict

**PASS WITH GAPS.**

Round 1's FAIL hinged on one **REAL Major** (AC5 red). That is resolved the way round 1 itself
sanctioned: an owner contract amendment (`bb811962`) re-scoping AC5 to the cluster side, with the
conformance pass owned by iris#30 — and I independently re-verified both halves (cluster live and
serving; conformance still failing on iris's 64-char label, exactly as recorded). Round 1's two
THEORETICAL Majors are fixed with named regression tests, one of which I mutation-verified red.
No Blockers, no open Majors; the two remaining items are a Minor wording imprecision and a process
Question, both tracked above with dispositions.

### Recommended next steps

Not "before archive" — these are written for the implementer to disposition in `verification.md`
(applied / ticketed / declined with a reason) or to carry into a follow-up; none gates the verdict:

1. **Wording precision (verification.md row):** record that the 63-char label cap is the API
   server's built-in ObjectMeta validation, and that the CRD's role is routing the `Sandbox` create
   into validation — the run proves the substrate, not the CRD's own schema.
2. **T9 / archive-checklist reconciliation (owner decision):** either disposition T9 in
   `verification.md` as externally owned per the amended AC5 (contract set untouched), or accept
   that a later contract round rewords T9. Note knowledge#118 is already closed — align the archive
   checklist with reality (close-out comment naming iris#30 as the open remainder) rather than
   "closing" it at archive time.
3. **Carry-over from round 1, still open by design:** re-pin `agent-sandbox` to a stable v1beta1
   semver when upstream ships one, and re-run `TestK8sConformance` in iris once iris#30 lands —
   that closing run belongs to iris, not to this spec.

**Is `dotf spec archive` advisable now?** Yes, subject to the archive gate's own checks: the
verdict is passing on a fresh review of the current contract digests, and the residual gaps are
tracked above rather than blocking. If the gate refuses on the unticked T9, that refusal is the
mechanism working, not a defect in this review — resolve it per recommendation 2.
