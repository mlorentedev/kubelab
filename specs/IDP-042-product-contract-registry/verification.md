---
tags: [spec, verification, idp, product-contract]
created: "2026-10-17"
---

# Verification - IDP-042-product-contract-registry

> Every row below is a command that proves the criterion by its consequence. `<hash>` and outputs are filled in as each PR lands. AC4 and the receiver half of AC1 are properties of the deployed machine, not of a diff; they are marked **live** and carry the command that settles them afterwards.

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof.

- [ ] **AC1** A product absent from the registry is refused; a payload naming another app changes nothing
  - Offline, PR 2 and PR 6: `poetry run pytest tests/test_product_registry.py tests/test_product_image_receiver_workflow.py --no-cov -q`. The receiver test executes the shipped resolve step with `gh` stubbed and asserts: an unmapped event type exits non-zero with ERROR / WHY / FIX; a payload carrying `app`, `repo` or `image` produces the same branch, the same files and the same app as one carrying only `tag`; `client_payload.app` appears nowhere in the workflow text; no step interpolates `client_payload` into a script
  - **Live**, after PR 7: dispatch an event type that no registry entry maps (`gh api repos/mlorentedev/kubelab/dispatches -f event_type=ghost-image-published -f 'client_payload[tag]=sha-0000000'`, run by the operator, who holds the dispatch token) and then `gh run list --repo mlorentedev/kubelab --workflow product-image-receiver.yml --limit 1 --json conclusion,displayTitle`. Expected: `failure`, and `git status`/`gh pr list` show nothing opened
- [x] **AC2** A contract that fails the schema fails the receiver with ERROR / WHY / FIX
  - PR 1: `poetry run pytest tests/test_product_contract.py tests/test_product_contract_schema.py --no-cov -q`; every refusal case asserts the three labelled lines and the field name
  - PR 6: the stubbed-`gh` receiver test feeds an invalid contract body and asserts non-zero exit and the three lines in the step output
  - By hand, offline: `poetry run toolkit product validate --contract tests/fixtures/product/invalid-port.kubelab.yaml --json; echo "exit=$?"`. Expected: JSON with `error`, `why`, `fix`, `exit=1`
  - Run 2026-10-21 on master `d7a0d8db`. The fixture did not exist until the closeout review found that, and it is now committed (`port: 70000`). Output: `{"ok": false, "error": "tests/fixtures/product/invalid-port.kubelab.yaml: field 'port': Input should be less than or equal to 65535", "why": "the value does not meet the constraint the schema declares for this field.", "fix": "set port to the container's listening port, an integer from 1 to 65535 (not quoted). Schema: ..."}`, `exit=1`
