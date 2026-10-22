---
spec: "IDP-042-product-contract-registry"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "addba1066cc4ea2dd495f1e9fff6aaa732e52c11"
reviewer: "nan/qwen3.8-flash"
date: "2026-10-22"
---

## Adversarial review

**Scope**: `IDP-042-product-contract-registry` — round 3, the re-review after the round-2 FAIL.
`git diff 2c82904656e3ad15f19fe771ebf679ebbd7388ed...HEAD` (396 files; the range carries unrelated PRs
merged between base and HEAD, so scope is judged on the files this spec's tasks name, not on the whole
range). The late fix under review is `4c9cda64 fix(product): render prod from the release's own contract
snapshot (#2624)`, judged together with the early PRs it interacts with (`product_render`, the drift
tests, `product_verify.targets_at`, `promote-prod.yml`, `tests/test_dns_contract_hostnames.py`).

**Sources**: `specs/IDP-042-product-contract-registry/{proposal,tasks,verification,features,review-round2}.md`,
`toolkit/features/{product_registry,product_contract,product_guards,product_render,product_release,product_ready,product_verify,registry}.py`,
`toolkit/cli/product.py`, `.github/workflows/{product-image-receiver,promote-prod}.yml`,
`infra/config/{products.yaml,products/contracts/web.yaml,products/contracts/prod/web.yaml}`,
`tests/test_product_*.py`, `tests/test_promote_prod_dispatch.py`, `tests/test_dns_contract_hostnames.py`,
`docs/runbooks/cicd.md`.

**Contract freshness**: `dotf spec digest IDP-042-product-contract-registry` returns
`features.json 03b7dd85…`, `proposal.md 90d05ded…`, `tasks.md 233b5f05…` — byte-equal to the
`contract_digests` this round's `review-request.json` recorded. This review is against the current contract.

### Spec and task alignment

Verified by running, not by reading assertions (every command re-run in this session on `addba106`):

| Criterion | Evidence I produced | Result |
|---|---|---|
| AC1 registry decides, payload cannot name the app | `tests/test_product_registry.py`, `tests/test_product_image_receiver_workflow.py` in the 6449-pass suite; the resolve step reads `client_payload.tag` only, and reads `app`/`lane`/`receiver` through `toolkit product … --json` with `jq -er` so a missing field fails | pass (offline; the live unmapped-dispatch half stays operator-run) |
| AC2 schema refusal with ERROR/WHY/FIX | `tests/test_product_contract.py`, `tests/test_product_contract_schema.py`, `tests/test_product_cli.py`; fixture `tests/fixtures/product/invalid-port.kubelab.yaml` now exists (the round-2 Minor is closed) | pass |
| AC3 drift, offline, non-vacuous | `env -u SOPS_AGE_KEY_FILE poetry run pytest tests/test_product_contract_drift.py --no-cov -q` → **28 passed**; and my own mutation (below) proves it can fail | pass |
| AC4 web on the generic receiver, old receiver deleted | `web-image-receiver.yml` absent from the tree; I checked GitHub independently: runs **39537825940** and **39540892119** are both `Product Image Receiver / repository_dispatch / success / master`, and **#2581** `chore(staging): deploy web sha-9d79e52` is `MERGED`. The evidence `verification.md` pastes is real | pass (the live proof exists; the `tasks.md` box is still unticked — finding 1) |
| AC5 `PLATFORM_APPS` derived | the `features.json` f5 guard itself: `test -z "$(git grep -n 'PLATFORM_APPS' -- toolkit …)"` → `grep-guard OK`; `tests/test_promotion.py` green | pass |
| AC6 contract cannot widen the registry | `tests/test_product_contract_guards.py`, the four refused repository keys, `test_every_committed_snapshot_passes_the_registry_guards` now covers **both** snapshot dirs (the prod copy included) | pass |
| AC7 bad tag/commit refused before any write | `tests/test_product_image_receiver_workflow.py`; `resolve` job holds no write grant | pass |
| Whole change | `poetry run pytest -m "not e2e and not infra and not integration" -q --no-cov` → **6449 passed, 20 skipped, 212 deselected in 333.26s**, 0 failures | pass |
| Quality gates | `make lint` → `All checks passed!`, `143 files already formatted`; `poetry run mypy toolkit` → `Success: no issues found in 142 source files` | pass |

