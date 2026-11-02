---
spec: "IDP-042-product-contract-registry"
verdict: "FAIL"
reviewed_sha: "d7a0d8db9b228ad9f31d6218f4dfcff6dd7c3bdc"
reviewer: "nan/deepseek-v4-flash"
date: "2026-10-21"
---

## Adversarial review

**Scope**: `IDP-042-product-contract-registry` — `git diff 2c82904656e3ad15f19fe771ebf679ebbd7388ed...HEAD`
(374 files; the range also carries unrelated PRs merged between the base and HEAD, so scope below is
judged on the files this spec's own tasks name, not on the whole range).
**Sources**: `specs/IDP-042-product-contract-registry/{proposal,tasks,verification,features.json}.md`,
`toolkit/features/{product_registry,product_contract,product_guards,product_render,product_ready}.py`,
`toolkit/cli/product.py`, `.github/workflows/{product-image-receiver,promote-prod}.yml`,
`infra/config/{products.yaml,products/contracts/web.yaml}`, `tests/test_product_*.py`.

### Spec and task alignment

Verified by running, not by reading assertions:

| Criterion | Evidence I produced | Result |
|---|---|---|
| AC1 registry decides; payload cannot name the app | `pytest tests/test_product_registry.py tests/test_product_image_receiver_workflow.py`; workflow reads `client_payload.tag` only | pass (offline half; the live half is still unticked in `verification.md`) |
| AC2 schema refusal with ERROR/WHY/FIX | `tests/test_product_contract.py`, `tests/test_product_contract_schema.py` | pass |
| AC3 drift detection, offline, non-vacuous | `tests/test_product_contract_drift.py` (22 pass); mutation `staging.yaml default_port 8080→8081` turns 3 of them red | pass — the guard really can fail |
| AC4 web on the generic receiver, old receiver deleted | `.github/workflows/web-image-receiver.yml` absent; `tests/test_delivery_health.py`, `tests/test_receiver_pr_step.py` pass; live run evidence in `verification.md` | pass |
| AC5 `PLATFORM_APPS` derived | `git grep -n 'PLATFORM_APPS' -- toolkit tests` → no output; `tests/test_promotion.py`, `tests/test_product_registry.py`, `tests/test_k8s_generator_secrets.py` pass | pass |
| AC6 contract cannot widen the registry | `tests/test_product_contract_guards.py` (21 pass), including the four refused repository keys and the hand-written-route hostnames | pass |
| AC7 bad tag/commit refused | `tests/test_product_image_receiver_workflow.py` tag/commit cases; `resolve` job holds no write grant | pass |

Whole-suite and linters, run fresh in this session:

- `pytest -m "not e2e and not infra and not integration"` → **6376 passed, 20 skipped, 212 deselected** (303s).
- `make lint` → `All checks passed!`, `142 files already formatted`. `mypy toolkit` → `Success: no issues found in 141 source files`.

Task boxes: `tasks.md` "Setup" still has `/spec check` unticked and the whole "Closing" section unticked;
`verification.md` leaves AC1, AC2, AC3, AC5, AC6, AC7 unticked while recording rich evidence for them.
`features.json` is entirely `state: pending` with empty `evidence` (harness-owned, so not a false claim,
but nothing in the contract has been machine-verified). No `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tags remain.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | REAL | delivery / render coverage | A contract change to a **prod-owned** key (`port`, `health_path`, `auth`, `hostnames.prod`) cannot land. The receiver renders only `--env staging`, so the same PR that writes the new snapshot leaves `values/prod.yaml` rendering the old snapshot; `test_the_web_snapshot_matches_the_values[prod]` then fails on that PR and on `master`, and no workflow renders prod from the contract. `proposal.md` §Risks states the opposite — that the prod lane "fetches the contract at that commit and renders the prod hostnames from it" — and `tasks.md` has no task for it. | Reproduced: editing `hostnames.prod` in `infra/config/products/contracts/web.yaml` (a change the snapshot's own header invites) turns 6 tests red, including `test_the_web_snapshot_matches_the_values[prod]` and `test_render_check_passes_on_the_committed_tree[prod]`. `grep -n "render" .github/workflows/promote-prod.yml toolkit/features/promotion.py` → no render step and no `product_render` caller; the prod lane runs only `deployment promote --env prod`. `docs/runbooks/cicd.md` documents `product render --env <env> --write` for onboarding only, not for a contract change. | `tests/test_product_contract_drift.py::test_the_web_snapshot_matches_the_values[prod]` detects the drift, but **no named test or step corrects it** → the correction path is UNTESTED | code (receiver renders every env whose values the contract owns, or `promote-prod.yml` renders prod from the snapshot at the staging pin as the proposal claims) + tests (a contract edit to a prod-owned key leaves the tree green) + spec (`verification.md` records the reproduction and the fix) |
| Minor | REAL | verification artifacts | `verification.md` AC2's "By hand, offline" command cites `tests/fixtures/product/invalid-port.kubelab.yaml`, which does not exist; the command exits 1 for a missing file, so the quoted JSON/diagnosis in that row was never produced as written. | Ran it: `{"ok": false, "error": "...invalid-port.kubelab.yaml: cannot be read (No such file or directory)", ...}`, exit 1. `ls tests/fixtures/product/` → `registry.yaml`, `web.kubelab.yaml` only. The schema-refusal behaviour itself is proven by `tests/test_product_contract.py`. | UNTESTED (nothing guards the cited command) | spec artifacts (`verification.md`, outside the contract set) and/or `tests/fixtures/product/invalid-port.kubelab.yaml` |
| Minor | THEORETICAL | SSOT / hostname | `render` owns `domain`, but web's `site_domain` and `site_url` mirror the same hostname in both overlays and nothing ties them to it. A contract hostname change would leave canonical URLs and the Astro site URL pointing at the old host while the drift test stays green. `proposal.md` row 1 keeps `site_*` out of scope, so this is a recorded consequence rather than a spec violation. | `grep -rn "site_domain\|site_url" tests/ toolkit/` → no hits; `values/staging.yaml:48-50` and `values/prod.yaml:79-81` carry all three keys. | UNTESTED | tests (one consistency test) or a follow-up ticket; do not edit `proposal.md` |
| Minor | SPECULATIVE | concurrency / multi-product | With a second `receiver: generic` product, two long-lived branches (`deploy/staging-<app>`) both rewrite the shared `values/staging.yaml` and the generated staging overlay from their own base, while `concurrency.group: product-receiver-<app>` serialises only within one app and the push is `--force`. Latent today (web is the only generic product). Surfaced deliberately; it does not move the verdict. | Code read: `.github/workflows/product-image-receiver.yml` (`concurrency.group`, `git push origin "$BRANCH" --force`), `product_render.write()` editing the env file in place. | UNTESTED | code (a test with two generic fixture products), or record as a known limit |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All seven criteria are exercised and pass on the delivered paths; the prod-owned-key change path is a real functional hole rather than a wrong result. |
| Verification       | C | Commands reproduce (I re-ran them), but six of seven AC rows stay unticked, one live sub-check (AC1) is unrun, and one cited by-hand command names a fixture that does not exist. |
| Scope              | B | The IDP-042 slice matches the proposal's eight PRs; the reviewed range also carries unrelated merged PRs, which the base commit choice makes unavoidable, not creep by this spec. |
| Reliability        | C | Refusals are correct and precede writes, but the flow has one unhandled operational path: a contract change to a prod-owned key leaves `master` red with no automated corrective. |
| Maintainability    | B | `make lint` clean, `mypy` clean, ≤40-line functions, refusals carry ERROR/WHY/FIX, comments explain the why (force-push, concurrency group, Q7 derivation). |
| Handoff-readiness  | C | The lesson and runbook updates are there, but `tasks.md`/`verification.md` understate what is proven, and the proposal's prod-lane risk paragraph describes behaviour the code does not have. |

### Verdict

**FAIL** — one **REAL Major** (the prod-owned-key change path). The rubric alone would allow PASS WITH GAPS; the severity × reality rule escalates it.

Reviewer note: I did not write this change; commands above were run in this session against
`d7a0d8db9b228ad9f31d6218f4dfcff6dd7c3bdc`, and every mutation was reverted (`git status` shows only the
untracked review artifacts).

### Recommended next steps

1. **Code + tests (contract set untouched):** close the prod gap. Either have the receiver render every
   environment whose values the contract owns, or give `promote-prod.yml` the fetch-validate-render step
   `proposal.md` §Risks already describes. Then add a named test that a contract edit to
   `hostnames.prod`/`port`/`auth` leaves the tree green, and re-run
   `pytest tests/test_product_contract_drift.py -q`. This is the fix that flips the verdict; it needs a re-review.
2. **`verification.md` (outside the contract set):** record the reproduction above, and correct or add a
   fixture for the AC2 by-hand command so the row states a command that was actually run.
3. **Ticks only:** ticking the AC boxes in `verification.md`/`tasks.md` and the Closing checklist is safe
   (the archive digest ignores checkbox ticks); any rewording of `proposal.md`, `tasks.md` or
   `features.json` would invalidate this verdict, so do not.
4. **Track, do not block:** the `site_domain`/`site_url` mirror of `domain`, and the multi-product
   shared-file force-push limit. Both belong in `verification.md` as dispositions or in follow-up tickets.
5. `dotf spec archive` is **not** advisable in this state: the verdict is FAIL and the archive gate refuses it.
