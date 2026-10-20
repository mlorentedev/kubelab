---
tags: [spec, tasks, idp, product-contract]
created: "2026-10-17"
---

# Tasks - IDP-042-product-contract-registry

> The operator decided Q1-Q8 on 2026-10-17 (see "Decisions" in `proposal.md`); the tasks below follow those decisions.
>
> TDD order. One task = one focused commit. Eight PRs, each at most about 300 lines of diff, each independently reviewable and each leaving master green with the old receiver still working until PR 7. Tests run through the repo's pytest wrapper (`poetry run pytest <file> --no-cov -q`), and `make test-fast` before opening a PR.
>
> **Inline markers**
> - `[P]` — no dependency on another unchecked task.
> - `[AC<n>]` — serves acceptance criterion `<n>` of `proposal.md`.

## Setup

- [x] Operator answers Q1-Q8 in `proposal.md` (Q8: the WIP override for this spec, recorded as `wip_override`)
- [ ] `/spec check IDP-042-product-contract-registry` returns PASS
- [x] Branch for PR 1 created from master: `feat/idp-042-contract-schema` (worktree outside the repo, `make worktree-init` run once)
- [x] `proposal.md` carries no `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tag

## Implementation

### Dependency graph

```
PR 1 schema ──┬──> PR 3 render + drift ──┬──> PR 6 receiver ──> PR 7 cutover ──> PR 8 delete
PR 2 registry ┼──> PR 4 guards ──────────┘          ^
              └──> PR 5 prod lane / Makefile / prune │
                                       web repo adds kubelab.yaml (external, before PR 7)
