---
id: "IDP-042-product-contract-registry"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-10-17"
issue: "mlorentedev/kubelab#1926"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal, idp, product-contract, registry, delivery]
template_version: "1.0"
wip_override: "Operator 2026-10-17: granted over the WIP limit (20 active, limit 10). Archiving one spec would not unblock the gate; burndown tracked in #2443."
---

# IDP-042-product-contract-registry

> Operator decisions on Q1-Q8 were recorded on 2026-10-17 and are under "Decisions" below. Design point 2 and AC6 were adjusted for Q7.

## Why

<!-- from issue #1926: IDP-042: product contract schema, registry and one generic receiver -->

Onboarding a product to kubelab means editing about a dozen places by hand (inventory below), and the third product is refused outright: `toolkit deployment promote` raises for any app outside the tuple `("api", "web")` (#1815). Each product also needs its own receiver workflow, which is how `web-image-receiver.yml` came to be 163 lines that a second product would copy. ADR-067 D2 and D3 replace this with a contract the product owns (`kubelab.yaml`), a registry of admitted products, and one receiver that serves all of them. #1815 is folded in because D2 derives `PLATFORM_APPS` from the registry, so it is not a separate change.

## What

After this work:

- kubelab publishes a JSON Schema for `kubelab.yaml` (image repository, port, health path, hostname per environment, auth level, secret names) and a command that validates a contract against it.
- A registry file lists the admitted products: app, repository, forge and event types. A product absent from it is refused. `PLATFORM_APPS` no longer exists as a literal; the platform apps are read from the registry, so `toolkit deployment promote --app <any registry product>` works (#1815).
- One workflow, `product-image-receiver.yml`, replaces `web-image-receiver.yml`. It maps the dispatch event type to an app through the registry, accepts only an immutable `sha-*` tag, fetches the contract at the commit that tag names, validates it, renders the derived configuration, runs `toolkit deployment promote`, and opens or updates the staging PR. The payload carries only the tag.
- A committed snapshot of each contract, the registry and the derived configuration are checked against each other by an offline test, so a hand edit to a derived value fails CI.
- `web` runs on all of it, and its old receiver is deleted. The next product (garsync) is onboarded by a contract plus a registry entry; that onboarding is the proof, and is tracked in the epic, not built here.

### Onboarding today: what a plain public product touches

The ADR says "11 mandatory edits" and does not list them (the research issue #1924 does not either). This is a reconstruction from the code on `origin/master` at `6570c66a`, so the count is mine, not a confirmation of the ADR's. Fate column: **removed** (this spec deletes the edit), **reads registry** (the file stays, the literal goes), **rendered** (the file stays and the contract writes it), **stays** (out of scope, named so the silence is deliberate).

| # | Edit | Evidence | Fate |
|---|------|----------|------|
| 1 | `apps.platform.<app>` block: image_name, port, health_path, auth | `infra/config/values/common.yaml:949-960` (web) | rendered for staging/prod; web-specific keys (`site_*`, `extra_routes`, `backend_url`, `allowed_hosts`) stay |
| 2 | staging overrides: domain, port, version pin | `infra/config/values/staging.yaml:44-54` | rendered (domain, port); version stays written by `promote` |
| 3 | prod overrides: domain, port, version pin | `infra/config/values/prod.yaml:76-86` | rendered (domain, port); version stays written by `promote` |
| 4 | the hardcoded tuple | `toolkit/config/constants.py:48` (+ alias `:77-78`) | **removed** |
| 5 | the refusal in `promote` / `resolve_image_sha` | `toolkit/features/promotion.py:61-65`, `:160-164` | **reads registry** |
| 6 | per-product staging receiver | `.github/workflows/web-image-receiver.yml` (163 lines, `on:` at `:23-25`) | **removed** (last PR) |
| 7 | per-product prod trigger and guards | `.github/workflows/promote-prod.yml:34-35` (choice), `:42` (event type), `:56` (`\|\| 'web'` group), `:93` (`app=web`), `:101-104` (case guard) | **reads registry** (Q4) |
| 8 | local dispatch guard | `Makefile:963`, `:965` (`web\|api`) | **reads registry** |
| 9 | prune default | `toolkit/cli/registry.py:21` (`"api,web,errors"`) | **reads registry** (+ `errors`) |
| 10 | the delivery-lane set | `tests/test_delivery_health.py:48-54` (`EXPECTED`) | rewritten once: the generic receiver replaces the per-product one |
| 11 | per-product receiver and dispatch tests | `tests/test_web_image_receiver_workflow.py`, `tests/test_promote_prod_dispatch.py:43,47,90` | rewritten against the generic workflow |
| 12 | prod DNS record for the hostname | `infra/terraform/dns/records_mlorente.tf:5-30` (mechanism for a new hostname not traced) | **stays** (see Out of scope) |

That is 12 rows, 11 of them inside the scope of this spec (the DNS row stays), against the ADR's 11. The count matters less than the shape: every row is either a literal that names `web`/`api`, or a copy of what the product already knows about itself.

Further sites that a product touches only conditionally, all **stay**: `SECRET_CATALOG` and `toolkit/features/k8s_secrets.py:133-135` when the product has secrets; an OIDC client in `apps.services.security.authelia.oidc_clients` when `auth: oidc`; `tests/e2e/expectations.py:139` (one e2e expectation per service); `infra/config/values/common.yaml:545` and `tests/test_branch_protection.py:~228` (the product repository's branch protection, declared per repository, not per product); `toolkit/scripts/sync_homepage_config.py:268` (reads `platform["web"]` by name). Outside kubelab, the product's CI needs the dispatch step and `KUBELAB_DISPATCH_TOKEN`.

One suspected leftover, not verified: `.github/workflows/ci-pipeline.yml:196-218` builds `web` args from `apps.platform.web.*` although `apps/web` left the monorepo (ADR-053). Worth a ticket if no caller passes `app: web`.

## Design points the proposal fixes (they follow from the ADR and the code, they are not choices)

1. **The dispatched tag is an image tag, not a git ref.** CI publishes `sha-${GITHUB_SHA::7}` (`web-image-receiver.yml:71`, `promotion._SHA_TAG`). "Fetch the contract at the dispatched tag" therefore means: strip `sha-`, resolve the 7+ hex characters to a commit through the product repository's API, refuse if it does not resolve to exactly one commit, and read `kubelab.yaml` at that commit. The contract and the image come from the same commit. The commit must also be reachable from the repository's default branch, so a commit that exists only in a fork network is refused.
2. **The registry is the trust anchor, the contract cannot widen it.** The contract is attacker-shaped data (anyone who can push to the product repo writes it). It is parsed with `yaml.safe_load`, validated with `additionalProperties: false` and anchored patterns (hostnames, names, port range, a health path starting with `/`), and then checked against the registry and the platform: the image repository must equal the one the platform derives for that product (Q7), a secret name must already exist in `SECRET_CATALOG`, a hostname may not already belong to another route. Anything else is refused with ERROR / WHY / FIX.
3. **`api` has no remote repository** (ADR-048: the API is evolved in place). If `PLATFORM_APPS` is derived from the registry, `api` needs an entry whose forge is `in-tree` and which has no dispatch event. Otherwise `generator_k8s.py:224` and `generator_traefik.py:189` stop emitting it. `api`'s values stay hand-authored in this phase; moving `api` onto a contract belongs with IDP-043.
4. **`errors` is not a product.** It is edge furniture on an env-agnostic semver (DELIVERY-003). The registry replaces only the `("api", "web")` tuple; `_promote_errors` and the `errors` branch of `promote()` stay, and `EDGE` in `constants.py` is untouched.
5. **`auth: oidc` is accepted by the schema and refused by the renderer** until an OIDC client can be rendered from the contract. `toolkit/features/oidc_clients.py` is owned by another session in this lane, so this spec does not touch it. A product declaring `oidc` fails at render with an ERROR / WHY / FIX naming the follow-up; a silent deploy without its client would be worse than a refusal.
6. **Event types are not renamed.** `web-image-published` and `web-release-published` stay and the registry maps them to `web`. `tests/test_promote_prod_dispatch.py:30-45` records why: a cross-repo rename drifts silently, because GitHub accepts a dispatch no workflow listens for with a 204 and drops it.
7. **`COMPONENTS` is a frozen dataclass**, so a registry-derived list cannot be a field computed at import. A cached `platform_apps()` in a new `toolkit/features/product_registry.py` replaces it; the consumers to switch are `generator_k8s.py:224`, `generator_traefik.py:189`, `promotion.py:61` and `:160`, `constants.py:77-78` (the `APPS` alias, whose one consumer is `generator_authelia.py:44`) and `tests/test_k8s_generator_secrets.py:41`.
8. **The toolkit commands take paths, not URLs.** `toolkit product validate|render` read a contract file and the registry file as inputs and need no SOPS key (ADR-067 D8). The workflow fetches; the toolkit does not know which forge. A Gitea path later changes the workflow's fetch step and nothing else.
9. **A contract snapshot is committed**, verbatim, next to the registry (`infra/config/products/contracts/<app>.yaml`, written by the receiver in the same PR). Without it the drift test would need the network. With it a reviewer also sees the contract diff in the staging PR.
10. **Coexistence has a hazard.** Both receivers listen for `web-image-published`; if both are live, both run and race `deploy/staging-web`. The cutover therefore flips one registry field (`receiver: generic`) and demotes the old workflow to `workflow_dispatch` only in the same PR, and the old file is deleted only after a real dispatch has been observed (tasks.md PR 7, PR 8).
11. **A generic workflow cannot enumerate its event types without a workflow edit per product.** `on.repository_dispatch.types` is a static list. The decision is Q5: omit `types`.

## Out of scope

- Tenancy: namespace, AppProject, SOPS recipient per product, and moving `api`/`web` out of `kubelab` (phase 2 of the epic; #400, #378, #889, #1927).
- The private path: the tenant repository on Gitea, its runner and the Argo source (IDP-044, #1928). The registry's `forge` field and the path-based toolkit commands leave room for it; nothing here builds it.
- Rendering an OIDC client from a contract, and anything in `toolkit/features/oidc_clients.py` or `toolkit/features/credentials.py`.
- DNS records derived from contract hostnames (row 12), e2e expectations derived from the contract, branch protection per product repository.
- Onboarding garsync. This spec makes it possible and names it as the next step; the product repo and its ADR-011 are its own work.
- Anything on the MCP side (phase 4) and image signing (phase 5).
- Prod auto-merge of generated PRs (ADR-067 D7). Every PR here still needs a human merge.

## Risks

- **The prod lane reads the staging-validated contract.** `promote-prod.yml` re-tags the staging digest as the prod semver (ADR-056), so the contract that applies to prod is the one staging validated: the prod lane reads the staging pin (`resolve_image_sha("staging", app)` already returns it), fetches the contract at that commit and renders the prod hostnames from it. Prod stays a human decision: the PR is opened by the workflow, a human merges it.

- **A contract is code that reaches a runner holding a write PAT.** Mitigated by design point 2, and by the receiver running the toolkit from the registry-trusted checkout of kubelab master, never from the product's tree.
- **Short-sha resolution.** The API behaviour for a 7-character ref is to be measured in PR 6 (a spike, with the response recorded in `verification.md`), not assumed. If it does not resolve reliably the tag carries a longer sha or the product's CI sends the full sha as a second payload field (still data, still validated against the tag).
- **Rendering into hand-authored values files** (Q2) means a machine-written key sits beside human-written ones. The drift test compares only the contract-owned keys, and `tests/test_values_version_key_placement.py` already guards the `version` key's position.
- **`web`'s dev stack still reads `common.yaml`** (`infra/ansible/playbooks/deploy-vps.yml:112-117` reads `apps.platform.web.domain` and `default_port`; dev ports differ, 4321 vs 8080). The migration must not delete a key the dev stack reads; the render targets are `staging.yaml` and `prod.yaml` only.
- **Hostname collision.** A contract could name a host another route owns (`grafana.kubelab.live`). The collision check (design point 2) needs the full set of declared hosts, which `tests/test_declared_domains_are_served.py` already enumerates; reuse it rather than writing a second list.
- **Cutover is only provable after merge** (AC4). The live-machine check is named in `verification.md`.

## Decisions

Recorded from the operator's answers of 2026-10-17. The options considered are kept in one line each so the reasoning survives; where the operator's answer covered only part of a question, the rest says so.

**Q1. Where does the registry live?** Decided 2026-10-17: its own file under `infra/config/`, `infra/config/products.yaml`. Rejected: a `products:` key in `common.yaml` (it is flattened into `APPS_*` env vars that reach ConfigMaps, and D8 wants the registry as a standalone toolkit input); one file per product (a mechanical split later if needed).

**Q2. Where does a contract render to?** Decided 2026-10-17: into `apps.platform.<app>` in `values/<env>.yaml`, the same place `promote` writes `version`, through the same ruamel round-trip. Generators and every existing consumer are untouched; the drift test compares only the contract-owned keys. Rejected: a generated per-product layer in `ConfigurationManager` (larger PR, can replace this later without changing the contract); generators reading the snapshot directly.

**Q3. Schema definition.** Decided 2026-10-17: a pydantic model (already a dependency, `^2.14.0`) that generates the JSON Schema, committed and checked for drift; no `jsonschema` dependency. The operator's answer covered the definition; the rest stays as proposed and is not contested: the file lives in the package (`toolkit/schemas/kubelab-product.schema.json`, so D8's pinned install carries it), its `$id` is the public raw URL on `master`, and the contract carries a required integer `schema_version: 1`.

**Q4. Prod lane.** Decided 2026-10-17: option (b). Staging goes through the generic receiver; `promote-prod.yml` stays its own gated workflow and reads the event-to-app map and the app list from the registry (rows 7 and 8), in one small PR. Prod remains a human decision: a human merges the PR. One literal stays: the `|| 'web'` fallback at `promote-prod.yml:56`, because a concurrency group is evaluated before any step can ask the registry; a test asserts the registry has exactly one app with a prod dispatch event, and the fallback goes only when event types encode the app. Rejected: staging only (leaves a literal `web` in a path every product must edit); one receiver for both lanes (different tag rules and gates).

**Q5. Event types.** Decided 2026-10-17: omit `types` under `repository_dispatch`, so the workflow runs for every dispatch and the registry decides. An event type the registry does not know fails the run in red with ERROR / WHY / FIX; a prod-lane event type (`*-release-published`) is skipped as "not this lane". Rejected: a registry-generated `types` list with a drift test (one workflow edit per product); a hand-written list. Cost accepted: every dispatch starts a run, including ones meant for `promote-prod.yml`.

**Q6. Secret names.** Decided 2026-10-17: only names already in `SECRET_CATALOG`; an unknown name is refused. The catalog stays operator-owned, values never travel in the contract, and a product cannot widen the catalog.

**Q7. What pins a product's image repository.** Decided 2026-10-17, and this changes the draft: **the registry has no `image` field**, so ADR-067 D2's list (app, repository, forge, event types) needs no amendment. The image is derived by the rule `<registry>/<owner>/<product>`, with an optional override in the registry entry only where the derived name is wrong. The contract still carries `image` (ADR-067 D2), and the guard in AC6 is that it equals what the platform derives (or the override), so a contract cannot point at another product's image. Two consequences the tasks pin down rather than assume: (1) the platform's own registry value is already `docker.io/mlorentedev` (`REGISTRY` in the merged config), so for the platform's namespace the rule reads `docker.io/mlorentedev/<product>`, and PR 2 fixes the exact reading in a test; (2) `web` needs the override, because its image is `kubelab-web` and the rule yields `docker.io/mlorentedev/web`. The override sits in the registry entry, not in the contract, so a product cannot grant it to itself.

**Q8. WIP limit.** Decided 2026-10-17: the operator granted `--over-wip-limit`. Reason, recorded in `wip_override`: "Operator 2026-10-17: granted over the WIP limit (20 active, limit 10). Archiving one spec would not unblock the gate; burndown tracked in #2443."

## Acceptance criteria

The first four are #1926's own; AC5 is #1815; AC6 and AC7 are the guards the design points require and the issue does not state.

- [ ] **AC1** A product absent from the registry is refused: dispatching an event type the registry does not map fails the run, and a dispatch whose payload names another app (extra `app`, `repo` or `image` fields) changes nothing, because the app is derived from the event type only.
- [ ] **AC2** A contract that fails the schema fails the receiver with an error that carries three labelled parts, ERROR, WHY and FIX, and names the contract path and the failing field.
- [ ] **AC3** A test fails when anything derived from a contract drifts from it: a derived key in `values/<env>.yaml` that no longer equals the render of the committed contract snapshot, a snapshot that no longer validates, or a registry entry with no snapshot (or the reverse). The test runs offline and needs no SOPS key.
- [ ] **AC4** `web` deploys to staging through the generic receiver (a real dispatch opens or updates `deploy/staging-web`), and `web-image-receiver.yml`, its test and its `EXPECTED` entry are deleted.
- [ ] **AC5** (#1815) `PLATFORM_APPS` is no longer a literal; the platform apps come from the registry. `toolkit deployment promote --env staging --app <a registry product other than api/web>` succeeds on a fixture registry, and `--app <unregistered>` fails naming the registry.
- [ ] **AC6** A contract cannot widen the registry: an image repository other than the one derived for the product (or its registry override), a secret name absent from `SECRET_CATALOG`, a hostname another route owns, and `auth: oidc` at render time are each refused with ERROR / WHY / FIX.
- [ ] **AC7** A tag that is not an immutable `sha-<7+ hex>`, or whose short sha does not resolve to exactly one commit on the product repository's default branch, is refused before any file is written.

## References

- Bitácora board: #1926 (see the `issue:` frontmatter field); epic #1931; absorbed #1815; siblings #1927 (IDP-043), #1928 (IDP-044), #400
- ADR: `docs/adr/adr-067-product-contract-and-agent-access.md` (D2, D3, D4, D7, D8); `docs/adr/adr-053-platform-product-repos.md` (§2, §5); `docs/adr/adr-046-gitops-delivery-promotion-strategy.md`; `docs/adr/adr-056-build-once-monorepo-apps.md`
- Shape to mirror for AC3: `tests/test_oidc_clients.py` (SSOT-017), declared once and a committed copy compared field for field without SOPS
- Receivers today: `.github/workflows/web-image-receiver.yml`, `.github/workflows/promote-prod.yml`; their tests `tests/test_web_image_receiver_workflow.py`, `tests/test_promote_prod_dispatch.py`
- Lessons: lesson-430 (`--force-with-lease` on a stable branch), DELIVERY-005 (#1645, one stable branch per app)
