---
tags: [spec, tasks]
created: "2026-06-23"
---

# Tasks - WEB-020-web-repo-extraction

> TDD/where-possible order. One task = one focused commit/PR. Spec frozen on entry to `implementing`.
> Cross-repo work: some tasks land in the NEW `web` repo, marked [web]; the rest in kubelab [kubelab].

## Setup

- [ ] Confirm repo name `web` (ADR-048 open decision — owner: proposed `mlorentedev/web`)
- [ ] `proposal.md` acceptance criteria reviewed
- [ ] Mint a kubelab-scoped PAT (`contents:write` + `actions:write`) for cross-repo dispatch; store as `web` repo secret

## Extraction (with history)

- [ ] [web] `git filter-repo` (or subtree split) of `apps/web/site` → new `mlorentedev/web`, history preserved
- [ ] [web] Verify `git blame` lineage survives on a sample file
- [ ] [web] Add `LICENSE`, `README.md` (documents the two-repo flow + `make dev`), `.gitignore`

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
