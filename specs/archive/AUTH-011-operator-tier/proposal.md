---
id: "AUTH-011-operator-tier"
type: spec
status: archived # draft | implementing | verifying | archived
created: "2026-09-26"
issue: "mlorentedev/kubelab#1862"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# AUTH-011-operator-tier

## Why

<!-- from issue #1862: AUTH-011: operator tier — users operate (Argo CD sync, Grafana Editor), admins administer (ADR-062 D2 amendment) -->

AUTH-004 AC2 took the role account `operator` out of `admins` in prod on 2026-09-26 (#1853). That fixed half the model: `operator` no longer administers. The other half is still missing, because in every app `users` gets the same tier as a stranger. In Argo CD `policy.default` makes it `role:readonly`, so it can look but not Sync. In Grafana it is Viewer. The intended split is the IT owner (`manu`, `admins`) who administers everything, and an engineer (`operator`, `users`) who operates the platform without administering it. ADR-062 D2 anticipated this ("no third group until a concrete permission need appears"), and the need has now been measured.

## What

- `users` maps to an operating tier in each app that has one. Argo CD: a new `role:operator`, which is `role:readonly` plus `sync` and `action/*` on applications. Grafana: Editor. Gitea: unchanged (a normal user already owns repositories and pushes).
- `admins` is unchanged: Argo CD `role:admin`, Grafana Admin, Gitea admin.
- Any other group (`e2e`) stays at the floor: Argo CD `role:readonly` via `policy.default`, Grafana Viewer.
- `make auth-review` judges three declared tiers instead of two, so a `users` account that is still Viewer in Grafana reports `drift`.
- ADR-062 D2 is amended: still two groups, and `users` now maps to an operating tier rather than the floor.

## Out of scope

- A third Authelia group. The change is in what `users` maps to, not in the group set.
- How long a demotion takes to reach Argo CD: AUTH-010 (#1861). Widening `users` is a promotion, so that unmeasured bound does not block this.
- Argo CD `exec`, `update`/`delete` of applications, and anything on repositories, clusters, projects, accounts, certificates, GPG keys or RBAC. `admins` keeps all of these.
- Sign-out through Authelia (#1813).

## Risks / open questions

- **Argo CD RBAC reaches the hub only through `make deploy-argocd`**, not GitOps, and that target restarts prod Authelia first (`_deploy-authelia-oidc`). This needs the operator's go-ahead at deploy time. The hub has no staging, so the Argo CD half is verified offline (Argo CD's own evaluator, pinned image) and then in prod.
- **Grafana writes the role at login**, so an open `operator` session stays Viewer until `make auth-review ENV=prod APPLY=1` revokes it (lesson-460).
- **The image the RBAC test runs must be the one the hub runs.** Only the chart version was pinned. This change declares the chart's `appVersion` next to it, so the test does not carry a literal.

## Acceptance criteria

- [ ] AC1: Argo CD's own evaluator, run on the shipped `policy.csv` with the pinned image, allows `users` to get, sync and run actions on applications. It denies `users` create, update and delete of applications, and update of repositories, clusters and projects. `admins` can do all of these, and `e2e` can only read.
- [ ] AC2: Grafana's role path maps `admins` to Admin, `users` to Editor and any other non-empty `groups` to Viewer. It still defers to UserInfo when `groups` is absent or empty.
- [ ] AC3: `make auth-review` declares three tiers (admin, operator, viewer) and maps them per app: Gitea admin/user/user, Grafana Admin/Editor/Viewer.
- [ ] AC4: ADR-062 D2 is amended in place, with the date and the measured need.
- [ ] AC5: In prod, `operator` can Sync an application and is refused on delete and on repository settings. Grafana shows Editor, `manu` is unchanged everywhere, and `make auth-review ENV=prod` reports no drift.

## References

- Bitácora: mlorentedev/kubelab#1862. Related: #1861 (AUTH-010), #1013 (AUTH-004).
- ADR: `docs/adr/adr-062-platform-identity-model.md` D2.
- Lessons: lesson-457 (groups in UserInfo only), lesson-460 (Grafana role settles at the next login), lesson-461 (null-on-empty role path).