**Round-2's REAL Major is closed, and I confirmed the closure is guarded rather than decorative** — four
mutations, each reverted (`git status` clean afterwards):

| Mutation | Named tests that went red |
|---|---|
| delete the `contract` step from `promote-prod.yml` | 5 in `tests/test_promote_prod_dispatch.py`: `test_the_release_contract_is_rendered_before_the_promotion`, `test_a_contract_managed_app_renders_prod_from_its_release`, `test_an_in_tree_app_skips_the_render`, `test_a_refused_release_contract_fails_in_red_and_renders_nothing`, `test_a_release_failure_that_is_not_json_names_its_output` |
| drop `infra/config/products/contracts/prod/` from the PR's `git add` | `test_the_promotion_pr_carries_the_prod_snapshot` |
| `snapshot_path`: point prod back at the flat snapshot | `test_a_contract_change_to_a_prod_owned_key_leaves_the_tree_green`, `test_the_prod_snapshot_is_a_separate_file_from_the_staging_one`, `test_a_prod_snapshot_for_an_app_prod_does_not_pin_is_drift` |
| disable the digest equality in `product_release._prove_image` | `test_a_tag_naming_another_commit_is_refused` |
| `product_verify.targets_at`: read the staging snapshot for every env | `TestTargetsAt::test_prod_reads_the_prod_snapshot_not_the_staging_one` |

