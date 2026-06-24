---
id: "WEB-020-web-repo-extraction"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-06-23"
issue: "kubelab#697"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal, web, repo-structure, gitops]
template_version: "1.0"
---

# WEB-020-web-repo-extraction

> Pilot product for [[adr-053-platform-product-repos|ADR-053]]. Implements [[adr-048-platform-consumer-repo-boundary|ADR-048]].

## Why

<!-- from issue #697: WEB-020: Extract web frontends to own `web` repo (mlorente.dev + kubelab.live) per ADR-048 -->

`apps/web/site` (mlorente.dev) is a consumer product living inside the platform monorepo. ADR-048 decided to extract it; ADR-053 fixed *how* a product repo relates to the platform: **code in its own repo, manifests centralized in kubelab, push-based cross-repo promotion**. This spec extracts mlorente.dev as the **first product to exercise that pattern**, so the kinks are found on a low-risk frontend before any other product follows. Not extracting it keeps the brand product entangled with L0 and leaves the ADR-053 pattern untested.

## What

1. **New `web` repo** (`mlorentedev/web`) holding the mlorente.dev frontend, **migrated WITH git history** (`git filter-repo` on `apps/web/site`), preserving `git blame`.
2. **CI in `web`**: build an immutable `sha-<short>` image → push to Docker Hub (`mlorentedev/kubelab-web`) → fire a **`repository_dispatch`** to kubelab on success.
3. **Receiver workflow in kubelab**: on the dispatch, run `toolkit deployment promote --env staging --app web --version sha-<short>` (ADR-046 path). Prod promotion stays the existing gated `promote-prod.yml`.
4. **Inner loop in `web`**: `make dev` / `npm run dev` (`astro dev`) pointing at the API via env var (`PUBLIC_API_URL`, default `https://api.kubelab.live`). No cluster needed to develop.
5. **Disconnect from kubelab**: remove `apps/web/site` (the Go API and the K8s manifests/overlays STAY in kubelab per ADR-053).
6. **Keep** the `kubelab.live → mlorente.dev` 301 redirect until the `web` repo serves kubelab.live.

## Out of scope

- **kubelab.live rebuild** (ES, fresh) inside the `web` repo — follow-up after mlorente.dev is green (ADR-048 says one repo for both; this spec lands the first domain only).
- **`api.mlorente.dev`** — the web calls the existing `api.kubelab.live` (confirmed canonical; `api.mlorente.dev` is migration residue). A dedicated brand API domain is a separate decision.
- **Scaffold / golden-path template** — distilled later, after 2-3 products (ADR-053 §5).
- **Per-PR ephemeral previews** (ApplicationSet) — deferred (ADR-053 §4).

## Risks / open questions

- **[OPEN — implementation]** `repository_dispatch` needs a PAT scoped to kubelab `contents:write` + `actions:write` stored as a secret in the `web` repo. Define rotation per secrets policy.
- **[OPEN — implementation]** Cross-repo coupling: a frontend change that also needs a manifest change spans two repos (ADR-053 negative consequence). Document the two-repo flow in the `web` README.
- **[RESOLVED]** Deploy target: VPS-K3s via the existing Argo CD staging→prod flow (manifests stay in kubelab). NOT Cloudflare Pages (ADR-045/049).
- **[RESOLVED]** Image promotion mechanism: push `repository_dispatch` → `toolkit deployment promote`, NOT Image Updater/polling (ADR-046/ADR-053 §2).
- **[RESOLVED — 2026-06-23]** Extraction scope: extract **`apps/web/`** (the whole product dir), not just `apps/web/site/`. The `Dockerfile`/`LICENSE`/`README`/`CHANGELOG`/`version.txt` live at `apps/web/`; the Docker build context is `./apps/web` with `COPY site/…`. Extracting `apps/web/` → repo root keeps `site/` as a subdir, so the build maps 1:1 (zero Dockerfile edits) and those files arrive with history.
- **[OPEN — inner-loop]** Code default of `PUBLIC_API_URL` is `https://api.staging.kubelab.live` (`site/src/data/site.ts`), but acceptance criterion #4 says default `https://api.kubelab.live`. Reconcile when wiring `make dev`.

## Acceptance criteria

- [ ] `mlorentedev/web` exists with mlorente.dev history preserved (`git log apps/web/site` lineage visible via `git blame` in the new repo).
- [ ] A push to `web` master builds a `sha-<short>` image, pushes it, and fires a `repository_dispatch` to kubelab.
- [ ] The kubelab receiver workflow promotes that tag to staging via `toolkit deployment promote` and Argo CD syncs it on the staging spoke.
- [ ] `make dev` in `web` serves mlorente.dev locally against `api.kubelab.live` with no cluster running.
- [ ] `apps/web/site` is removed from kubelab; the Go API and `infra/k8s` web manifests remain and still deploy.
- [ ] The `kubelab.live → mlorente.dev` 301 redirect still resolves.

## References

- ADR: [[adr-053-platform-product-repos]] (the pattern), [[adr-048-platform-consumer-repo-boundary]] (the boundary), [[adr-046-gitops-delivery-promotion-strategy]] (promotion), [[adr-045-mlorente-dev-interactive-cv]] (Docker→nginx→K3s lock)
- Epic: kubelab#697 (WEB-020)
- Notifications of deploy events reuse NOTIFY-006 (#685), not a new mechanism
