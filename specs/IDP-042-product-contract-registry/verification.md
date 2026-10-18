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
- [ ] **AC2** A contract that fails the schema fails the receiver with ERROR / WHY / FIX
  - PR 1: `poetry run pytest tests/test_product_contract.py tests/test_product_contract_schema.py --no-cov -q`; every refusal case asserts the three labelled lines and the field name
  - PR 6: the stubbed-`gh` receiver test feeds an invalid contract body and asserts non-zero exit and the three lines in the step output
  - By hand, offline: `poetry run toolkit product validate --contract tests/fixtures/product/invalid-port.kubelab.yaml --json; echo "exit=$?"`. Expected: JSON with `error`, `why`, `fix`, `exit=1`
- [ ] **AC3** A test fails if anything derived from a contract drifts from it
  - `env -u SOPS_AGE_KEY_FILE poetry run pytest tests/test_product_contract_drift.py --no-cov -q`. Expected: PASS, offline
  - Not vacuous: the test prints `compared N contract-owned keys for web/<env>` and asserts N equals the size of the schema-to-values mapping; one more mutation empties the mapping (`make mutate FILE=toolkit/features/product_render.py FROM=<the mapping entry> TO=<nothing> TEST=tests/test_product_contract_drift.py`) and must go red. `api` (forge `in-tree`) is exempt from the snapshot check by an explicit, tested rule; a `github` entry without a snapshot is not
  - Proof that it can fail, one mutation per direction, each on a clean committed tree: `make mutate FILE=infra/config/values/staging.yaml FROM='default_port: 8080' TO='default_port: 8081' TEST=tests/test_product_contract_drift.py`; the same for editing the snapshot into an invalid one, and for deleting a snapshot while its registry entry remains. Expected: each exits 0, meaning the test went red (a collection error is not red)
  - Findings recorded while writing the first test (any key that differed before the migration): `<fill in>`
- [ ] **AC4** `web` deploys to staging through the generic receiver, and its old receiver is deleted
  - Offline, PR 7 and PR 8: `poetry run pytest tests/test_product_image_receiver_workflow.py tests/test_delivery_health.py --no-cov -q`; and `test -e .github/workflows/web-image-receiver.yml && echo PRESENT || echo ABSENT`. Expected after PR 8: `ABSENT`; `git grep -n 'web-image-receiver' -- . ':!specs' ':!docs/lessons'` prints no live reference
  - Before PR 7 leaves draft: `poetry run toolkit product ready --app web --json; echo "exit=$?"` against the live repository. Expected: `exit=0`, and the JSON names the staging pin and the contract's commit. Paste it in the PR body: `<fill in>`
  - **Live**, after PR 7 merges and before PR 8 is opened. A diff cannot show this, because it is a property of GitHub's event routing and of the web repository's CI. Push a trivial commit to `mlorentedev/web` master, then:
    - `gh run list --repo mlorentedev/kubelab --workflow product-image-receiver.yml --limit 3 --json conclusion,event,createdAt` shows a `success` run of event `repository_dispatch`
    - `gh api 'repos/mlorentedev/kubelab/pulls?state=open&head=mlorentedev:deploy/staging-web' --jq '.[0] | {number, title}'` shows the new sha in the title
    - `gh run list --repo mlorentedev/kubelab --workflow web-image-receiver.yml --limit 3 --json event,createdAt` shows no run for that dispatch (this is what proves the two receivers did not both act)
  - Paste the three outputs here: `<fill in>`
- [ ] **AC5** (#1815) `PLATFORM_APPS` is derived; a third registered product promotes
  - `git grep -n 'PLATFORM_APPS' -- toolkit tests` prints nothing but a removal comment
  - `poetry run pytest tests/test_promotion.py tests/test_product_registry.py tests/test_k8s_generator_secrets.py --no-cov -q`; the promotion test uses the fixture registry's `third` product and asserts the failure message for `ghost` names the registry file
  - No regression in the generated manifests: generate both overlays on master and on the branch and `diff -r` them. Expected: empty
- [ ] **AC6** A contract cannot widen the registry
  - A contract that names a repository (`repository`, `repo`, `source`, `remote`) is refused, and the receiver test shows every fetch targets the registry's repository only (`tests/test_product_contract.py`, `tests/test_product_contract_guards.py`, `tests/test_product_image_receiver_workflow.py`)
  - `poetry run pytest tests/test_product_contract_guards.py --no-cov -q`: five refusals (an image other than the derived one, secret name, hostname collision, `auth: oidc`, a contract-named repository), each asserting ERROR / WHY / FIX, plus the positive case for web's real contract against the real registry and catalog
- [ ] **AC7** A bad tag or an unresolvable commit is refused before any file is written
  - `poetry run pytest tests/test_product_image_receiver_workflow.py --no-cov -q`: the stubbed `gh` returns zero, two, and a non-default-branch commit; in every case the test asserts a non-zero exit and an unchanged working tree (`git status --porcelain` empty)
  - The short-sha spike (PR 6) is the evidence that the real API behaves as the stub assumes: record the request and the response status here: `<fill in>`

## Test status

- Test suite: `make test-fast` -> `<output / coverage %>` after each PR
- Manual smoke test: the PR 6 dry run (`gh workflow run product-image-receiver.yml -f app=web -f tag=<sha> -f dry_run=true`) and the PR 7 live proof above
- No regressions in existing test suite: yes / no (if no, document)
- Mutation checks above were run on a clean tree via `make mutate`, never by editing and reverting by hand

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- Operator's answers to Q1-Q8 are recorded with their date in `proposal.md` under "Decisions" (2026-10-17). Q7 removed the registry's `image` field: the image is derived, with an override for `web` only.
-

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [ ] Lesson for the repo's `docs/lessons/`? <yes: path / no: reason>. Candidates already visible: two receivers listening to one event race a single branch during a cutover (so the flip and the demotion share a PR); `repository_dispatch` types are a static list, so a registry-driven receiver omits them
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason>. Likely `no`: ADR-067 holds the decision; the answers to Q1-Q8 are recorded in `proposal.md` and in the registry's header comment
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Independent review recorded (`review.md` with a `PASS` or `PASS-WITH-GAPS` verdict from a session that did not implement)
- [ ] Folder moved: `specs/IDP-042-product-contract-registry/` -> `specs/archive/IDP-042-product-contract-registry/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018); #1815 closed with the PR that removed the literal; the epic #1931 checklist ticked for both
- [ ] Promotions above executed (if any)