The per-env snapshot split is the right shape: prod's drift is judged against `contracts/prod/<app>.yaml`,
written by the promotion from the release's own commit (proven by digest, not trusted), so a contract change
to a prod-owned key no longer turns prod red on a staging PR — which is exactly what round 2 could not fix.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | spec artifacts / handoff | The bookkeeping that the archive gate reads is still unfilled: `tasks.md` PR 7's live-proof box and the whole `Closing` block are unticked (though `verification.md` records the runs — and I confirmed them against GitHub myself), `/spec check` is unticked, AC1's row stays unticked, and in `verification.md` two of the three "Promotion candidates" lines still carry the literal `<yes: path / no: reason>` template even though a second lesson (`lesson-616`) landed this round. The file's own text states `dotf spec archive` refuses a line left unanswered. | Ran `dotf spec digest` before/after ticking `Type checks pass`: digest unchanged (`233b5f05…` both ways) → **ticking is safe and does not invalidate this verdict**. Whether the archive parser accepts the prose "Likely `no`: …" as an answer I could not reach: **UNVERIFIED** (the gate's implementation is outside this repo). | UNTESTED — no test guards the promotion-candidate lines or the Closing block | spec artifacts outside the contract set (`verification.md`, `tasks.md` ticks only) |
| Minor | THEORETICAL | reliability / ops | The new prod gate hard-blocks a rollback to any release older than the product's first `kubelab.yaml`, and no recovery path is written down. `docs/runbooks/cicd.md` states the refusal ("rollbacks included") but names no bypass; `make promote-prod` only dispatches this workflow, so the workflow is the only codified path. | Code read: `product_release.fetch_release_contract` refuses when `contents/kubelab.yaml?ref=<sha>` is unreadable; `Makefile:997-1009` dispatches `promote-prod.yml` rather than promoting locally; `grep promote docs/runbooks/break-glass.md` → nothing about promotion. The counter-evidence is real: `git revert` of a merged promotion PR restores the previous snapshot and values together, so a revert of the last promotion still works. | `tests/test_product_release.py::test_a_release_without_a_contract_is_refused` proves the refusal; **no test and no doc covers the recovery**, so the recovery is UNTESTED | docs (`docs/runbooks/cicd.md` — name the revert path) + tests if a bypass is ever added |
| Minor | THEORETICAL | cross-product latent bug | The prod lane proves the release by comparing `<image>:<version>` with `<image>:sha-<first 7 hex of the commit>`, but the tag grammar the platform accepts is `sha-[0-9a-f]{7,}` (`product-image-receiver.yml`, `promotion._SHA_TAG`). A product whose CI publishes 8+-hex tags can be received into staging and can then **never** be promoted: the tag the proof looks for is one it never published. Latent — web publishes 7. | Code read: `_prove_image` builds `built = f"{SHA_TAG_PREFIX}{sha[:7]}"`; the receiver's `[[ "$tag" =~ ^sha-[0-9a-f]{7,}$ ]]` accepts more. `verification.md` records web's own scheme as `sha-${GITHUB_SHA::7}`, which is why nothing is red today. | `tests/test_product_release.py::test_the_release_contract_is_fetched_at_the_tagged_commit` pins the 7-hex form; the longer-tag case is **UNTESTED** | code (derive the published tag, or accept any `sha-<prefix-of-sha>`) + tests |
| Minor | THEORETICAL | portability / misleading error | `registry.tag_digest` answers `None` for any host that is not `docker.io/`, and `_prove_image` turns that into "the digest of X:Y cannot be read / FIX: check that X:Y exists". For a product on another registry the prod lane is impossible and the FIX sends the operator to look for a tag that does exist. | Code read: `if not registry.startswith("docker.io/"): return None` in `toolkit/features/registry.py`, consumed unconditionally by `_prove_image`. Today every derived image is `docker.io/mlorentedev/...` (`REGISTRY` in the merged config), so nothing is red. | `test_an_unreadable_digest_is_refused_not_skipped` covers the None→refusal, not the non-Hub cause → the message is **UNTESTED** | code or tests (a non-Hub case with a FIX that names the registry), or state the docker.io limit in `proposal.md`'s next revision |
| Minor | SPECULATIVE | SSOT | Nothing statically ties `contracts/prod/<app>.yaml` to the `version` pinned in `values/prod.yaml`: `version` is deliberately not contract-owned, so a hand edit of `version` alone leaves every drift test green while prod runs a release whose contract was never rendered. | Code read: `CONTRACT_KEYS` has no version entry by design (`write` "never touches version"); the consequence is caught live by `toolkit infra argo verify-product` (`product_verify.targets_at` reads the prod snapshot — I confirmed that by mutation). | `tests/test_product_verify.py::TestTargetsAt::test_prod_reads_the_prod_snapshot_not_the_staging_one` covers the live half; the static tie is **UNTESTED** | tests (a version↔snapshot assertion) or record as an accepted limit |
| Minor | SPECULATIVE | docs / ownership | The prod snapshot is a byte-for-byte copy of the product's `kubelab.yaml`, so it carries that file's header, which names `infra/config/products/contracts/web.yaml` (the staging path) and invites "edit it here" — on a file that is machine-owned and overwritten by the next promotion. `test_dns_contract_hostnames.py` likewise says it holds "every committed snapshot's prod hostname" while globbing only the flat dir (correct by transitivity — the staging snapshot is always the newer name — but the wording reads as a gap). | `cat infra/config/products/contracts/prod/web.yaml` (header identical to the staging copy); `SNAPSHOT_DIR.glob("*.yaml")` is not recursive. | `test_a_staging_hostname_needs_no_public_record`, `test_main_tf_still_keys_records_the_way_this_test_does` hold the DNS behaviour; the header wording is UNTESTED (fix is a runbook line, not a code change) | docs (`cicd.md`: the prod snapshot is machine-owned) — do **not** break byte-for-byte copying |
| Question | — | AC1 | The live half of AC1 (an unmapped `event_type` ends a run in red and opens nothing) has never been dispatched; the offline half is covered by named tests. Who runs it, and when, is recorded as the operator's. | `verification.md` AC1 row unticked with the exact command; `gh` dispatch needs the operator's token | `tests/test_product_image_receiver_workflow.py` (offline half) | ops — carry into the archive step, not a code fix |

