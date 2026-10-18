---
spec: "AUTH-004-identity-and-machine-access"
verdict: "PASS WITH GAPS"
reviewed_sha: "7422ce264766053fa2ff4179633b44f6c3b8b8cf"
reviewer: "agy/gemini-3.8-flash-high"
date: "2026-10-18"
---

## Adversarial review

**Scope**: `AUTH-004-identity-and-machine-access` (`git diff 5f3069dae1de80a034fa4d270c05b10065ae4bf9...HEAD`)
**Sources**:
- `specs/AUTH-004-identity-and-machine-access/proposal.md`
- `specs/AUTH-004-identity-and-machine-access/tasks.md`
- `specs/AUTH-004-identity-and-machine-access/verification.md`
- Codebase diff and git commit history across the feature delivery (`#1068`, `#1074`, `#1087`, `#1330`, `#1336`, `#1341`, `#1352`, `#1390`, `#1437`, `#1451`, `#1458`, `#1510`, `#1514`, `#1539`, `#1795`, `#1797`, `#1801`, `#1809`, `#1812`, `#1818`, `#1825`, `#1826`, `#1837`, `#1842`, `#2443`)

### Spec and task alignment

The implementation establishes the platform identity plane and machine access architecture specified in [ADR-062](../../docs/adr/adr-062-platform-identity-model.md):
1. **SSOT Admin Identity Decoupling (AC1, AC6)**: The historical security hazard where Gitea, MinIO, and Grafana derived admin identities from Traefik's `BASIC_AUTH_USER` (which caused a live admin rename during credential rotation in #1352) has been eliminated. Identity resolves from `apps.auth.identities` (`superadmin`, `operator`, `machine`) in `common.yaml`. In `toolkit/features/k8s_secrets.py`, `_resolve_grafana_admin` injects the declared break-glass account via dynamic literals, and the static mapping is gone. MinIO was retired (OPS-023), and Gitea resolves from `apps.auth.identities.superadmin` in Ansible. Red-green mutation tests verified this guard.
2. **SSO Onboarding and Closed Self-Registration (AC3, AC4)**: Gitea auto-registration from Authelia OIDC was deployed in prod (#1809). New accounts are provisioned upon first SSO login with no manual step in Gitea, while anonymous registration remains strictly forbidden (`POST /user/sign_up` returns HTTP 403). Required group claim mappings (`admins` -> admin, `users` -> user) ensure accounts outside approved groups (e.g. `testuser` in `e2e`) receive "Sign-In Prohibited".
3. **Machine Identity Provisioning (AC5)**: Provisioning of dedicated agent identity (`hefesto`) from Ansible is in place, minting scoped tokens stored directly in SOPS (`apps.services.core.gitea.bot_token`) via `no_log: true` subprocess calls. Permissive scopes (`write:repository,write:user`) and restrictive refusals (`GET /admin/users` 403) were demonstrated. Because Gitea 1.25.5's `prohibit_login: true` flag also disables API token authentication, interactive login blocking is achieved via a randomized unheld password, omission from Authelia users, and non-admin scopes. The recorded Authelia refusal probe and static exclusion guard are tracked under #2504.
4. **Break-Glass Access & Rotation (AC7)**: Private break-glass ingress paths bypassing Traefik and Authelia are derived for all dependents (`toolkit auth break-glass`, `make break-glass`). For Grafana, row ID 1 is reconciled to local account `breakglass` to prevent SSO adoption and password lockouts. Automated rotation (`toolkit secrets rotate --group break-glass`) was executed in prod (#1801). The live drill with Authelia scaled to 0 is tracked under #2503.
5. **Two-Tier Model Enforcement (AC2)**: `operator` was removed from the `admins` group in Authelia (#1853), and `make auth-review ENV=prod` confirms live roles as `users` / `user` / `Editor` vs `manu`'s admin. Live demonstration of an administrative refusal from an active operator session is tracked under #2505.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL | authz | AC2 operator refusal unverified in live interactive session. Privileges are read as non-admin (`Editor`/`user`), but a live administrative attempt returning 403 was not recorded. | `proposal.md:61`, `tasks.md:61`, `verification.md:18-20`. Carried by #2505. | UNTESTED (live session refusal); static/live privilege verified by `toolkit auth review` | Non-contract (tracked in #2505) |
| Major | THEORETICAL | machine-auth | AC5 bot account refusal at Authelia is unverified by live probe, and static guard preventing bot inclusion in Authelia users is absent. Gitea 1.25.5 `prohibit_login` disables tokens, requiring omission from Authelia instead. | `proposal.md:64`, `tasks.md:71-73`, `verification.md:25-27`. Carried by #2504. | UNTESTED (Authelia refusal probe); provisioning & scopes verified by `tests/test_gitea_machine_identity.py` | Non-contract (tracked in #2504) |
| Major | THEORETICAL | disaster-recovery | AC7 IdP-down drill not executed. Private break-glass connectivity and rotation were proven live, but scaling Authelia to 0 requires unbuilt `toolkit auth drill-idp-down`. | `proposal.md:66`, `tasks.md:85-86`, `verification.md:30-32`. Carried by #2503. | UNTESTED (drill-idp-down); path derivation tested by `tests/test_break_glass.py` (47 tests) | Non-contract (tracked in #2503) |
| Minor | REAL | spec-lifecycle | `tasks.md` Closing section checklist items (lines 93-98) remain unchecked `[ ]`, although the preceding disposition note documents why the spec archives with carried tickets. | `tasks.md:93-98` | N/A (process check) | Spec (contract set: preserved as-is to avoid staling review) |
| Minor | REAL | spec-metadata | `proposal.md` frontmatter has `status: implementing` rather than `archived` prior to running the archive command. | `proposal.md:4` | N/A | Spec (handled automatically by `dotf spec archive`) |
| Minor | REAL | code-quality | Test suites `tests/test_gitea_machine_identity.py` and `tests/test_admin_identity_ssot.py` produce 18 mypy typing errors under strict mode, while production code passes with 0 errors. | Output of `poetry run mypy tests/test_admin_identity_ssot.py tests/test_gitea_machine_identity.py` | Mypy suite check | Tests (follow-up typing polish) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | Core acceptance criteria met on happy paths and scope bounds; interactive refusal gaps formally amended and tracked. |
| Verification       | B | Comprehensive evidence and test suite (74 tests passing, mutation verified red-green); IdP-down drill carried by #2503. |
| Scope              | A | Diff strictly matches ADR-062 requirements and identity plane architecture without scope creep. |
| Reliability        | A | Robust fail-closed validation, idempotent provisioning (`changed=0`), and write-ahead rollback on break-glass rotation. |
| Maintainability    | A | Clean modular structure, cyclomatic complexity <= 10 across all auth modules, and clear ADR/lesson cross-references. |
| Handoff-readiness  | B | Spec amended with transparent disposition of open items to GitHub issues #2503, #2504, and #2505; promotion candidates verified. |

### Verdict

**PASS WITH GAPS**

All identified Major findings are THEORETICAL verification gaps with documented rationales, formal amendments in `proposal.md`, and tracked owning issues (#2503, #2504, #2505). No Blockers or REAL Major functional defects exist. The Evaluator Rubric grades are all B or above.

Archiving via `dotf spec archive AUTH-004-identity-and-machine-access` is **advisable** in this state.

### Recommended next steps

The contract set (`proposal.md`, `tasks.md`) is closed for this review. Do not modify contract files as that would invalidate this review's SHA and digests. Address the following in follow-up work or in non-contract artifacts:

1. **Follow-up issue #2505 (AC2 refusal verification)**:
   - Record an interactive attempt from an active `operator` session attempting an administrative action in Gitea and Grafana, confirming HTTP 403 refusal.
2. **Follow-up issue #2504 (AC5 Authelia exclusion guard)**:
   - Add a unit test asserting that `apps.auth.identities.machine` never appears in `apps.services.security.authelia.users`.
   - Execute and record an attempted first-factor login probe against Authelia as `hefesto`, confirming refusal.
3. **Follow-up issue #2503 (AC7 IdP-down drill)**:
   - Implement `toolkit auth drill-idp-down --env staging` to temporarily scale Authelia to 0, probe private break-glass endpoints, and restore Authelia in a `finally` block.
4. **Test typing cleanup**:
   - Annotate return types and generic dictionary types in `tests/test_gitea_machine_identity.py` and `tests/test_admin_identity_ssot.py` to achieve clean `mypy` test passes.
5. **Execute archive command**:
   - Run `dotf spec archive AUTH-004-identity-and-machine-access` to complete the archive gate and close issue #1013.
