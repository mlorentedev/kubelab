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
- [ ] [web] Update `README.md` for the two-repo flow + `make dev` (`LICENSE`/`.gitignore` already arrived with the extraction)

## CI in the `web` repo

- [ ] [web] Build immutable `sha-<short>` image on push: master, push to Docker Hub `mlorentedev/kubelab-web`
- [ ] [web] On build success, fire `repository_dispatch` (event_type `web-image-published`, payload = tag) to `mlorentedev/kubelab`
- [ ] [web] Dependabot + release automation (mirror kubelab conventions)

## Receiver in kubelab

- [ ] [kubelab] Workflow on `repository_dispatch: web-image-published` → `toolkit deployment promote --env staging --app web --version <tag>`
- [ ] [kubelab] Verify Argo CD syncs the staging spoke with the new tag
- [ ] [kubelab] Prod promotion unchanged (existing gated `promote-prod.yml`)

## Inner loop

- [ ] [web] `make dev` / `npm run dev` (`astro dev`) against `PUBLIC_API_URL` (default `https://api.kubelab.live`), no cluster required
- [ ] [web] Document local/staging/prod API profiles in README

## Disconnect

- [ ] [kubelab] Remove `apps/web/site` (KEEP the Go API and `infra/k8s` web manifests/overlays)
- [ ] [kubelab] Confirm `make deploy-k8s` + Argo CD still deploy web from the centralized manifests
- [ ] [kubelab] Verify the `kubelab.live → mlorente.dev` 301 redirect still resolves

## Closing

- [ ] Every acceptance criterion covered by a test/smoke check
- [ ] `features.json` emitted (one feature per acceptance criterion)
- [ ] `verification.md` filled (cross-repo dispatch evidence + staging deploy)
- [ ] PR(s) opened referencing this spec folder
- [ ] On merge: `git mv specs/WEB-020-web-repo-extraction specs/archive/...`; tick #697

## Machine-readable features

Emit a sibling `features.json` once acceptance is frozen (id, behavior, verification, state, evidence).
The agent CANNOT set `state: passing` — only the harness, after running `verification` with exit 0.