**Carried from round 2, dispositions verified real:** `#2610` (`site_domain`/`site_url` mirror of `domain`) and
`#2611` (two generic products force-pushing shared staging files) are both **OPEN** on the forge — checked with
`gh issue view`. `#1815` is CLOSED (AC5's absorbed issue). No `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tag remains
in any spec file (the only grep hit is `review-transcript.jsonl`, a launcher artifact — untracked and ignored,
and it holds no credential: scanned for `age1…`, `ghp_…`, `github_pat_…`, private-key blocks; only image
`sha256:` digests present).

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All seven criteria exercised green; the round-2 REAL Major is fixed and five of my own mutations show the fix is guarded, not asserted. |
| Verification       | B | Every quoted command reproduces here (6449 passed, lint clean, mypy clean), the AC4 live evidence checks out against GitHub independently of the spec's own claim; the unfilled tick/placeholder bookkeeping is a handoff gap, not absent evidence. |
| Scope              | B | The IDP-042 slice matches the proposal's eight PRs plus the closeout fix; unrelated PRs in the range come from the base commit, not from this spec. |
| Reliability        | B | Refusals precede every write and fail closed; two latent paths (longer sha tags, non-docker.io registries) refuse with a message that misdirects, and the rollback gate has no documented bypass. |
| Maintainability    | B | lint + mypy clean, ≤40-line functions, ERROR/WHY/FIX on every refusal, comments carry the why (force-push, per-env snapshots, `jq -er`); `product_release` reaching into `product_ready._gh` is the one private-helper smell. |
| Handoff-readiness  | C | Lesson-616 and the runbook update landed, but `tasks.md`'s Closing block, PR 7's live box and two `verification.md` promotion lines are still template text the archive gate reads. |

### Verdict

**PASS WITH GAPS** — no Blocker, no open REAL Major (the round-2 REAL Major is fixed and its guard is proven
by mutation); one C in the rubric (Handoff-readiness), and every remaining Major-class candidate is
THEORETICAL/SPECULATIVE and tracked. Per the severity × reality rule this stands: the gaps below are
tracked, not fixed, and none of them may be closed by editing `proposal.md`, `tasks.md` or `features.json`
under this verdict — a contract edit here requires a further round.

### Recommended next steps

For the implementer to disposition in `verification.md` (applied / ticketed / declined with a reason) or to
carry into a follow-up ticket — all of these are outside the contract set, so they do not invalidate this verdict:

1. **Ticks and placeholders only (safe, proven not to change the digest):** tick `tasks.md`'s Closing items
   the evidence already supports (type checks, lint, AC test coverage, verification filled, review recorded),
   tick PR 7's live-proof box since runs 39537825940/39540892119 and #2581 exist and I re-verified them, and
   answer the two `verification.md` promotion lines with `no: <reason>` in their own words (lesson-616 means
   the Lesson line now has two files). Then confirm `dotf spec check` / `/spec check` returns PASS or record
   why it does not — that box is the one I could not settle from here.
2. **Docs:** one line in `docs/runbooks/cicd.md` naming the recovery path when `release-contract` refuses an
   emergency rollback (revert the promotion PR; the workflow has no bypass), and one line marking
   `contracts/prod/<app>.yaml` machine-owned despite the header it inherits.
3. **Code + tests (carry, not block):** `_prove_image`'s `sha[:7]` against the `{7,}` tag grammar the receiver
   accepts; `tag_digest`'s silent `None` for non-`docker.io` hosts and the FIX that follows from it. Both are
   latent while web is the only generic product, so a ticket naming them is enough — do not edit `proposal.md`
   for either.
4. **Ops:** have the operator run AC1's unmapped-dispatch check once before the archive, since it is the last
   acceptance half with no live proof; #2610 and #2611 stay open as this verdict's tracked gaps.
5. `dotf spec archive` is **advisable** once step 1 is done; the archive gate's own acceptance of
   `PASS-WITH-GAPS` and of the `verification.md` promotion lines is what step 1 exists to satisfy.

Reviewer independence: I did not write this change. Every command above ran in this session against
`addba1066cc4ea2dd495f1e9fff6aaa732e52c11`; all five mutations were reverted and the working tree holds only
`review.md` and the launcher's `review-request.json`.