- [x] **AC3** A test fails if anything derived from a contract drifts from it
  - `env -u SOPS_AGE_KEY_FILE poetry run pytest tests/test_product_contract_drift.py --no-cov -q`. Expected: PASS, offline
  - Not vacuous: the test prints `compared N contract-owned keys for web/<env>` and asserts N equals the size of the schema-to-values mapping; one more mutation empties the mapping (`make mutate FILE=toolkit/features/product_render.py FROM=<the mapping entry> TO=<nothing> TEST=tests/test_product_contract_drift.py`) and must go red. `api` (forge `in-tree`) is exempt from the snapshot check by an explicit, tested rule; a `github` entry without a snapshot is not
  - Proof that it can fail, one mutation per direction, each on a clean committed tree: `make mutate FILE=infra/config/values/staging.yaml FROM='default_port: 8080' TO='default_port: 8081' TEST=tests/test_product_contract_drift.py`; the same for editing the snapshot into an invalid one, and for deleting a snapshot while its registry entry remains. Expected: each exits 0, meaning the test went red (a collection error is not red)
  - Findings recorded while writing the first test (any key that differed before the migration): none. On 2026-10-18 the web snapshot matched all six contract-owned keys in both staging and prod (`compared 6 contract-owned keys for web/staging`, the same for prod); the mapping is `auth: public` -> `enable_auth: false` / `auth_level: bypass`, and `forwardauth` -> `true` / `one_factor`, the only Authelia policy an app uses today
  - Snapshot completeness, 2026-10-18: `snapshot_gaps()` returns `([], [])` on the committed registry. The "entry with no snapshot" direction is proven by mutating the check rather than deleting a file (`make mutate` edits text): `make mutate FILE=toolkit/features/product_render.py` with the missing list forced to `[]`, the orphan list forced to `[]`, and the exempt rule changed to `forge == "github"`; each went RED. With `SOPS_AGE_KEY_FILE` and `SOPS_AGE_KEY` unset in a subshell (`env -u` is refused by this session's permission settings), `poetry run pytest tests/test_product_contract_drift.py --no-cov -q`: 18 passed; no code path in the test calls SOPS
- [x] **AC4** `web` deploys to staging through the generic receiver, and its old receiver is deleted
  - Offline, PR 7 and PR 8: `poetry run pytest tests/test_product_image_receiver_workflow.py tests/test_delivery_health.py --no-cov -q`; and `test -e .github/workflows/web-image-receiver.yml && echo PRESENT || echo ABSENT`. Expected after PR 8: `ABSENT`; `git grep -n 'web-image-receiver' -- . ':!specs' ':!docs/lessons'` prints no live reference
  - The web contract: https://github.com/mlorentedev/web/pull/476 (`kubelab.yaml` at the root; the kubelab snapshot is its bytes at `901dcd4f`)
  - Before PR 7 leaves draft: `poetry run toolkit product ready --app web --json; echo "exit=$?"` against the live repository. Expected: `exit=0`, and the JSON names the staging pin and the contract's commit. Pasted in #2566 on 2026-10-21, after #2567 moved staging to `sha-7ebd808` (web#476's merge):

    ```
    $ poetry run toolkit product ready --app web --json; echo "exit=$?"
    {"ok": true, "app": "web", "repository": "mlorentedev/web", "tag": "sha-7ebd808", "sha": "7ebd8088948cba69453ebe4623d482610a787ca3"}
    exit=0
    ```

    Dry run on GitHub's runner from master, https://github.com/mlorentedev/kubelab/actions/runs/39532563387 (success). Steps:
    - fetch: `OK: .../kubelab.yaml is a valid kubelab product contract (schema_version 1)`
    - render: `web/staging: nothing to write`
    - promote: `staging: web already at sha-7ebd808; nothing to do`
    - would offer: only `infra/config/products/contracts/web.yaml`, the header comment this PR already syncs
  - **Live**, after PR 7 merges and before PR 8 is opened. A diff cannot show this, because it is a property of GitHub's event routing and of the web repository's CI. Push a trivial commit to `mlorentedev/web` master, then:
    - `gh run list --repo mlorentedev/kubelab --workflow product-image-receiver.yml --limit 3 --json conclusion,event,createdAt` shows a `success` run of event `repository_dispatch`
    - `gh api 'repos/mlorentedev/kubelab/pulls?state=open&head=mlorentedev:deploy/staging-web' --jq '.[0] | {number, title}'` shows the new sha in the title
    - `gh run list --repo mlorentedev/kubelab --workflow web-image-receiver.yml --limit 3 --json event,createdAt` shows no run for that dispatch (this is what proves the two receivers did not both act)
  - Measured 2026-10-21 over REST (the GraphQL quota was spent), two web merges after #2566 landed at 02:55Z: `f55a8c0` and web#477's `9d79e52`:
    - `product-image-receiver.yml`: run 39537825940 (03:18Z) and run 39540892119 (03:51Z), both `repository_dispatch` `web-image-published`, both `success`. In 39540892119 the `Fetch and validate the contract at the commit`, `Render the contract and promote the tag` and `Open or update the staging deploy PR` steps all succeeded, and the dry-run step was skipped
    - `deploy/staging-web`: #2576 `chore(staging): deploy web sha-f55a8c0`, merged by the operator at 03:47Z as `75702f21`; then #2581 `chore(staging): deploy web sha-9d79e52`, open, touching only `values/staging.yaml` and the generated staging deployment
    - `web-image-receiver.yml`: the latest run is 39529776394 at 01:52Z, before the flip. Its sibling 39529776414 is the product receiver on the same dispatch, which skipped web because web was still `legacy` then. There is no run at 03:18Z or 03:51Z, so after the flip exactly one receiver acted on each dispatch
