---
spec: "AUTH-011-operator-tier"
verdict: "PASS"
reviewed_sha: "6790a7fe5a573ff627663f9a97f341673947e82f"
reviewer: "nan/deepseek-v4-flash"
date: "2026-09-28"
---

## Adversarial review

**Scope**: AUTH-011-operator-tier (issue #1862), reviewed at `6790a7fe` against the launcher-resolved base `edb421d0`.

**Sources**: `specs/AUTH-011-operator-tier/{proposal,tasks,verification,features.json}`; `git diff edb421d058753d196a09cea7e73be5ea21262a03...HEAD`; `git log edb421d0..HEAD`; PR #1870 (`275e5bc2`), #1872 (`fe71829c`) and the four spec/doc commits (`94949b4c`, `83f3f23c`, `6a7a45f6`, `6790a7fe`).

**Scope caveat, stated rather than silently absorbed.** The launcher's base makes the diff span 29 commits / 113 files, because it is the parent of the AUTH-011 merge while HEAD is master plus everything landed afterwards. Most of that is unrelated merged work with its own PRs and its own reviews (#1888, #1892, #1899, #1900, #1904, #1905, #1906, OPS-023, the APP-CONFIG-015 archive, renovate bumps). I reviewed the AUTH-011 subset in depth — that is what this verdict is about — and ran the AUTH-011 guards plus the linter against the whole tree. I did **not** re-review the other 25 commits; each of those went through its own gate.

### Spec and task alignment

Acceptance criteria, each checked against the implementation rather than against `verification.md`:

| AC | What the spec requires | What the diff does | Reproduced here |
|---|---|---|---|
| AC1 | `users` get/sync/action on applications; denied create/update/delete of applications and update of repositories/clusters/projects; `admins` all; `e2e` read-only | `role:operator` = `role:readonly` + `applications, sync` + `applications, action/*`; `g, users, role:operator`; `g, admins, role:admin`; `policy.default: role:readonly` | **yes** — 1 passed |
| AC2 | Grafana path: `admins`→Admin, `users`→Editor, other non-empty→Viewer, absent/empty defers to UserInfo | `contains(groups,'admins') && 'Admin' \|\| contains(groups,'users') && 'Editor' \|\| 'Viewer'`, inside the existing `length(groups \|\| \`[]\`) > \`0\`` guard, in **both** copies (K8s env + dev Compose) | **yes** — 9 passed over every path found by `_role_paths()` |
| AC3 | `declared_tiers` three-valued; Gitea admin/user/user, Grafana Admin/Editor/Viewer | `ADMIN/OPERATOR/VIEWER` + `_tier()` (admins first, then users, else viewer) + `tier_map` per app; `review()` reads `tiers.tier_map[...]` | **yes** — 9 passed |
| AC4 | ADR-062 D2 amended in place, dated, with the measured need | New "Amendment 2026-09-26: `users` operate" subsection + a pointer line next to the D4 amendment; trigger clause explicitly declared fired | **yes** — `grep -c 'role:operator'` = 2 |
| AC5 | Prod: Sync allowed, delete/repository refused, Grafana Editor, `manu` unchanged, `make auth-review ENV=prod` no drift | Recorded in `verification.md` (deploy rc=0, hub revision 3, browser checks, review rc=0 with Argo CD reported `bounded`) | **no** — not reproducible from this environment (see Q1) |

Tasks: every box is `[x]` and every one has diff evidence — I checked each implementation task against a file in the diff (`app_version` in `common.yaml`, the RBAC test, `policy.csv`, the role path, `declared_tiers`, the ADR). No `[x]` without code. No `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tag in any spec artifact (the only grep hits were inside the launcher's own `review-transcript.jsonl`, which is not a spec file).

The change is internally consistent at every seam I could probe: `declared_tiers` was renamed everywhere (`tests/e2e/test_grafana_sso.py` updated; no `declared_admins` caller left), the two Grafana role-path copies both moved, the `e2e` fixture (`testuser`, group `e2e`) lands on Viewer in Grafana and on `policy.default: role:readonly` in Argo CD, and `manu` (groups `admins,users`) is tested `admins`-first so it keeps Admin even now that `users` grants Editor.

### Evidence I produced (not merely read)

- `poetry run pytest -q tests/test_access_review.py -k argo_cd_rbac` → **1 passed, 38 deselected**. The test runs Argo CD's own evaluator (`argocd admin settings rbac can`) from `quay.io/argoproj/argocd:v3.4.1` over the shipped `policy.csv`, 16 allow/deny pairs, and fails (not skips) in CI when docker is missing.
- `-k role_path` → **9 passed**; `-k tier` → **9 passed**.
- **Mutation A (red-green for AC1's deny half):** I appended `p, role:operator, applications, *, */*, allow` to `policy.csv`; the guard failed, naming exactly `users create/update/delete applications` as newly allowed. Reverted; tree clean. This is the claim the PR body makes ("widening to `applications, *` turns create/update/delete red") and it holds.
- **Mutation B (red-green for AC2):** I deleted the `users`→`Editor` branch from `grafana.env`; `test_the_role_path_maps_each_tier[…Editor…]` failed. Reverted; tree clean.
- `ruff check` + `ruff format --check` on the touched Python files → clean.
- **Not reached:** a full `poetry run pytest -q --no-cov` run, which stalled at `tests/test_monitoring_integration.py` (59% of collection) and was not completed inside the time window. So the "2876 passed" in the PR body is **UNVERIFIED by this review**; what I verified is the three AUTH-011 selections, the linter, and that no test was deleted (the diff only adds/changes tests for this spec).

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Question | SPECULATIVE | verification | **Q1 — AC5's prod half cannot be reproduced from the review environment.** No hub kubeconfig and no prod break-glass path here, so the strongest independent reproduction of AC5's denial half remains offline: the same 16-case matrix, run in CI, over the policy that the deploy ships. `verification.md` records rc=0 and specific browser observations, which is real evidence but testimony from the implementing session. | `make auth-review ENV=prod` could not be run (`Makefile:657` restricts `ENV` to `staging|prod` and the run needs the private URL path); the offline equivalent is the named test below | `test_argo_cd_rbac_lets_users_operate_and_never_administer` covers the offline half; the live half is `UNTESTED` in this review | `verification.md` (outside the contract set) — record the offline matrix as AC5's reproducible half, and let the live checks stay the operator's |
| Minor | REAL | tests | **M1 — one self-referential assertion in the lifespan guard.** `test_the_argo_cd_bound_is_the_token_lifespan_authelia_actually_issues` ends with `assert ARGOCD_TOKEN_LIFESPAN == "1h"`, which restates the constant's own definition and can only pass. The three config guards above it (no `lifespans` in base or prod overlay, no `lifespan` on the argocd client) are the load-bearing part. | Read of `tests/test_access_review.py`; the final assertion is a tautology regardless of what the constant is | `test_the_argo_cd_bound_is_the_token_lifespan_authelia_actually_issues` | tests (drop or invert the tautology; derive the constant from the declared lifespan if the guard is to mean something) |
| Minor | THEORETICAL | maintainability | **M2 — `argocd_group_bound()` overstates what it reads.** Its docstring says the bound is "read from the LIVE hub", but only `enableUserInfoGroups` comes from the live `argocd-cm`; the 1h is a module constant validated against repo configs. Under IaC (the reason the value holds) this is fine, but an out-of-band `lifespans` on the deployed Authelia would make the tool report a bound nobody checked. | Code read, `toolkit/features/access_review.py` (`argocd_group_bound`, `ARGOCD_TOKEN_LIFESPAN`) | `test_the_argo_cd_bound_is_the_token_lifespan_authelia_actually_issues` (covers the repo configs, not derivability) | code (docstring/wording) |
| Minor | REAL | spec hygiene | **M3 — `proposal.md` "Risks / open questions" still reads as open** while the Setup task `[x] No open questions left in proposal.md` is ticked. Two of the three items (Argo CD reaches the hub only via `make deploy-argocd`; Grafana writes the role at login) were resolved by the deploy and are now written up in `runbook:identity-tier-change.md`, which the section does not point at. | `proposal.md` §Risks vs `tasks.md` Setup; runbook exists and covers both | `UNTESTED` (documentation) | spec — **do not edit while this verdict stands**; carry it as a note in `verification.md` or a follow-up ticket (see "Recommended next steps") |

No Blocker and no Major was found. Specifically, the two failure modes I tried hardest to construct did not hold:

- *"`users` can reach administration through the wildcard `action/*`"* — the evaluator, run by Argo CD itself, denies `exec`, `update` on repositories/clusters/projects/accounts and create/update/delete of applications under the shipped policy, and the mutation test shows the matrix is sensitive to exactly that widening.
- *"The Grafana change demotes the superadmin or misses a copy"* — `admins` is tested first, `manu` is in both groups, and `_role_paths()` parametrizes over every role path in the repo, so a stale second copy would fail rather than lie.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | AC1–AC4 reproduced by execution with mutation-sensitive negative paths; AC5's prod half rests on recorded evidence and is not reproducible from here. |
| Verification       | B | Named tests, reproducible commands and outputs for four criteria; the prod half needs context (hub kubeconfig, break-glass) the review environment does not have. |
| Scope              | A | The AUTH-011 commits touch exactly what the proposal describes plus its own docs; no creep. The unrelated commits in the launcher's diff range are other PRs, not this spec's. |
| Reliability        | A | Deny-by-default policy with the allow half explicit; the review reports `bounded`/`failed`/`refused` distinctly and `bounded` is deliberately non-blocking; reconciliation is read-back verified; the change is reversible by editing one policy and re-deploying. |
| Maintainability    | B | Clear naming, comments explain WHY, ruff clean; docked for M1's tautology and M2's overstated docstring (`reconcile` at 51 lines exceeds the 40-line rule, but it did so at the base commit too — pre-existing, not introduced here). |
| Handoff-readiness  | A | ADR amended in place, runbook added and cross-linked from `docs/README.md`, lesson-473 and corrected lesson-471 captured, and the next steps (#1876 AUTH-012, #1911 AUTH-014) are named in the artifacts. |

### Verdict

PASS

No Blocker, no REAL Major, no rubric D or C. The three minors are tracked above and none of them is worth blocking an archive over; per the aggregation rule, minors alone with every dimension at B or above do not move this below PASS.

Completion notes required by the skill: (a) verdict is **PASS**; (b) `dotf spec archive` is **advisable** in the current state — the review is fresh against the contract digests the launcher recorded, and no contract file was edited by me (I touched only `review.md`; the working tree carries nothing but the launcher's `review-request.json`); (c) not applicable — the verdict is not FAIL. If the archive gate insists on the exact string `PASS`, this file already carries it.

### Recommended next steps

All three are **non-contract** by construction — `proposal.md`, `tasks.md` and `features.json` are frozen by this verdict, and an edit to any of them would invalidate it.

- **M1 (tests)** — replace `assert ARGOCD_TOKEN_LIFESPAN == "1h"` with a check that means something: assert the constant against the value the guard derives from the declared Authelia config, or drop the line and let the three config guards carry the claim.
- **M2 (code, wording)** — narrow the `argocd_group_bound()` docstring to what it does: the branch is read live, the bound is a declared constant enforced by the test.
- **M3 (verification.md, outside the contract set)** — add one line under "Decisions made during implementation" noting that `proposal.md`'s "Risks / open questions" is historical and now covered by `runbook:identity-tier-change.md`; the archive will carry it as written. If that is unsatisfying, file a follow-up ticket rather than editing the proposal.
- **Open prod half of AC5 (Q1)** — keep the offline matrix as the reproducible half; the operator's browser and `make auth-review ENV=prod` run stay the live half, and #1876 (AUTH-012) is the tracked path to folding the Argo CD evaluator into `auth-review` so it stops being testimony.