```

PR 1 and PR 2 are independent and can be written in parallel. PR 5 may land at any point after PR 2.

### PR 1 — Contract schema and validator (about 250 lines, pure addition)

Branch `feat/idp-042-contract-schema`. Commit prefix `feat(toolkit):`.

- [x] [AC2] Failing test `tests/test_product_contract.py`: a valid contract (web's, hand-written from `values/staging.yaml:44-54` and `common.yaml:949-960`) validates; each of these is refused, naming the field: unknown top-level key, port `0` and `70000`, a hostname with a scheme or uppercase, a health path without a leading `/`, `auth: admin`, `schema_version` absent or `2`, a secret name with a space, and a contract that carries `repository`, `repo`, `source` or `remote` (refused as unknown keys, with a message that says the repository comes from the registry). Run: `poetry run pytest tests/test_product_contract.py --no-cov -q`. Expected: FAIL, `ModuleNotFoundError: toolkit.features.product_contract`
- [x] [AC2] Failing test, same file: a refusal renders three labelled lines `ERROR:`, `WHY:`, `FIX:`, and `ERROR` names the contract path and field. Expected: FAIL
- [x] [AC2] `toolkit/features/product_contract.py`: pydantic model (`extra="forbid"`, anchored patterns), `validate_contract(path) -> Contract`, `ContractError(error, why, fix)`. Run the file's tests. Expected: PASS
- [x] [AC2] [P] Failing then passing test `tests/test_product_contract_schema.py`: `toolkit/schemas/kubelab-product.schema.json` equals `Contract.model_json_schema()` serialised with sorted keys, and carries `$id`. Generate the file with `poetry run python -m toolkit.features.product_contract --write-schema`. Expected: FAIL (file absent), then PASS
- [x] [AC2] `toolkit/cli/product.py`: `toolkit product validate --contract PATH [--json]`, exit 1 with the three-line error (or a JSON object with `error`, `why`, `fix`). Wire it into the CLI entry. Test with `typer.testing.CliRunner` for exit code and JSON shape. Expected: PASS
- [x] Offline check: `poetry run toolkit product validate --contract tests/fixtures/product/web.kubelab.yaml --json` prints `{"ok": true, ...}` and exits 0; no SOPS key, no network

### PR 2 — Registry and `PLATFORM_APPS` derived from it (about 280 lines; this is #1815)

Branch `feat/idp-042-product-registry`. Commit prefix `feat(toolkit):`.

- [x] [AC1] Failing test `tests/test_product_registry.py` against a fixture registry (`tests/fixtures/product/registry.yaml`, three products: `api` in-tree, `web` on GitHub, `third` on GitHub): `platform_apps()` returns the three names in registry order; `app_for_event("web-image-published")` is `web`; an unmapped event type raises `UnknownEventError`; an entry whose event type is claimed by two apps fails the load. Expected: FAIL, module absent
- [x] [AC1] `toolkit/features/product_registry.py`: `load_registry(path)`, cached `platform_apps()`, `app_for_event()`. Entry fields: `repository`, `forge` (`github` | `gitea` | `in-tree`), `events` (`staging`, `prod`), `receiver` (`legacy` | `generic`). `infra/config/products.yaml` (Q1) holds `api` and `web`. Optional `image_name` override (Q7), set for `web` (`kubelab-web`) and absent otherwise; there is no required `image` field. Expected: PASS
- [x] [AC6] Failing test in `tests/test_product_registry.py`: `derived_image("third")` is `<registry>/third` under the platform namespace (the exact reading of `<registry>/<owner>/<product>` against `REGISTRY=docker.io/mlorentedev` is fixed here), and `derived_image("web")` is `docker.io/mlorentedev/kubelab-web` because of the override. Then `derived_image()` in `product_registry.py`. Expected: FAIL, then PASS
- [x] [AC5] Failing test in `tests/test_promotion.py`: with the fixture registry, `promote("staging", "third", "sha-abc1234")` writes `apps.platform.third.version` and regenerates; `promote("staging", "ghost", ...)` raises `ValueError` whose message names the registry file. Expected: FAIL (the tuple refuses `third`)
- [x] [AC5] Replace the consumers with `platform_apps()`: `toolkit/features/promotion.py:63` and `:191`, `toolkit/features/generator_k8s.py:224`, `toolkit/features/generator_traefik.py:189`, `toolkit/features/generator_authelia.py:44` (via the `APPS` alias), `tests/test_k8s_generator_secrets.py:41`. Delete the literal `PLATFORM_APPS` at `toolkit/config/constants.py:48` and the alias at `:77-78` (keep `EDGE`). Expected: `make test-fast` PASS, and `git grep -n 'PLATFORM_APPS' -- toolkit tests` returns only the removal comment
- [x] [AC5] Regression guard: generate both overlays before and after and diff them. Expected: `diff -r` empty for `infra/k8s/overlays/{staging,prod}/generated` (the registry lists `api` and `web`, so output must not change)
- [x] [AC5] Update the `--app` help in `toolkit/cli/deployment.py:25,33,48` to say "a registered product (see infra/config/products.yaml), or errors"

### PR 3 — Render, snapshot and the drift test (about 300 lines)

Branch `feat/idp-042-contract-render`. Commit prefix `feat(toolkit):`. Depends on PR 1 and PR 2. Render targets follow Q2: `apps.platform.<app>` in `values/staging.yaml` and `values/prod.yaml`, the place `promote` writes.

- [x] [AC3] Commit the web contract snapshot `infra/config/products/contracts/web.yaml` with values copied from the current staging and prod blocks. Failing test `tests/test_product_contract_drift.py`: render the snapshot for each env and compare the contract-owned keys (`default_port`, `health_path`, `domain`, `enable_auth`, `auth_level`, image name) with `values/<env>.yaml` merged over `common.yaml`. Expected: FAIL on the first run if any key differs today. Every difference found is a finding to record in `verification.md`, not to paper over
- [x] [AC3] Failing test in `tests/test_product_contract_drift.py`: the comparison returns the number of contract-owned keys it checked per env and the test asserts it equals the size of the schema-to-values mapping (not merely `> 0`), and a run over an empty mapping fails. Expected: FAIL, then PASS with the count printed (`compared N contract-owned keys for web/staging`)
- [x] [AC3] Failing test, same file: the snapshot-completeness check covers contract-managed entries only; with the fixture registry (`api` in-tree, `web` and `third` on GitHub) `api` without a snapshot passes, `third` without a snapshot fails, and the exempt set is asserted to equal the `in-tree` entries exactly. Expected: FAIL, then PASS
- [x] [AC3] `toolkit/features/product_render.py` and `toolkit product render --contract PATH --env ENV [--check | --write]`. `--check` exits 1 on drift and prints the keys. `--write` edits through the same ruamel round-trip `promotion._load_values_doc` uses and never touches `version`. Expected: drift test PASS
- [x] [AC3] Failing then passing tests in the same file for the three drift directions: a derived key edited by hand, a snapshot edited so it no longer validates, a registry entry with no snapshot (and a snapshot with no entry). Each is run as a mutation with `make mutate FILE=<path> FROM=<text> TO=<text> TEST=tests/test_product_contract_drift.py` on a clean tree. Expected: each goes red
- [x] [AC3] The test uses no SOPS key and no network: `poetry run pytest tests/test_product_contract_drift.py --no-cov -q` with `SOPS_AGE_KEY_FILE` unset. Expected: PASS
- [x] `auth: oidc` makes `render` exit 1 (design point 5); the message is written in PR 4's format, so only the refusal itself is added here

### PR 4 — The contract cannot widen the registry (about 220 lines)

Branch `feat/idp-042-contract-guards`. Commit prefix `feat(toolkit):`. Depends on PR 1 and PR 2.

- [x] [AC6] Failing tests `tests/test_product_contract_guards.py`, one per refusal, each asserting ERROR / WHY / FIX: the contract's `image` differs from `derived_image(app)` (Q7); a secret name absent from `SECRET_CATALOG` (Q6); a contract that names a repository (`repository`, `repo`, `source`, `remote`), which must be refused even when the value equals the registry's own, since the contract is not where the repository comes from; a hostname that another declared route owns (use the enumeration in `tests/test_declared_domains_are_served.py`); `auth: oidc` at render. Expected: FAIL
- [x] [AC6] `toolkit/features/product_guards.py` and `--registry` on `toolkit product validate`; reuse the existing host enumeration instead of writing a second list. Expected: PASS
- [x] [AC6] One positive test: web's real contract passes every guard against the real registry and the real catalog. Expected: PASS
- [x] [AC6] Failing then passing test: every `key_path` in `SECRET_CATALOG`, including the ones built per node (`access_key_path(node)` and siblings), matches the contract's secret-name pattern (`_SECRET_NAME` in `product_contract.py`, PR 1), so a real catalog key can never fail the schema before the catalog check sees it. Expected: PASS, or the pattern widens in the same commit

### PR 5 — The remaining literals read the registry (about 120 lines)

Branch `feat/idp-042-literals-from-registry`. Commit prefix `feat(toolkit):`. Depends on PR 2.

- [x] [AC5] (Q4 b) Extend `tests/test_promote_prod_dispatch.py` so the event-to-app map and the `inputs.app` options are asserted against the registry, then make `promote-prod.yml` resolve the app with `toolkit product app-for-event` (lines 34-35, 42, 93, 101-104 lose their literals; the `|| 'web'` at line 56 stays, because the concurrency group is evaluated before any step can call the toolkit, and a test asserts the registry has exactly one app with a prod dispatch event so the fallback cannot go stale silently). Keep the "app comes from the event type" and "payload never interpolated" tests unchanged and green. 
- [x] [AC5] `toolkit product list --json` and `toolkit product app-for-event EVENT` (thin adapters over `product_registry`, test with `CliRunner`); the next two items and the first one use them
- [x] [AC5] [P] `Makefile:969,971`: derive the allowed `APP` values from `toolkit product list --json`; test with the existing `GH`-overridable harness in `tests/` for `promote-prod` (an unregistered `APP` exits 2)
- [x] [AC5] [P] `toolkit/cli/registry.py:23`: the default `--apps` becomes the registry's apps plus `errors`; `tests/test_registry_prune.py` gains a case for a third product
- [x] Record in the PR body the `ci-pipeline.yml:196-218` leftover question; file a ticket if no caller passes `app: web`

### PR 6 — The generic receiver, dormant for web (about 300 lines)

Branch `feat/idp-042-product-receiver`. Commit prefix `feat(ci):`. Depends on PR 3, PR 4 and PR 2. `web` is `receiver: legacy` in the registry, so this workflow ignores `web-image-published` and the old receiver stays the only one that acts.

- [x] Spike, result recorded in `verification.md`: does `GET /repos/{repository}/commits/{7-hex}` resolve a short sha on the product repo, and what does it return for an ambiguous or unknown one? Measure against `mlorentedev/web` with a real `sha-` tag from `values/staging.yaml:54`
- [x] [AC7] Failing test `tests/test_product_image_receiver_workflow.py`, mirroring `tests/test_web_image_receiver_workflow.py`: it executes the shipped resolve step with `gh` stubbed. Cases: a non-`sha-<7+ hex>` tag exits non-zero before any file is written; a short sha the stub resolves to zero or two commits exits non-zero; a commit not on the default branch (`compare` status `diverged` or `ahead`) exits non-zero. Every recorded `gh api` call that fetches a commit or the contract targets `repos/<registry repository>/`; a contract body that names another repository changes none of them. Expected: FAIL, workflow absent
- [x] [AC1] Same file, failing test: an unknown event type exits non-zero with ERROR / WHY / FIX; a `*-release-published` event is skipped as "not this lane" (exit 0); `client_payload.app` is never read (copy `test_the_app_is_never_taken_from_the_payload`); no step interpolates `client_payload` into a script (copy `test_no_step_interpolates_the_payload_into_its_shell`); a `receiver: legacy` app is skipped with a notice. Expected: FAIL
- [x] [AC1][AC7] `.github/workflows/product-image-receiver.yml`: `on.repository_dispatch` without `types` (Q5) plus `workflow_dispatch` inputs `app`, `tag`, `dry_run`; `concurrency.group: product-receiver-${{ github.event.action }}` (superseded: two jobs, the group is per app on `needs.resolve.outputs.app`; see `verification.md` Decisions) (verify that `github.event.action` carries the event type on a `repository_dispatch` in the spike, since the group is evaluated before any step); steps: checkout kubelab master with `RELEASE_PLEASE_TOKEN`, install toolkit, resolve (registry, tag, commit), fetch the contract with `gh api` at the commit, `toolkit product validate --registry`, `toolkit product render --write`, `toolkit deployment promote`, then the stable-branch PR step copied from `web-image-receiver.yml:78-163` with `BRANCH="deploy/staging-${APP}"`. Every value reaches a script through `env:`. Expected: the two test groups above PASS
- [x] [AC2] The fetch step writes the snapshot `infra/config/products/contracts/${APP}.yaml` and `git add`s it with the values and overlay; a contract that fails validation exits non-zero with the three-line error on the run page. Covered by the stubbed-`gh` test with an invalid contract body
- [x] [AC4] `tests/test_delivery_health.py:46-52`: add `product-image-receiver.yml` to `EXPECTED` (a single-route lane, mutate it to prove the set goes red, per the comment at `:68-75`). `web-image-receiver.yml` stays in the set until PR 8
- [ ] Deferred to PR 7's prerequisites (2026-10-19: `gh api repos/mlorentedev/web/contents/kubelab.yaml` answers 404, and a `workflow_dispatch` only reaches a workflow on the default branch, so the run cannot happen before this PR merges). Dry run: `gh workflow run product-image-receiver.yml --repo mlorentedev/kubelab -f app=web -f tag=<current staging sha> -f dry_run=true`; the run validates and renders and pushes nothing. This needs the web contract; if it does not exist yet, the dry run is deferred to PR 7's prerequisites

### External dependency — the web repository adds `kubelab.yaml` (not in this repo)

- [ ] Owner: the operator or the web session. A PR in `mlorentedev/web` adds `kubelab.yaml` at the repo root, equal to `infra/config/products/contracts/web.yaml`, and confirms its CI still sends `web-image-published` with only `tag` in the payload. It must be merged to web's default branch and be present at the commit of the sha currently pinned in staging, or the first generic dispatch fails at fetch (a safe failure, but staging stalls)
- [ ] Record the web PR URL in `verification.md`

### PR 7 — Cutover: web runs on the generic receiver (about 150 lines, draft until the web PR merges)

Branch `feat/idp-042-web-cutover`. Commit prefix `feat(ci):`. Depends on PR 6 and the external dependency above. Two files change atomically so the two receivers never both act on the event (design point 10).

- [ ] [AC4] Gate before the flag flips. Failing test `tests/test_product_ready.py` (with `gh` stubbed): `toolkit product ready --app web --json` resolves the staging pin (`resolve_image_sha("staging", "web")`), fetches `kubelab.yaml` at that commit from the registry's repository, validates it, and exits non-zero with ERROR / WHY / FIX when the file is absent at that commit or invalid. Expected: FAIL (command absent), then PASS. PR 7 stays a draft until the web PR is merged, and its body carries the real output of `poetry run toolkit product ready --app web --json` run against the live repository, exit 0. `gh pr ready` is the last step, so the flag cannot flip before the contract exists at the pinned commit
- [ ] [AC4] Failing test in `tests/test_product_image_receiver_workflow.py`: with `web` set to `receiver: generic`, the resolve step proceeds for `web-image-published`; and `tests/test_web_image_receiver_workflow.py` asserts the old workflow no longer has a `repository_dispatch` trigger (only `workflow_dispatch`, kept for rollback). Expected: FAIL
- [ ] [AC4] `infra/config/products.yaml`: `web.receiver: generic`. `web-image-receiver.yml`: replace the `repository_dispatch` trigger with `workflow_dispatch` only. Expected: PASS
- [ ] [AC4] Rollback is `git revert` of this single PR: it restores the legacy trigger and the flag in one step. Write that into the PR body
- [ ] After merge, prove it on the deployed machine (not provable from the diff): push a trivial commit to `mlorentedev/web`, then `gh run list --repo mlorentedev/kubelab --workflow product-image-receiver.yml --limit 3` shows a `success` run for the dispatch, `gh api repos/mlorentedev/kubelab/pulls?state=open --jq '.[] | select(.head.ref=="deploy/staging-web") | .title'` shows the new sha, and `gh run list --workflow web-image-receiver.yml --limit 3` shows no run for that dispatch. Paste the three outputs into `verification.md`

### PR 8 — Delete the old receiver (about 200 lines of deletion)

Branch `chore/idp-042-delete-web-receiver`. Commit prefix `chore(ci):`. Only after PR 7's live proof is recorded.

- [ ] [AC4] Delete `.github/workflows/web-image-receiver.yml` and `tests/test_web_image_receiver_workflow.py`; remove `web-image-receiver.yml` from `EXPECTED` in `tests/test_delivery_health.py:46-52`. Run `make test-fast`. Expected: PASS, and `git grep -n 'web-image-receiver' -- . ':!specs' ':!docs/lessons'` returns nothing but historical comments
- [ ] Before deleting `tests/test_web_image_receiver_workflow.py`, port its stable-branch PR-step tests (lookup before push, PATCH versus POST, `--force` on one branch per app) to `tests/test_product_image_receiver_workflow.py` against the `open-pr` step: PR 6 copied that step but tests only its branch name
- [ ] Update `docs/runbooks/cicd.md:39,91,203,222` to the generic receiver and the onboarding recipe (contract + registry entry + the product's dispatch step)
- [ ] Confirm `docs/adr/adr-053-platform-product-repos.md` §2 already carries its "Amended by ADR-067" note (ADR-067 promised it) and say in the PR that the generic receiver now exists; update the `CLAUDE.md` bullets that name `web-image-receiver`
- [ ] File follow-up tickets with their root cause: DNS from contract hostnames (row 12), e2e expectations from the contract, OIDC client rendering, `platform_manifest.py:863`, the `ci-pipeline.yml` leftover if confirmed

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test (AC4 additionally by the live check in PR 7)
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep); `toolkit/features/oidc_clients.py` and `toolkit/features/credentials.py` untouched
- [ ] `verification.md` filled in, including the spike result and the three post-cutover outputs
- [ ] Independent adversarial review (`dotf spec review`) by a session that is not the implementer, before archive
- [ ] PR opened referencing this spec folder; `## Knowledge` section filled in each PR

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to at least one feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"`; only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.
