---
tags: [spec, tasks]
created: "2026-11-03"
id: "IDP-053-forge-agnostic-product-path"
type: spec-tasks
status: active
owner: manu
---

# Tasks - IDP-053-forge-agnostic-product-path

> TDD order inside each slice: failing test, then code, then refactor. One slice = one PR.
> **Markers:** `[P]` = no dependency on another unchecked task, safe to run in parallel (the
> slice touches files no other open slice touches). `[AC<n>]` = helps satisfy acceptance
> criterion `<n>` in `proposal.md`.
>
> **Order.** Wave 1 (all parallel, disjoint files): S1a, S3a, S5a, and S2c once the owner has run its D2 consequence check against the live forge (its first task; it cannot start without the owner). Wave 2: S1b and S2a
> (after S1a), S3c (after S3a), S5b (after S5a and the API note), S5c (after S2c, to avoid a
> shared-file conflict), S6a (after S5a). Wave 3: S2b (after S1b and S2a), S3b (after S1, S2,
> S3a, S3c and the product's `kubelab.yaml`), S6b (after S6a, S5b, S5c), S8. Then S4 (after S3b
> merges and an image exists), S7 (D1 deferred to it by the owner), S9 (after #3063).
>
> **Merge owner.** ADR-073 D13: anything under `infra/` or `.github/workflows/`, and every
> secrets PR and mint, is the owner's to merge or run. Slices marked "agent" touch neither and
> may be merged by the agent under the standing grant once CI is green and triage is posted.
>
> **Hard rule for every slice:** none touches `toolkit/features/deploy_shape.py` before S9.

## Setup

- [ ] Branch created from master: `feat/idp-053-<slice>` (one branch per slice)
- [ ] `proposal.md` acceptance criteria are testable (they name commands)
- [x] D1 and D2 are decided before the slices that carry them (owner, 2026-11-05: D1 deferred to S7, D2 the reviewer account)

## Implementation

### S1a. Registry fields and prune exclusion [P] (agent merges, ~90 LOC)

Files: `toolkit/features/product_registry.py`, `toolkit/features/registry.py`,
`infra/config/products.yaml` (schema comment only, no new entry), tests below.

- [x] [P] [AC1] Failing tests in `tests/test_product_registry.py`: `image_registry` and `private`
  parse; `derived_image` returns `<image_registry>/<image_name or app>`; `private` without
  `image_registry` or `pull_credential` is refused with ERROR / WHY / FIX; two private entries on
  one host naming different credentials are refused (D6)
- [x] [AC1] Add `image_registry`, `private`, `pull_credential` (username + catalog key) to `Product`; `derived_image` honours `image_registry`
- [x] [AC1] Failing test in `tests/test_registry_prune.py`: a product whose registry is not
  `platform_registry()` is skipped by `image_repositories`, and
  `test_the_committed_set_is_the_three_kubelab_repositories` still passes
- [x] [AC1] `image_repositories` skips non-default-registry products instead of raising on `/`
- [x] Mutation check on both new guards: `make mutate FILE=toolkit/features/product_registry.py TEST=tests/test_product_registry.py`

Acceptance: `.venv/bin/python -m pytest -q tests/test_product_registry.py tests/test_registry_prune.py`

### S1b. Generator, promote, `tag_exists`, prod-lane guard (agent merges, ~130 LOC)

Depends on S1a. Files: `toolkit/features/generator_k8s.py`, `toolkit/features/promotion.py`,
`toolkit/features/registry.py`, `toolkit/features/product_render.py` (test only: `CONTRACT_KEYS`
is NOT edited, D4).

- [x] [AC2] Failing test: the generated overlay image for a product with `image_registry` is
  `<image_registry>/<name>:<tag>`, and the committed overlays for `web` are byte-identical
  (`make validate-sync ENV=staging` / `ENV=prod` stay clean)
- [x] [AC2] `_build_context` and `_resolve_image` take the registry from the product's entry, falling back to `REGISTRY`
- [x] [AC2] Failing test in `tests/test_product_registry.py`: `"image_registry" not in CONTRACT_KEYS` (D4) (already on master from the previous slice: `test_image_registry_is_not_a_contract_key`)
- [x] [AC2] Failing tests in `tests/test_promotion.py`: `promote --env prod` for a product with no `events.prod` is refused (D5); a prod values block without `version` for a staging-only product fails
- [x] [AC2] Implement the refusal and the committed-test for staging-only products
- [x] [AC2] Failing tests for `tag_exists` on a non-`docker.io` host: 200 is True, 404 is False, 401/403/unreachable is None with a warning naming the registry (D3); injectable HTTP, no network in tests
- [x] [AC2] Implement the OCI `HEAD /v2/<name>/manifests/<tag>` transport
- [x] [AC2] New `tests/test_prod_images_always_on.py`: no prod overlay image points at a forge host (D7)

Acceptance: `make validate-sync ENV=staging && make validate-sync ENV=prod` and
`.venv/bin/python -m pytest -q tests/test_promotion.py tests/test_product_registry.py tests/test_prod_images_always_on.py`

### S2a. dockerconfigjson Secret through `apply-secrets` (owner merges, ~140 LOC)

Depends on S1a. Owner merges because it changes the secret delivery path (D13).
Files: `toolkit/features/k8s_secrets.py`, tests.

- [ ] [AC3] Failing test: `SecretMapping` accepts a `secret_type`; a private entry yields `pull-<host-slug>` of type `kubernetes.io/dockerconfigjson` whose `.dockerconfigjson` decodes to `{"auths": {"<host>": {"username", "password", "auth"}}}`
- [ ] [AC3] `_render_secret_manifest` takes the type (default stays `Opaque`); build the dockerconfigjson from the catalogued token, as a rendered literal (D6)
- [ ] [AC3] Failing test: the token never appears in an argv, a log line or `--dry-run` output (the manifest is redacted the way the existing Secret dry-run is)
- [ ] [AC3] Failing test: `web`'s rendered secrets are unchanged; a registry with no private entry adds no Secret
- [ ] [AC3] Generate the mapping from the registry (no hand-written list entry per product)

Acceptance: `.venv/bin/python -m pytest -q tests/test_image_pull_secret.py tests/test_k8s_secrets_apply.py tests/test_k8s_secrets_delivery.py` (the first is new)

### S2b. `imagePullSecrets` in the Deployment template (owner merges, ~50 LOC)

Depends on S1b and S2a. Files: `infra/k8s/templates/deployments.yaml.j2`,
`toolkit/features/generator_k8s.py`, regenerated overlays (not counted).

- [ ] [AC3] Failing test: a private product's Deployment carries `imagePullSecrets: [{name: pull-<host-slug>}]`; every other Deployment is byte-identical
- [ ] [AC3] Emit the block only when the entry is `private`
- [ ] [AC3] `make validate-sync ENV=staging && make validate-sync ENV=prod` clean

Acceptance: `.venv/bin/python -m pytest -q tests/test_image_pull_secret.py` and the two `validate-sync` runs.

### S2c. Gitea pull token: catalog, mint, `registry-check` [P] (owner merges and mints, ~140 LOC)

First task, before any code: the consequence check for D2, run against the live forge by the
owner (or by the agent with the owner's read-only token if they hand one over). Record the
result on #2612.

- [ ] [AC4] Consequence check (D2): create a throwaway `read:package` token on the reviewer account, pull a manifest for `personal/imagesensortool`, record status. Also pick one package the reviewer account must not read and record its `<owner>/<name>` in `verification.md` as `OUT_OF_SCOPE_PACKAGE`, with the denial status it answers; f4d's negative half uses that value. Fail means go back to the architect (ADR-062/065), and the rest of S2c/S5c wait
- [ ] [AC4] Failing tests in `tests/test_gitea_registry_pull_token.py`, copying the shape of `tests/test_gitea_issue_reader_token.py`: the grant in `token_scopes` equals `read:package` exactly; the mint is gated on the SOPS key being absent; the revoke-then-unset rotation covers it
- [ ] [AC4] Add `registry_pull` to `ROTATABLE_TOKENS` (`gitea_tokens.py`), `SCOPE_BY_METHOD` if a client method is needed (`gitea_client.py`), the catalog entry (`secrets_manager.py`, read from SOPS by `apply-secrets`, no `forge_actions`: that field writes Gitea Actions secrets, not the cluster; file per D2), the `common.yaml` `token_scopes` grant, and the Ansible mint task in `beelink_services`
- [ ] [AC4] Failing test then implement `toolkit services gitea registry-check --app <app> [--package <owner>/<name>] [--expect-denied]`: pulls a manifest by consequence (the app's own package by default, the named one with `--package`), prints status, never the token. Without `--expect-denied` it exits 0 only on 200; with it, 0 only on 401 or 403. An empty `--package` exits non-zero. The tests cover 200, 401/403, another status (500), an empty package, and a denied pull run without the flag
- [ ] [AC4] Owner operation: mint, then `toolkit secrets audit --env staging` and `registry-check` (deployed)

Acceptance: `.venv/bin/python -m pytest -q tests/test_gitea_registry_pull_token.py tests/test_gitea_token_rotation_registry.py tests/test_gitea_token_scopes.py tests/test_gitea_token_scope_drift.py`

### S3a. Optional `hostnames.prod` and staging-only guards [P] (agent merges, ~90 LOC)

Files: `toolkit/features/product_contract.py`, `toolkit/features/product_guards.py`,
`toolkit/features/product_render.py`, `toolkit/schemas/kubelab-product.schema.json`
(regenerated, not counted), tests (see the list in `proposal.md`).

- [x] [P] [AC5] Failing tests: a contract with no `hostnames.prod` validates; `_FIELD_FIX["hostnames"]` text no longer says "exactly staging and prod"; the committed JSON Schema equals the model
- [x] [AC5] Make `Hostnames.prod` optional; regenerate the schema with `python -m toolkit.features.product_contract --write-schema`
- [x] [AC5] Failing tests: `_check_hostnames` loops only the envs the registry entry's `events` declares; `product render --env prod` for a staging-only product is refused with ERROR / WHY / FIX
- [x] [AC5] Implement; `CONTRACT_KEYS` derivation for `domain`, `site_domain`, `site_url` does not read an absent env
- [x] [AC5] Failing tests in the six red tests named in `proposal.md`: a staging-only fixture needs no prod tile, no prod snapshot, no prod e2e expectation and no prod DNS record; `test_dns_contract_hostnames.py` gets a case pinning the existing skip
- [x] [AC5] Make `test_platform_tiles_cover_registry`, `test_e2e_expectations_cover_registry` and `test_product_registry` loop the envs the entry declares

Acceptance: `.venv/bin/python -m pytest -q tests/test_product_contract.py tests/test_product_contract_schema.py tests/test_product_contract_drift.py tests/test_product_contract_guards.py tests/test_dns_contract_hostnames.py tests/test_platform_tiles_cover_registry.py tests/test_e2e_expectations_cover_registry.py tests/test_product_registry.py`

### S3c. A product's staging zone is a declaration (owner merges, `infra/`, ~120 LOC)

Depends on S3a (both touch `product_render.py`'s hostname checks). Implements D8. Files:
`toolkit/features/product_render.py` (or `product_guards.py`, wherever S3a leaves
`_check_hostnames`), `toolkit/features/k8s_render.py` (the render step that already fills
`RESOLVE_RPI4_TAILSCALE_IP` in `coredns-custom.yaml`), `infra/k8s/base/edge/coredns-custom.yaml`
(the staging server blocks become one templated block over `networking.staging_zones`; the
prod rewrite blocks stay hand-written until a product declares prod),
`docs/adr/adr-067-product-contract-and-agent-access.md` (amendment), tests.

- [ ] [P] [AC13] Failing tests in `tests/test_product_staging_hostname.py` (new): `web` passes; staging-only `staging.imagesensortool.com` passes with its zone in `networking.staging_zones`; the same name with the zone missing is refused, naming the line to add; `beta.imagesensortool.com` is refused; `<label>.staging.kubelab.live` passes; a product declaring `hostnames.prod: x.dev` with `hostnames.staging: staging.y.dev` is refused even when both zones are listed
- [ ] [AC13] Implement the check at render time (the contract model cannot read `common.yaml`, so the contract schema does not change)
- [ ] [P] [AC13] Failing tests in `tests/test_coredns_hairpin_zones.py` (new): the rendered staging blocks equal today's two blocks byte for byte; a third zone in a fixture `staging_zones` yields a third `forward` block; a zone that is not a lowercase FQDN is refused
- [ ] [AC13] Implement the templated block; `tests/test_coredns_hairpin_answer.py` stays green
- [ ] [AC13] ADR-067 amendment: the D8 convention, the wildcard exception, `web` already conforming, and the note that ADR-073 D8 replaces it with the domain registry on acceptance
- [ ] Ticket, not code: derive the ACME token's zones (`kubelab-acme-dns`, #2459) from `zones.json` in Terraform, so a new domain needs no Cloudflare UI step (proposal risk 7)

Acceptance: `.venv/bin/python -m pytest -q tests/test_product_staging_hostname.py tests/test_coredns_hairpin_zones.py tests/test_coredns_hairpin_answer.py`, each new boundary test mutation-checked.

### S3b. Onboarding PR for `imagesensortool` (owner merges, ~70 LOC plus data)

Blocked until `personal/imagesensortool` commits a valid `kubelab.yaml` (image, port 8080,
`/healthz`, `hostnames.staging`, auth level) and its CI has pushed one `sha-<12hex>` image.
Depends on S1, S2, S3a and S3c merged. `hostnames.staging` is `staging.imagesensortool.com`
(D8). Files: `infra/config/products.yaml`,
`infra/config/products/contracts/imagesensortool.yaml`, `infra/config/values/staging.yaml`
(staging-only block, `version` set), the platform tile file, the e2e expectation file,
regenerated overlays, and one line in `infra/config/values/common.yaml`
(`networking.staging_zones`: `staging.imagesensortool.com`); the hairpin block follows from
S3c.

- [ ] [AC6] Registry entry: `forge: gitea`, `repository: personal/imagesensortool`, `receiver: generic` (dormant until S6b and S7; proposal risk 3), `image_registry: gitea.kubelab.live/personal`, `private: true`, `pull_credential`, `events: {staging: ...}` and no `events.prod`
- [ ] [AC6] Snapshot: `toolkit product render --contract ... --env staging` and commit the snapshot
- [ ] [AC6] Staging values block with a pinned `version` (never `:latest`), platform tile, e2e expectation, and the staging zone line
- [ ] [AC6] `make test`, `make validate-sync ENV=staging`, `product render --check` exit 0
- [ ] Owner widens the ACME token (`kubelab-acme-dns`) to `imagesensortool.com` in Cloudflare, provisions the staging zone (VPS, RPi4), and confirms with `toolkit secrets acme-token-scope` (see "What cannot be verified")

### S4. First deploy by hand (owner, ~80 LOC of runbook)

- [ ] [AC7] Owner mints the pull token (S2c) and runs `apply-secrets` for staging
- [ ] [AC7] `toolkit deployment promote imagesensortool --env staging --version sha-<12hex>`; deploy PR opened and merged by the owner
- [ ] [AC7] Run the three commands in AC7 and record the output in `verification.md`
- [ ] [AC7] Runbook: `docs/runbooks/cicd.md` gains the Gitea product path (hand-run promote, on-demand node note, how to read a pull failure)

### S5a. Forge adapter, GitHub implementation [P] (agent merges, ~200 LOC)

Files: new `toolkit/features/forge_adapter.py`, `toolkit/features/product_ready.py`,
`toolkit/features/product_release.py`, `toolkit/cli/product.py` (new `product resolve`),
tests.

- [x] [P] [AC8] Failing tests in `tests/test_forge_adapter.py`: a `ForgeAdapter` protocol with `resolve_commit(short)`, `is_on_default_branch(sha)`, `read_file(path, ref)`, `resolve_tag(tag)`; the GitHub implementation maps each to the `gh api` call the receiver and `product_release` make today (injectable runner, no network)
- [x] [AC8] Implement `forge_adapter.py` with the GitHub implementation and a factory keyed on the registry entry's `forge`
- [x] [AC8] Move the `forge != github` refusals in `product_ready.py:58` and `product_release.py:52` behind the factory (an unsupported forge is refused by the factory, not by string compare)
- [x] [AC8] `toolkit product resolve --app --tag` prints the resolved commit and on-default-branch verdict
- [x] [AC8] New `tests/test_no_forge_names_outside_adapter.py`: no module outside `forge_adapter.py` compares `forge` to a forge name; `deploy_shape.py` is allow-listed with a comment pointing at S9

Acceptance: `.venv/bin/python -m pytest -q tests/test_forge_adapter.py tests/test_no_forge_names_outside_adapter.py tests/test_product_release.py tests/test_product_ready.py`

### S5b. Gitea implementation (agent merges, ~170 LOC)

Depends on S5a and the API note. Files: `toolkit/features/forge_adapter.py`,
`toolkit/features/gitea_client.py` (new read methods plus their `SCOPE_BY_METHOD` entries),
`docs/lessons/` or the spec's `verification.md` (the note).

- [ ] [AC8] API note first: run a local Gitea 1.27.3 (as `scope-lab.py` does) and record, for each adapter method, the endpoint, the status codes and the edge cases (unknown vs ambiguous short sha, `compare` direction, raw at a commit, annotated tag). Commit it before code
- [ ] [AC8] Failing tests with recorded responses: each of the four methods on the Gitea implementation; unknown and ambiguous short sha are told apart; a missing file is an error with ERROR / WHY / FIX
- [ ] [AC8] Implement on `GiteaClient`; each new method is mapped in `SCOPE_BY_METHOD` and the test that pins the method-to-scope map passes with `read:repository` only
- [ ] [AC8] The factory selects the Gitea implementation for `forge: gitea`

Acceptance: `.venv/bin/python -m pytest -q tests/test_forge_adapter.py tests/test_gitea_token_scopes.py tests/test_gitea_token_scope_drift.py`

### S5c. Read-only Gitea token for repository reads [P] (owner merges and mints, ~100 LOC)

Sequence after S2c (shares `gitea_tokens.py`, `common.yaml`, the Ansible task file). Depends on D2.

- [ ] [AC8] Failing tests in `tests/test_gitea_repo_reader_token.py` (shape of the issue_reader test): grant equals `read:repository`, mint gated on absence, rotation covers it
- [ ] [AC8] `repo_reader` in `ROTATABLE_TOKENS`, catalog entry in SOPS (no `forge_actions`: it reaches Gitea repositories only, not `mlorentedev/kubelab` on GitHub), `token_scopes` grant, Ansible mint; the owner sets the kubelab GitHub Actions secret by hand (proposal, "What cannot be verified from a diff")
- [ ] [AC8] Owner mints; the receiver's `resolve` job reads it as a secret

Acceptance: `.venv/bin/python -m pytest -q tests/test_gitea_repo_reader_token.py tests/test_gitea_token_rotation_registry.py tests/test_gitea_token_scopes.py`

### S6a. Receiver logic as toolkit commands (agent merges, ~150 LOC)

Depends on S5a. Moves the workflow's inline `gh api` shell into testable commands without
changing the workflow's behaviour (the workflow edit itself is S6b). Files:
`toolkit/cli/product.py`, `toolkit/features/product_receiver.py` (new), tests.

- [ ] [AC9] Failing tests: `product resolve` returns the same JSON the workflow's resolve step builds today for a GitHub fixture
- [ ] [AC9] `toolkit product fetch-contract --app --sha` reads `kubelab.yaml` at the commit through the adapter and writes it
- [ ] [AC9] Failing test then implement `toolkit product route --app` printing `{forge, runs_on}` from `products.yaml` only (GitHub keeps `vars.RUNNER_DOCKER`'s ubuntu default, Gitea selects the self-hosted label)

Acceptance: `.venv/bin/python -m pytest -q tests/test_product_receiver.py tests/test_forge_adapter.py`

### S6b. Receiver workflow: `route` job and per-forge runner (owner merges, ~120 LOC)

Depends on S6a, S5b, S5c. Held, not merged, until #2611 settles (proposal risk 3); AC9's dry run gates its merge. Files:
`.github/workflows/product-image-receiver.yml`, `tests/test_product_image_receiver_workflow.py`,
`tests/test_receiver_pr_step.py`.

- [ ] [AC9] Failing workflow tests: a `route` job exists, reads `products.yaml` only and has no secret; `resolve` `runs-on` comes from its output; `promote` stays on a hosted runner (Risks 4); no `forge != github` step remains; the GitHub path's jobs run on the runners they run on today
- [ ] [AC9] Edit the workflow to match; resolve calls `toolkit product resolve` and `fetch-contract` only
- [ ] [AC9] `actionlint` clean
- [ ] [AC9] `workflow_dispatch` dry run on the self-hosted runner for the Gitea product (deployed)

Acceptance: `.venv/bin/python -m pytest -q tests/test_product_image_receiver_workflow.py tests/test_receiver_pr_step.py && actionlint`

### S7. Trigger (owner decides D1; implementation per option)

- [ ] [AC10] D1 was deferred to S7 (owner, 2026-11-05); at S7's start the owner picks (a) or (b), the choice is commented on #2612 and the loser's reason recorded
- [ ] [AC10] Option (a): `forge_actions` catalog entry for the dispatch token (`personal/imagesensortool` target), the product CI step that fires `repository_dispatch` with `{tag}`, a runbook paragraph in `docs/runbooks/cicd.md`; spike first: the minimum token permission
- [ ] [AC10] Option (b): a separate spec (Go API outbound dispatch plus Gitea webhook registration); out of this one's size budget

### S8. Prod half: authenticated, forge-neutral `release-contract` and digest (agent merges the code; the credential is owner, ~200 LOC)

Depends on S5b and S1b. Closes #2627 AC1 and AC2. Files: `toolkit/features/product_release.py`,
`toolkit/features/registry.py`, tests.

- [ ] [AC11] Failing tests in `tests/test_registry_digest.py` (new): authenticated manifest digest read for GHCR and for the Gitea registry; unsupported or private registry without a credential is refused with ERROR / WHY / FIX naming the registry
- [ ] [AC11] Implement `tag_digest` for non-`docker.io` hosts using the catalogued pull credential (D3's authenticated half)
- [ ] [AC11] Failing test then implement: `release-contract` reads the contract through the adapter for any forge; a 7-hex and a 10-hex `sha-` tag are both proven, so a check fixed at 7 fails (#2627 AC1)

Acceptance: `.venv/bin/python -m pytest -q tests/test_product_release.py tests/test_registry_digest.py`

### S9. `deploy_shape` provenance through the adapter (owner merges, after #3063, ~80 LOC)

- [ ] [AC12] Failing test: a Gitea product's deploy PR is `mechanical` when provenance proves against Gitea, and `not-mechanical` with an ERROR / WHY / FIX when it does not
- [ ] [AC12] Replace `_provenance`'s `gh api` calls and the `forge == "github"` branch with the adapter; remove the allow-list entry in `test_no_forge_names_outside_adapter.py`

Acceptance: `.venv/bin/python -m pytest -q tests/test_deploy_shape.py tests/test_deploy_shape_widening.py tests/test_no_forge_names_outside_adapter.py`

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test or a recorded deployed check
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Type checks pass (`make lint`)
- [ ] No unrelated changes in any slice's diff
- [ ] `verification.md` filled in, including the deployed checks
- [ ] Each slice PR references this spec folder and carries a `## Knowledge` section
- [ ] An independent adversarial review before archive (the reviewer is not the implementer)

## Machine-readable features

`features.json` (alongside this file) follows [[pattern-feature-list-as-primitive]]: one entry
per acceptance criterion, `state` starts `pending`, and only the harness sets `passing` after
running `verification` and capturing exit code 0. Entries for deployed criteria carry the
command that is run on the machine after the owner's operation; until then they fail by design.
