---
tags: [spec, verification, web, repo-structure, gitops]
created: "2026-06-25"
---

# Verification - WEB-020-web-repo-extraction

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (PR, workflow, or observed behavior).
Cross-repo: `web` = `mlorentedev/web`, `kubelab` = `mlorentedev/kubelab`.

- [x] **AC1** (`mlorentedev/web` exists, mlorente.dev history preserved, `git blame` lineage) -> **verified 2026-06-23**: `git filter-repo` of `apps/web/` -> `mlorentedev/web` (239->12 commits; public; default branch `master`). Blame lineage survives: `site/package.json` and `Dockerfile` trace to `a93727f`; `--follow` works on `site/src/data/site.ts`.
- [x] **AC2** (push to `web` master builds `sha-<short>`, pushes it, fires `repository_dispatch`) -> **verified 2026-06-24**: `web` `release.yml` builds via reusable `build-image.yml` (multi-arch buildx -> Docker Hub `mlorentedev/kubelab-web:sha-<short>`), then job `dispatch-staging` fires `repository_dispatch` (`event_type: web-image-published`, `client_payload: {tag, sha}`) to `mlorentedev/kubelab` using `KUBELAB_DISPATCH_TOKEN`. Exercised live by staging promotions: PR #753 (`sha-20c9f91`), PR #756 (`sha-5bd6c07`).
- [x] **AC3** (kubelab receiver promotes tag to staging via `toolkit deployment promote`; Argo CD syncs the staging spoke) -> **verified 2026-06-24**: receiver workflow PR #751 (`repository_dispatch: web-image-published` -> `toolkit deployment promote --env staging --app web --version <tag>`). Argo CD staging spoke runs `kubelab-web:sha-5bd6c07` READY 1/1 == master overlay pin == receiver-promoted tag from PR #756. Full chain dispatch->promote->sync confirmed. Prod promotion unchanged (gated `promote-prod.yml`; receiver touches staging overlay only).
- [~] **AC4** (`make dev` serves mlorente.dev locally against `api.kubelab.live`, no cluster) -> **PARTIAL, residual delegated**: `make dev` / `npm run dev` (`astro dev`) runs with no cluster ✓. The canonical-API half is NOT met by a bare `make dev`: the code default of `PUBLIC_API_URL` is `https://api.staging.kubelab.live` (`site/src/data/site.ts`), not the `https://api.kubelab.live` AC4 specifies; the `web` README documents the canonical URL only as a manual override (`PUBLIC_API_URL=https://api.kubelab.live npm run dev`). This `api.staging` vs `api.kubelab` drift is owned by **WEB-021** (`mlorentedev/web#6`, "implement ADR-054 — same-origin `/api`"), which removes the baked `PUBLIC_API_URL` default by moving to a relative `/api` reverse-proxy. WEB-021 was blocked by ADR-054 (kubelab#750) approval; #750 is now MERGED, so WEB-021 is unblocked. Per the WEB-020 closure decision (2026-06-25), AC4's "no cluster" guarantee is satisfied and the canonical-API reconciliation is delegated to WEB-021.
- [x] **AC5** (`apps/web/site` removed; Go API + `infra/k8s` web manifests remain and still deploy) -> **verified 2026-06-24**: PR #755 (`apps/web/` removed; `apps/api` + the `mlorentedev/kubelab-web` pin in `base/kustomization.yaml` + staging/prod overlays remain). `make deploy-k8s` + Argo CD still deploy web from the centralized overlay: web Deployment in `kubelab` ns 1/1 available after removal — Go API + manifests remain authoritative.
- [x] **AC6** (`kubelab.live -> mlorente.dev` 301 redirect still resolves) -> **verified 2026-06-24**: HTTP 308 permanent -> `https://mlorente.dev/`, served at the Cloudflare edge (`Server: cloudflare`), NOT VPS Traefik; `mlorente.dev` returns 200 via nginx. Note: 308 (not literal 301) — both are permanent; the redirect lives at the DNS/CDN layer.

## Test status

This spec is a repo-extraction + GitOps-wiring change; its "tests" are the live deploy chain and the new repo's CI, not unit tests in kubelab.

- **Cross-repo dispatch chain (primary smoke):** `web` push -> `build-image.yml`/`release.yml` -> `sha-<short>` image on Docker Hub -> `repository_dispatch` -> kubelab receiver -> `toolkit deployment promote --env staging` -> Argo CD staging sync. Exercised end-to-end twice (PR #753 `sha-20c9f91`, PR #756 `sha-5bd6c07`).
- **Staging parity:** staging spoke `kubelab-web:sha-5bd6c07` READY 1/1 == master overlay pin (receiver-promoted tag).
- **Disconnect regression:** post-removal web Deployment 1/1 available from the centralized overlay (Go API + manifests authoritative).
- **Redirect smoke:** `kubelab.live` -> 308 -> `https://mlorente.dev/` (200, nginx).
- **`web` repo CI present:** `build-image.yml`, `release.yml` (release-please + dispatch), `pr-validation.yml`, `dependabot.yml`, bitácora wiring (`add-to-project.yml`, `bitacora-status.yml`).

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections. Routine choices belong in commit messages.

- **Extract `apps/web/` (whole product dir), not just `apps/web/site/`** — the `Dockerfile`/`LICENSE`/`README`/`CHANGELOG`/`version.txt` live at `apps/web/`; the Docker build context is `./apps/web` with `COPY site/…`. Extracting `apps/web/` -> repo root keeps `site/` as a subdir, so the build maps 1:1 (zero Dockerfile edits) and those files arrive with history.
- **Push `repository_dispatch`, not Image Updater/polling** — per ADR-046/ADR-053 §2. The `web` CI pushes the deploy signal; kubelab's receiver owns the promotion via `toolkit deployment promote`. Keeps manifests centralized (ADR-053) and the promotion path identical to other apps.
- **Manifests stay in kubelab** — only the frontend *code* moved. The Go API and `infra/k8s` web overlays remain authoritative in kubelab (ADR-053 platform-vs-product split).
- **AC4 canonical-API reconciliation delegated to WEB-021** — rather than patch the `PUBLIC_API_URL` default in this spec, the drift is resolved holistically by ADR-054 (same-origin relative `/api`), already ticketed as WEB-021. Avoids a throwaway edit that ADR-054 would immediately supersede (Astro bakes `PUBLIC_API_URL` at build time, so changing the code default also changes the staging-deployed runtime target — a coupling WEB-021 removes entirely).

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault.

- [ ] Lesson for the repo's `docs/lessons.md`? **no** — the governance lesson (verify master before closing a duplicate of a closed twin) already landed via PR #747; the two-repo-flow mechanics live in ADR-053 + the `web` README.
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? **no** — ADR-048 (boundary), ADR-053 (pattern), ADR-046 (promotion), ADR-054 (env config) already cover the decisions; this spec is their first implementation.
- [ ] New pattern candidate for `00_meta/patterns/`? **deferred** — the platform↔product repo pattern is a real cross-project candidate, but ADR-053 §5 explicitly distils the golden-path template only after 2-3 products. Premature here (web is product #1).

## Archive checklist

- [x] `proposal.md` frontmatter set to `status: archived` ✓ 2026-06-25
- [x] Folder moved: `specs/WEB-020-web-repo-extraction/` -> `specs/archive/WEB-020-web-repo-extraction/` ✓ 2026-06-25
- [ ] Bitácora epic #697 — close on merge (built-in workflow -> Done). Residuals tracked separately: WEB-021 (web#6, AC4 canonical API), WEB-022 (web#7, Astro 6), kubelab.live rebuild (follow-up, out of scope per proposal).
