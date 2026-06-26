---
tags: [spec, tasks]
created: "2026-06-23"
---

# Tasks - WEB-020-web-repo-extraction

> TDD/where-possible order. One task = one focused commit/PR. Spec frozen on entry to `implementing`.
> Cross-repo work: some tasks land in the NEW `web` repo, marked [web]; the rest in kubelab [kubelab].

## Setup

- [x] Confirm repo name `web` (ADR-048 open decision — owner: proposed `mlorentedev/web`) ✓ 2026-06-23
- [x] `proposal.md` acceptance criteria reviewed ✓ 2026-06-23
- [x] Mint a kubelab-scoped PAT (`contents:write` + `actions:write`) for cross-repo dispatch; store as `web` repo secret ✓ 2026-06-23 (fine-grained, scoped to `kubelab`)

## Extraction (with history)

> **Scope (decided 2026-06-23):** extracted **`apps/web/`** (whole product dir), NOT just `apps/web/site/` — the `Dockerfile`/`LICENSE`/`README`/`CHANGELOG`/`version.txt` live at `apps/web/` and the build context is `./apps/web` with `COPY site/…`. Extracting `apps/web/` → repo root keeps `site/` as a subdir → Docker build maps 1:1, zero Dockerfile edits, files arrive with history. See `proposal.md` Risks.

- [x] [web] `git filter-repo` of `apps/web/` → new `mlorentedev/web`, history preserved (239→12 commits; public; default branch `master`) ✓ 2026-06-23
- [x] [web] Verify `git blame` lineage survives on a sample file (`site/package.json`, `Dockerfile` → `a93727f`; `--follow` on `site/src/data/site.ts`) ✓ 2026-06-23
- [x] [web] Update `README.md` for the two-repo flow + `make dev` ✓ 2026-06-25 (README has "Deployment — the two-repo flow (ADR-053)" + "Local development"; `LICENSE`/`.gitignore` arrived with the extraction)

## CI in the `web` repo

- [x] [web] Build immutable `sha-<short>` image on push: master, push to Docker Hub `mlorentedev/kubelab-web` ✓ 2026-06-25 (verified: `build-image.yml` reusable buildx workflow + `release.yml` push on master → `docker.io/mlorentedev/kubelab-web:sha-<short>`; exercised by `sha-20c9f91`, `sha-5bd6c07`)
- [x] [web] On build success, fire `repository_dispatch` (event_type `web-image-published`, payload = tag) to `mlorentedev/kubelab` ✓ 2026-06-25 (verified: `release.yml` job `dispatch-staging` fires `{event_type: web-image-published, client_payload:{tag,sha}}` via `KUBELAB_DISPATCH_TOKEN`)
- [x] [web] Dependabot + release automation (mirror kubelab conventions) ✓ 2026-06-25 (verified: `dependabot.yml` present + release-please in `release.yml`; follow-up #730 for a npm group-bump build break)

## Receiver in kubelab

- [x] [kubelab] Workflow on `repository_dispatch: web-image-published` → `toolkit deployment promote --env staging --app web --version <tag>` ✓ 2026-06-24 (PR #751; exercised by staging PRs #753 `sha-20c9f91`, #756 `sha-5bd6c07`)
- [x] [kubelab] Verify Argo CD syncs the staging spoke with the new tag ✓ 2026-06-24 (staging spoke runs `kubelab-web:sha-5bd6c07` READY 1/1 == master overlay pin == receiver-promoted tag from PR #756; chain dispatch→promote→sync confirmed. Direct `argocd app get` would need the hub transport — one-at-a-time limit)
- [x] [kubelab] Prod promotion unchanged (existing gated `promote-prod.yml`) ✓ 2026-06-24 (receiver touches staging overlay only)

## Inner loop

- [~] [web] `make dev` / `npm run dev` (`astro dev`) against `PUBLIC_API_URL` (default `https://api.kubelab.live`), no cluster required
  - **PARTIAL (verified 2026-06-24 read-only via gh):** `make dev` exists and runs `astro dev` with no cluster ✓, BUT bare `make dev` resolves to `https://api.staging.kubelab.live` (code default in `site/src/data/site.ts`), NOT the `api.kubelab.live` that acceptance criterion #4 specifies. The `web` Makefile `dev:` target sets no `PUBLIC_API_URL` export; the README only shows the canonical URL as a manual override (`PUBLIC_API_URL=https://api.kubelab.live npm run dev`). Three sources disagree — this is the proposal's OPEN question (line 44), still unresolved. Reconciliation is a `web`-repo edit interacting with ADR-054 (same-origin reverse-proxy); NOTE Astro bakes `PUBLIC_API_URL` at build time, so changing the code default would also change the staging-deployed runtime target. **No new ticket — already owned by `mlorentedev/web#6` (WEB-021 "implement ADR-054 — same-origin /api"), whose body explicitly states it "resolves the `api.staging` vs `api.kubelab` drift" by moving to relative `/api` and removing the baked `PUBLIC_API_URL` default.** Conflict-checked 2026-06-24 to avoid a duplicate. WEB-021 was "blocked by ADR-054 (kubelab#750) approval" — kubelab#750 is now MERGED, so WEB-021 is unblocked. WEB-020 #4 stays open until WEB-021 lands and `make dev` resolves the canonical API per ADR-054.
- [~] [web] Document local/staging/prod API profiles in README — **delegated to WEB-021** (web#6, ADR-054): same-origin relative `/api` makes the local/staging/prod profile split moot (no baked per-env `PUBLIC_API_URL`). README currently documents the canonical override; the profile model is rewritten by ADR-054.

## Disconnect

- [x] [kubelab] Remove `apps/web/site` (KEEP the Go API and `infra/k8s` web manifests/overlays) ✓ 2026-06-24 (PR #755; `apps/web/` gone, `apps/api` + `mlorentedev/kubelab-web` pin in `base/kustomization.yaml` + staging/prod overlays remain)
- [x] [kubelab] Confirm `make deploy-k8s` + Argo CD still deploy web from the centralized manifests ✓ 2026-06-24 (web Deployment in `kubelab` ns serves from centralized overlay, 1/1 available, after `apps/web/site` removal — Go API + manifests remain authoritative)
- [x] [kubelab] Verify the `kubelab.live → mlorente.dev` 301 redirect still resolves ✓ 2026-06-24 (HTTP 308 permanent → `https://mlorente.dev/`, served at Cloudflare edge `Server: cloudflare`, NOT VPS Traefik; `mlorente.dev` returns 200 via nginx. Note: 308 not literal 301 — both permanent; redirect lives at DNS/CDN layer)

## Closing

- [x] Every acceptance criterion covered by a test/smoke check ✓ 2026-06-25 (5/6 verified, AC4 partial — canonical-API delegated to WEB-021; see `verification.md`)
- [x] `features.json` emitted (one feature per acceptance criterion) ✓ 2026-06-25
- [x] `verification.md` filled (cross-repo dispatch evidence + staging deploy) ✓ 2026-06-25
- [x] PR(s) opened referencing this spec folder ✓ 2026-06-25 (closing PR `docs/web-020-close-spec`)
- [x] On merge: `git mv specs/WEB-020-web-repo-extraction specs/archive/...`; tick #697 ✓ 2026-06-25 (folder moved in this PR; #697 closes on merge → bitácora Done)

## Machine-readable features

Emit a sibling `features.json` once acceptance is frozen (id, behavior, verification, state, evidence).
The agent CANNOT set `state: passing` — only the harness, after running `verification` with exit 0.
