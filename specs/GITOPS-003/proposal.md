---
id: "GITOPS-003"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-08-27"
issue: "mlorentedev/kubelab#1478"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# GITOPS-003

> **Naming**: file lives at `<repo>/specs/GITOPS-003/proposal.md`. `GITOPS-003` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #1478: GITOPS-003: an Argo CD auto-sync that fails is never retried — verify web promotions by consequence -->

A merged manifest is treated as a deploy. Twice (#1457, #1465) the same-origin `/api` route reached staging's git overlay with green CI and never reached the cluster: first because the route did not match, then because Argo CD's automated sync panicked and was never retried. Nothing between `merge` and `Synced at the merge SHA` reports back, so the newsletter path (#190, broken since June) can be declared fixed while still returning nginx's 404 — and the only detector so far has been a human running `curl`.

## What

Since #2566 (2026-10-20) web reaches staging through `product-image-receiver.yml`: a web image dispatch updates the long-lived `deploy/staging-web` PR, a human merges it, and Argo CD auto-syncs `kubelab-staging`. Every check below starts after that merge. `staging.mlorente.dev` has no public DNS record (`dig @1.1.1.1` answers nothing), which is the measured reason no hosted job can read the served commit itself.

Argo CD reports outward; CI never enters the mesh (GitHub-hosted runners, ADR-030, reach neither the hub nor staging's VPN-only DNS).

1. **Every completed sync operation of `kubelab-staging` / `kubelab-prod` sets a GitHub commit status** on the synced revision in `mlorentedev/kubelab`: context `argocd/<app>`, `success` from `on-sync-succeeded`, `failure` carrying `operationState.message` from `on-sync-failed`. Mechanism: notifications `service.webhook.github` → `POST /repos/mlorentedev/kubelab/statuses/<sha>` with a PAT (same shape as the Slack webhook; lesson-236).
2. **A post-merge workflow `deploy-verify.yml`** (one job per touched env; triggered by the Argo status and a schedule, never by `on: push` alone, because a merge made with `GITHUB_TOKEN` starts no push workflow and #1619 moves staging merges to a workflow) waits up to N minutes for `argocd/kubelab-<env>` on `github.sha` and goes **red** when the status is `failure` or never arrives (Argo down, hub unreachable, sync skipped). A green run means that cluster is at the merge SHA, not that a file changed. Prod's run sits behind the existing promote gate (ADR-046): it only fires once a prod promotion has merged.
3. **A `PostSync` hook Job in both overlays** sends a malformed `POST /api/subscribe` to the web host (`staging.mlorente.dev`, `mlorente.dev`) through `traefik.kube-system.svc` (`--connect-to`, real SNI/Host) and fails the sync unless the answer is `400` with `content-type: text/plain` (the API) — `text/html` or `server: nginx` means the route still lands in the web pod. A failed hook is a failed operation, so (1) publishes it. The hook also compares `version.json`'s `commit` with the tag it was rendered with: the route probe proves the API answers on the web host, the commit proves the web pod runs the promoted image, and the 2026-08-27 incident and the eleven-releases one each broke exactly one of the two. **Sequencing:** a hook is binary and a missing `commit` is never a pass, so it would fail every web staging sync until web#435 is live, and Argo does not retry a failed revision. PR3 lands only after `make verify-product APP=web ENV=staging` stops answering exit 3, and its hook is rendered per product from the contract, like the check above.
4. **`make verify-product APP=<app> ENV=staging|prod`** (`toolkit infra argo verify-product`): the operator's by-consequence check, for any contract-managed product in the registry (web is the first),, runnable from any box on the mesh after any sync. It reads `kubelab-<env>` from the hub and waits, up to a deadline, for `sync.status == Synced` at `origin/master` HEAD with the last `operationState.phase == Succeeded`, then for the product's host to serve the image tag pinned at HEAD. Host and image come from the contract snapshot (`infra/config/products/contracts/<app>.yaml`, ADR-067), never from per-product code. The served answer is a **platform convention**: every contract-managed product serves `GET https://<host>/version.json` as `{"version":"X.Y.Z","commit":"<7 hex>"}`, `commit` being its image tag minus `sha-` (web implements it in web#435 / web#477; interface fixed on #1478 2026-10-20). A per-product `version_path` contract field is a possible later override, not needed now: a `sha-<hex>` tag must equal `commit` with `sha-` removed, a semver tag (prod) must equal `version`. A payload without `commit` is **not verifiable yet**, with its own exit code, never a pass. Every non-zero exit prints `operationState.message`.
5. **A runbook section** for a red `deploy-verify`: read `operationState.message`, `make sync-app APP=kubelab-<env>`, and `make restart-argocd` only if the same panic repeats. A new signal without a written response is the Slack alert again (#685).

## Out of scope

- **Argo CD 3.4.1 → 3.5.x** (chart `9.5.13` → `10.4.0`): removes the panic itself, but it is a chart major with its own release notes and rollback plan → #1209. This spec makes the failure *visible*; it does not make it impossible.
- **Routing the Slack alert to somewhere it is read**, and any notification-disposition process → #685. This spec adds the GitHub destination next to the Slack one; it does not touch, replace or re-route Slack.
- **The receiver and the human gate.** `product-image-receiver.yml` (IDP-042) and the merge gate on staging/prod PRs (#1619) are not touched: verification runs after the merge, as its own step.
- **Detecting drift the other way** (a live resource differing from git while Argo says `Synced`) → #1164. Here the question is only whether the merge SHA was applied and whether the route answers.

## Risks / open questions

1. **The hook's network path — measured, resolved.** From a pod on `ace1` (2026-08-27, `curlimages/curl`, ephemeral) both paths reach the API through Traefik: the Tailscale hairpin `https://staging.mlorente.dev` and the in-cluster service `traefik.kube-system.svc` with the web host as `Host`. Signatures: `GET /api/health` → `404 text/plain` (Gin), `POST /api/subscribe` with a malformed body → `400 text/plain; charset=utf-8` (Gin); the web pod answers `200 text/html`, `server: nginx`. **Decision:** the hook targets the service, not the hairpin — `curl --connect-to <host>:443:traefik.kube-system.svc:443 https://<host>/api/subscribe -X POST -d '{'` keeps SNI and `Host` on the real name so the Let's Encrypt certificate validates without `-k`, and it does not depend on CoreDNS-custom or on the node's Tailscale address. **Healthy = `400` and `content-type: text/plain`; broken = `text/html` or `server: nginx`.** A `404` is never the healthy signal.

2. **The Argo → GitHub credential — decided 2026-08-28 (#1478): fine-grained PAT**, `statuses:write` on kubelab, expiry set, in SOPS, delivered by `toolkit secrets apply`; its expiry is what AC6 catches. Not minted yet as of 2026-10-20, which is what blocks PR1. **The same credential is what lets PR2 run**: `deploy-verify.yml` triggers `on: status`, which a status posted with `GITHUB_TOKEN` would never start; a PAT's (or a GitHub App installation token's) does. It is therefore on the PAT inventory that dotfiles#2836 (SEC-017, GitHub App ADR) replaces, and any replacement must keep the Argo status able to start workflows. Original question: `service.webhook.github` needs a token in `argocd-notifications-secret`: a fine-grained PAT scoped to `statuses:write` on `kubelab`, with an expiry and a rotation path through SOPS + `toolkit secrets apply` (lesson-013: Argo CD never creates Secrets). A GitHub App is the alternative (more moving parts, no expiry). Decide which; the template is the same either way.
3. **Latency and N — measured, resolved.** `timeout.reconciliation` on the hub is `120s`; over today's seven automated staging syncs the merge→`deployStartedAt` lag was 0, 0, 0, 2, 3, 3 and 6 minutes (the "52 minutes" first read off the sync history was a misread: #1477 merged at 04:09:17Z, not at its PR-creation time). **N = 10 minutes** — above the observed maximum with the poll interval on top; a status that has not arrived by then is a sync that did not run. Also: a hook that fails because the API itself is down turns every web sync into `failure`; `hook-delete-policy: HookSucceeded` keeps the failed Job for inspection and the wave stays `PostSync` so a failed probe is loud without wedging later syncs.

## Acceptance criteria

- [ ] **AC1** — After a merge to `master` touching `infra/k8s/overlays/<env>/**`, that commit carries a status `argocd/kubelab-<env>` within N minutes: `success` when `operationState.phase == Succeeded` at that revision, `failure` carrying `operationState.message` when `Error`/`Failed`. Verified with `gh api repos/mlorentedev/kubelab/commits/<sha>/status`.
- [ ] **AC2** — `deploy-verify.yml` ends **red** when the status is `failure` or has not arrived after N minutes, and green only on `success`. Verified by a unit test of the wait script against a simulated API, plus real runs: against `1489265` (no status → red) and against the next healthy merge (green).
- [ ] **AC3** — The `PostSync` hook fails the sync when a malformed `POST /api/subscribe` on the web host answers `text/html`/`server: nginx`, and leaves it `Succeeded` on `400 text/plain`; the Job is cleaned up after success (`hook-delete-policy`). Verified by a generator test (`tests/test_k8s_generator_*.py`) plus one real run on staging.
- [ ] **AC4** — `make verify-product APP=web ENV=staging|prod` exits 0 only when, before its deadline (default 10 minutes, Risk 3), `kubelab-<env>` is `Synced` at `origin/master` HEAD with `operationState.phase == Succeeded` **and** the contract host's `/version.json` serves the tag pinned at HEAD (`commit` for `sha-*`, `version` for semver). It exits 1 on a failed operation at HEAD (immediately: Argo will not retry it) or on no match by the deadline, 2 when the hub or the host cannot be reached, and 3 when the host serves no `commit` (not verifiable yet); every non-zero exit prints `operationState.message`. Application health is deliberately not a condition: staging is `Degraded` by unrelated Jobs as of 2026-10-20. An app with no contract (in-tree `api`, an unregistered name) is refused with exit 2. Verified by `tests/test_product_verify.py` and by running it in both environments.
- [ ] **AC5** — The `trigger.on-sync-*` expressions are rendered by a test with `operationState == nil` and with an empty `syncResult`, and neither raises: a raised expr-lang expression is a silently skipped trigger (see the comment block in `infra/helm/argocd/values.yaml`).
- [ ] **AC6** — The token behind `service.webhook.github` is checked by consequence — an authenticated `GET` against the GitHub API returns 200 — from `tests/infra` (or uptime-kuma), so an expired PAT stops publishing statuses loudly, not silently.
- [ ] **AC7** — `docs/runbooks/` carries a "deploy-verify is red" section naming the three commands above, linked from lesson-407 and from the workflow's failure message.

## References

- Bitácora: mlorentedev/kubelab#1478 (GITOPS-003). Incident evidence on #1465, #1209, #685, #1249.
- Lessons: `docs/lessons/gitops-delivery/lesson-407-…` (this incident), lesson-236 (`service.webhook`, not `service.slack`), lesson-013 (Argo CD never creates Secrets), lesson-319 (a manifest changed in git is a claim), lesson-406 (a routing change is not verified by its manifest).
- ADRs: adr-046 (gated promotion), adr-030 (GitHub-hosted runners by default; self-hosted opt-in per job), adr-052 (cluster access transport), adr-053 (two-repo delivery), adr-067 (product contract; `product-image-receiver.yml` since #2566 replaced `web-image-receiver.yml` for web).
- Upstream: argoproj/argo-cd#27659 / #27750 (the panic; fixed in v3.5.0+), Argo CD notifications `webhook` service, GitHub REST `POST /repos/{owner}/{repo}/statuses/{sha}`.