- [x] **AC5** (#1815) `PLATFORM_APPS` is derived; a third registered product promotes
  - `git grep -n 'PLATFORM_APPS' -- toolkit tests` prints nothing but a removal comment
  - `poetry run pytest tests/test_promotion.py tests/test_product_registry.py tests/test_k8s_generator_secrets.py --no-cov -q`; the promotion test uses the fixture registry's `third` product and asserts the failure message for `ghost` names the registry file
  - No regression in the generated manifests: generate both overlays on master and on the branch and `diff -r` them. Expected: empty
- [x] **AC6** A contract cannot widen the registry
  - A contract that names a repository (`repository`, `repo`, `source`, `remote`) is refused, and the receiver test shows every fetch targets the registry's repository only (`tests/test_product_contract.py`, `tests/test_product_contract_guards.py`, `tests/test_product_image_receiver_workflow.py`)
  - `poetry run pytest tests/test_product_contract_guards.py --no-cov -q`: five refusals (an image other than the derived one, secret name, hostname collision, `auth: oidc`, a contract-named repository), each asserting ERROR / WHY / FIX, plus the positive case for web's real contract against the real registry and catalog
- [x] **AC7** A bad tag or an unresolvable commit is refused before any file is written
  - `poetry run pytest tests/test_product_image_receiver_workflow.py --no-cov -q`: the stubbed `gh` returns zero, two, and a non-default-branch commit; in every case the test asserts a non-zero exit and an unchanged working tree (`git status --porcelain` empty)
  - The short-sha spike (PR 6) is the evidence that the real API behaves as the stub assumes. Measured 2026-10-19 with `gh api` against `mlorentedev/web` (default branch `master`, 249 commits), staging pin `sha-b9874f2`:
    - `GET repos/mlorentedev/web/commits/b9874f2` -> 200, `.sha` = `b9874f2f693dd41ee4e1985cb88b0645ac59f996` (40 hex, starting with the short sha)
    - `GET .../commits/0000000` (unknown) -> 422 `No commit found for SHA: 0000000`
    - `GET .../commits/8748` (ambiguous: `87486966...` and `87481f3b...` both exist) -> 422 with the **same** message as an unknown sha. The API cannot tell ambiguous from unknown, so the receiver refuses both with one message naming both causes. A 7-hex prefix is ambiguous far less often than this 4-hex one, but the refusal does not depend on that
    - `GET .../compare/master...b9874f2` -> `identical`; `compare/master...<an older master commit>` -> `behind` (`behind_by: 4`); `compare/master...<the head of docs/web-161-agents-stack>` -> `ahead` (`ahead_by: 2`). On the default branch means `identical` or `behind`; `ahead` and `diverged` are refused
    - `GET repos/mlorentedev/web` -> `.default_branch` = `master`, so the receiver reads the default branch from the API rather than assuming `main`
    - `GET .../contents/.nvmrc?ref=<full sha>` with `Accept: application/vnd.github.raw` -> 200, the file body. `.../contents/kubelab.yaml?ref=<full sha>` -> 404: web carries no contract yet, which is the external dependency before PR 7
    - `github.event.action` carrying the event type on a `repository_dispatch` is GitHub's documented behaviour and is what `promote-prod.yml` already reads (`EVENT_TYPE: ${{ github.event.action }}`); it cannot be measured without sending a dispatch, which needs the operator's token

## Test status

- Test suite: on `addba106` (master with #2624), the round-3 reviewer ran `poetry run pytest -m "not e2e and not infra and not integration" -q --no-cov` and got `6449 passed, 20 skipped, 212 deselected`. It also ran `make lint` (clean) and `poetry run mypy toolkit` (no issues in 142 source files)
- Manual smoke test: the PR 6 dry run (`gh workflow run product-image-receiver.yml -f app=web -f tag=<sha> -f dry_run=true`), the PR 7 live proof above, and the prod no-op run 39725586157 for #2624
- No regressions in existing test suite: yes. The same run had 0 failures
- `/spec check`, 2026-10-22: PASS. AC1 to AC7 are each named by Implementation tasks: AC1 4 times, AC2 6, AC3 9, AC4 7, AC5 8, AC6 5, AC7 3. Thirteen tasks name no AC, and each still traces to one or is housekeeping:
  - to AC2: PR 1's validate check;
  - to AC6: PR 3's `auth: oidc` refusal;
  - to AC7: PR 6's short-sha spike;
  - to AC4: PR 6's dry run, the web contract (external dependency), PR 7's live proof and PR 8's doc sweep;
  - to AC3: the prod snapshot bootstrap;
  - housekeeping: the leftover-question ticket in PR 5 and the re-review.

  No orphans
- Mutation checks above were run on a clean tree via `make mutate`, never by editing and reverting by hand

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- Operator's answers to Q1-Q8 are recorded with their date in `proposal.md` under "Decisions" (2026-10-17). Q7 removed the registry's `image` field: the image is derived, with an override for `web` only.
- PR 6, operator 2026-10-19: the receiver is two jobs. `resolve` holds no write grant and refuses before anything is written (AC7); `promote` runs in `concurrency.group: product-receiver-${{ needs.resolve.outputs.app }}`. The task's group on `github.event.action` is empty on a manual run, so a manual re-promote and a dispatch of one app could both force-push `deploy/staging-<app>`.
- PR 6: a dispatch for a `receiver: legacy` product is skipped with a notice; a manual run of one proceeds only as a dry run and is refused otherwise, because its legacy workflow still writes the branch (design point 10). `dry_run` defaults to `true`, and only an explicit `false` leaves it, so a manual run that omits the box writes nothing.
- PR 6 adds `toolkit product show APP [--json]` for forge, repository and receiver, rather than widening `app-for-event`, so a manual run (which has no event type) asks the same command. The contract is fetched to `$RUNNER_TEMP` and copied into the tree only after `validate --registry --app` passes.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/ci-automation/lesson-607-two-receivers-on-one-dispatch-event-race-one-branch-so-the-flip-and-the-demotion-ship-together.md, docs/lessons/ci-automation/lesson-612-a-skip-that-matches-a-word-in-the-path-also-skips-every-checkout-named-after-it.md, docs/lessons/gitops-delivery/lesson-616-one-snapshot-for-two-envs-that-advance-separately-makes-the-slower-one-drift.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: ADR-067 already decides that a product's contract travels with its image, and ADR-056 that a release is a digest re-tag; the prod snapshot applies both. The answers to Q1-Q8 are recorded in the proposal and in the registry's header comment
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: the per-consumer snapshot rule (lesson-616) has been seen in this project only; promote it if a second project keeps one committed copy for two consumers

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Independent review recorded (`review.md` with a `PASS` or `PASS-WITH-GAPS` verdict from a session that did not implement)
- [ ] Folder moved: `specs/IDP-042-product-contract-registry/` -> `specs/archive/IDP-042-product-contract-registry/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018); #1815 closed with the PR that removed the literal; the epic #1931 checklist ticked for both
- [ ] Promotions above executed (if any)

## Closeout review, 2026-10-21 (round 2, `nan/deepseek-v4-flash`, on `d7a0d8db`): FAIL

Round 1 (`nan/mimo-v2.6-flash`) stopped on a 429 concurrency limit before giving a verdict. Its provisional file is `review-round1.md`.

| Finding | Severity / reality | Disposition |
|---|---|---|
| A contract change to a prod-owned key (`port`, `health_path`, `auth`, `hostnames.prod`) cannot land. The receiver renders staging only, nothing renders prod, and §Risks says the prod lane does. | Major / REAL | Fix in #2624 (operator chose option A, inside IDP-042, 2026-10-21). Confirmed by reading: `product-image-receiver.yml` renders `--env staging` only, and `promote-prod.yml` had no render step. Each env now renders from its own snapshot: `contracts/prod/<app>.yaml` is written by `promote-prod` from `kubelab.yaml` at the release commit, and that commit is proven by digest. Named test: `tests/test_product_contract_drift.py::test_a_contract_change_to_a_prod_owned_key_leaves_the_tree_green`, which goes red under `make mutate` when prod reads the flat file. Live no-op run: 39725586157. The second review runs after #2624 merges. |
| AC2's by-hand command names a fixture that does not exist | Minor / REAL | Fixed: `tests/fixtures/product/invalid-port.kubelab.yaml` added, and the command was run (output above). |
| `site_domain` / `site_url` mirror `domain` and nothing ties them to it | Minor / THEORETICAL | Ticketed: #2610 |
| Two generic products force-push deploy branches that rewrite the same staging files | Minor / SPECULATIVE | Ticketed: #2611 |

AC1 stays unticked: its live half (an unmapped dispatch) is run by the operator.

## Closeout review, 2026-10-22 (round 3, `nan/qwen3.8-flash`, on `addba106`): PASS-WITH-GAPS

The round-2 Major is closed. The reviewer applied five mutations of its own to the #2624 fix, and named tests failed under every one. The contract digests were the same before and after the ticks below, so the verdict still holds.

| Finding | Severity / reality | Disposition |
|---|---|---|
| The `tasks.md` Closing block, PR 7's live-proof box and two promotion lines were unfilled | Minor / REAL | Applied. The boxes the evidence supports are ticked; ticks do not change the `tasks.md` digest (`233b5f05…` before and after). All three promotion lines are answered, and `/spec check` is recorded under Test status. |
| No written recovery when `release-contract` refuses an emergency rollback | Minor / THEORETICAL | Applied. `docs/runbooks/cicd.md` names the path: `git revert` of the promotion PR. The workflow keeps no bypass. |
| `_prove_image` looks for `sha-<7 hex>`, but the receiver accepts `sha-<7+ hex>` | Minor / THEORETICAL | Ticketed: #2627 (IDP-054). It is latent because web publishes 7-hex tags. |
| `tag_digest` returns `None` for any non-`docker.io` host, and the FIX then points at a tag that exists | Minor / THEORETICAL | Ticketed: #2627 (IDP-054), together with private images. IDP-053 (#2449) is told it meets this limit on both lanes. |
| No static test ties `contracts/prod/<app>.yaml` to the prod `version` pin | Minor / SPECULATIVE | Declined, accepted limit. Only `promote-prod` writes the pin and the snapshot, and it writes both in one PR. A hand edit of `version` alone is caught live, because `verify-product` reads `hostnames.prod` from the prod snapshot (`TestTargetsAt::test_prod_reads_the_prod_snapshot_not_the_staging_one`). A static tie would need the release commit, which only the forge knows, so it could not run offline. |
| The prod snapshot inherits a header naming the staging path; the DNS test's wording reads as covering both directories | Minor / SPECULATIVE | Applied for the header. `cicd.md` marks the prod snapshot machine-owned, and the snapshot stays a byte copy. Declined for the DNS test: it checks the staging snapshot on purpose, because the record has to exist before prod cuts over (the reviewer agrees this is correct). |
| Question: AC1's live unmapped-dispatch half | — | The operator runs it before the archive, with the command in the AC1 row. |
