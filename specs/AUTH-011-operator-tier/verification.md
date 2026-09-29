---
tags: [spec, verification]
created: "2026-09-26"
---

# Verification - AUTH-011

## Evidence

- [x] AC1 (Argo CD's own evaluator on the shipped policy) -> #1870 `275e5bc2`, test `tests/test_access_review.py -k argo_cd_rbac`. It runs `argocd admin settings rbac can` from the pinned image over every allow/deny pair. 1 passed, 2026-09-29.
- [x] AC2 (Grafana role path: admins Admin, users Editor, other Viewer, empty groups defer) -> #1870 `275e5bc2`, test `-k role_path`. 9 passed, 2026-09-29.
- [x] AC3 (three declared tiers, mapped per app) -> #1870 `275e5bc2`, test `-k tier`. 9 passed, 2026-09-29.
- [x] AC4 (ADR-062 D2 amended in place) -> #1870 `275e5bc2`, `docs/adr/adr-062-platform-identity-model.md`. `grep -c role:operator` = 2.
- [x] AC5 (prod behaviour) -> deployed 2026-09-26 with `make deploy-argocd` (rc=0, hub Helm revision 3). Evidence:
  - `operator` in the browser synced an application.
  - Delete, update and repository settings were refused. The refusal was evaluated offline with `argocd admin settings rbac can` (v3.4.1) against the live `argocd-rbac-cm`, not by confirming a destructive modal (lesson-473).
  - Grafana Profile showed Editor, and `/admin/users` was refused. Operator browser check, 2026-09-29.
  - `make auth-review ENV=prod` on 2026-09-29: rc=0, every account OK (`operator` Gitea user, Grafana Editor; `manu` admin/Admin unchanged); Argo CD `BOUNDED` by the 1h token lifespan (#1872 `fe71829c`, lesson-471).

## Test status

- Spec tests: the three `pytest -k` selections above, all green on master `1d26f53e`.
- Staging smoke, 2026-09-29: `make auth-review ENV=staging` rc=0 (`operator` Grafana Editor), after the correction below. Operator browser check: Profile Editor, `/admin/users` refused.
- No regressions: #1870 and #1872 merged with CI green.

## Decisions made during implementation

- Argo CD's demotion bound is documented as the real 1h access-token lifespan, not shortened (#1872, lesson-471).
- Staging correction, 2026-09-29. Authelia in staging still served `operator` the pre-AUTH-011 groups `admins,users`, because the `authelia-users` Secret is delivered only by `make apply-secrets` and had not been re-applied. `auth-review APPLY=1` reported `BOUNDED`, but a revoke cannot fix a stale IdP. Fixed with `make apply-secrets ENV=staging` (`authelia-users configured`, Authelia restarted) and a fresh login. The detection gap is #1911 (AUTH-014). The missing automatic delivery is ADR-038's deferred decision, with this incident added as evidence to #1613.

- Review follow-ups (nan/deepseek-v4-flash, PASS at `6790a7fe`):
  - M3: `proposal.md` "Risks / open questions" is historical. Both deploy-time risks it names were resolved by the deploy and are documented in `docs/runbooks/identity-tier-change.md`. The proposal is left unedited because the verdict freezes it.
  - Q1: AC5's reproducible half is the offline matrix. `test_argo_cd_rbac_lets_users_operate_and_never_administer` runs Argo CD's own evaluator over the shipped policy in CI. The live half is the operator's browser checks and `make auth-review ENV=prod`. #1876 (AUTH-012) moves the evaluator into `auth-review`, so the live half stops being testimony.
  - M1: the lifespan guard now also asserts the pinned Authelia minor (4.39). The 1h is that version's default, so an upgrade fails the test until the default is re-measured (proven red with the pin set to 4.40.0).
  - M2: `argocd_group_bound()`'s docstring now says what it reads live (the UserInfo branch) and what is declared (the bound).

## Promotion candidates

- [x] Lesson: yes: docs/lessons/identity-secrets/lesson-473-the-argo-cd-ui-asks-for-confirmation-before-the-server-authorizes.md
- [x] Runbook: yes: docs/runbooks/identity-tier-change.md
- [x] ADR: no: ADR-062 D2 was amended in place by #1870, not a new decision
- [x] Pattern: no: specific to this repo's identity model

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved to `specs/archive/`
- [ ] #1862 closed by the archive PR
- [x] Promotions executed (lesson-473, runbook)
