---
spec: "ADR028-004-classify-stateful-service-placement"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "6974af9b22fe2a0dcc333dd6ad1ae7bb39e8c353"
reviewer: "nan/mimo-v2.6-flash"
date: "2026-10-10"
---

## Adversarial review

**Scope**: ADR028-004-classify-stateful-service-placement — round 2 (whole change from base `de15841`, not only the delta since round 1 at `00854de2`)
**Sources**: `specs/ADR028-004-classify-stateful-service-placement/{proposal,tasks,verification,features}.md|json`, `git diff de1584131b4c92323cd7a0a65a3afcf06b7eaae5...HEAD`. The range contains 696 commits of shared `master` history since the spec's first commit (`2a3b5a44`, proposal scaffold #1003); findings are scoped to the spec's own implementation — PRs #1039 (`b81ba7c1`), #1035 (`f3d9ffd6`), #2060 (`5cccd7ef`), #1058 (`7b2879b8`), #1062 (`b92debff`) — plus the two post-round-1 commits judged against the early work (`4fca806c` complexity split, `6974af9b` dispositions). Unrelated work in the range belongs to other specs with their own reviews.

### Spec and task alignment

- **Contract freshness**: `sha256` of `proposal.md`, `tasks.md`, `features.json` matches the `contract_digests` in `review-request.json`. No `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags in any spec file.
- **AC1 (ADR, both axes, eight services)**: **Met, verified fresh.** `docs/adr/adr-061-stateful-service-placement.md` exists with all eight rows; f1's verification command re-run exits 0. MinIO's `undecided` cell has its recorded deferral (#972) in D4, so it counts as filled per the criterion. Amendment notes present in ADR-028 (line 21 ff.) and ADR-037 (line 23 ff.).
- **AC2 (SSOT + demonstrably-red gate)**: **Met, verified fresh with my own mutation.** Full suite `28 passed` (f2's exact command). Red-against-the-real-repo re-demonstrated *by me*: removing grafana's `state_promotion` from `common.yaml` → `1 failed, ... grafana (PVCs: grafana-data): missing 'state_promotion'`; restored byte-identical (`git diff --exit-code` clean). Nine classified blocks found in `common.yaml` (the original eight minus retired MinIO, plus `open_webui` and `hermes_kubelab` added since — the ground-truth-from-manifests design working as intended). The duplication clause landed in #2060 with its own real-render red control (`test_duplication_clause_goes_red_on_the_real_render`, passed).
- **AC3 (both overlays render, staging e2e green)**: **Render half verified fresh**: `kubectl kustomize` exits 0 on both overlays — staging 97 objects, prod 108, zero `minio`/`gitea-data` references, matching `features.json` f3/f4 evidence exactly. **e2e half UNVERIFIED in this session**: the staging cluster is unreachable from here (`dial tcp 172.16.1.10:6443: no route to host`), so `make test-e2e ENV=staging` (recorded 68 passed / 21 skipped on 2026-10-10 against master `f1c952a8`) is accepted as recorded evidence, not re-run.
- **AC4 (pre-deletion emptiness evidence)**: **Partial, honestly recorded.** Both Gitea markers present as `### ` headings (f5 re-run exits 0; renaming a marker turns it red — I checked). Staging MinIO's marker capture was never taken because OPS-023 (#1788) deleted the PVC out from under this spec. **Archive review ruling, recorded here as requested by `verification.md`:** the supersession is accepted for archive purposes — R5's authenticated/observational emptiness check of 2026-08-12 predates the 2026-09-24 deletion, staging MinIO had no consumer at all, its only writer had been failing since 2026-08-25, and the data route moved to R2 via `node_backup` (#1236). AC4's substance (no PVC deleted without prior emptiness proof) holds; its marker-form operationalization for this one instance does not, and `features.json` f5 correctly stays `partial` rather than being reworded as met.
- **Tasks**: all implementation boxes `[x]` with diff evidence I traced to the named commits; the two `[~]` boxes are exactly the staging-MinIO AC4 capture and the `verification.md` AC4 fill, both annotated with why. Round-1's two findings are dispositioned in `verification.md`: AC4 gap accepted as recorded; CC 11 fixed in `4fca806c` — I re-measured with `radon cc`: largest complexity in the file is B (≤10), `classification_problems` now A.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | AC4 / process | Staging MinIO's `AC4-EVIDENCE staging/minio pre-deletion` capture was never taken before OPS-023 deleted the PVC; f5 is `partial`. Supersession accepted per the ruling above. | `verification.md` "PR 3 superseded by OPS-023"; f5 exits 0 only on the two Gitea markers | UNTESTED by design — f5 was narrowed (contract) so no test covers the MinIO marker | spec — no contract edit; ruling recorded in this review, disposition in `verification.md` |
| Minor | REAL | verification | `verification.md`'s AC2 red transcript mutates **gitea's** `state_promotion`; since gitea's retirement (#1062) gitea has no PVC in any manifest, so re-running that exact step today stays green (I reproduced: mutation at gitea's block → `1 passed`). The mechanism still goes red — I re-demonstrated on grafana → `1 failed ... missing 'state_promotion'` — so AC2 stands, but the recorded transcript is no longer reproducible verbatim. | my two mutation runs above, gitea-green / grafana-red | `test_every_stateful_service_declares_a_classification`; `test_manifests_actually_yield_stateful_services` | `verification.md` (outside contract set — add a one-line re-run note) |
| Minor | THEORETICAL | tests | `rendered_pvcs` skips the whole duplication clause when `kubectl` is absent outside CI (fails closed only under `CI=`). A contributor running the suite offline gets a green file without the clause having executed. Explicit, loud skip message; CI is the enforcement point. | code read of `tests/test_stateful_service_classification.py` fixture | `test_no_singleton_renders_in_both_overlays` (skipped path) | tests — disposition only; CI fail-closed already covers the gate |
| Minor | SPECULATIVE | spec artifacts | `features.json` f2 notes name the ConfigMap-generator guard `_PLACEMENT_SUFFIXES`; the implemented symbols are `_PROMOTION_SUFFIX`/`_LOCATION_SUFFIX` in `toolkit/features/generator_k8s.py`. A reader grepping for the noted name finds nothing. Guard itself verified present and covered. | grep of `generator_k8s.py`; `tests/test_k8s_generator_configmap_env.py` 8 passed | `test_k8s_generator_configmap_env.py` | spec (`features.json` note — contract set is closed under this verdict; disposition as cosmetic in `verification.md`) |
| Question | THEORETICAL | enforcement | ADR-061 D3's n8n binding condition (git + `n8n import` is the sole write path) is prose only — no test enforces it, so a UI-authored workflow would silently falsify the `dual` label. Disclosed as "declared doctrine, not yet enforced" and tracked as #501/#688 (`APP-CONFIG-003`); not an acceptance criterion here. | grep: no enforcement test exists | UNTESTED (disclosed, tracked) | tests (follow-up ticket already exists — do not file a duplicate) |

**Code-level checklist over the spec's diff**: no injection (subprocess invoked with fixed argv, no shell), no hardcoded secrets (Ansible reads `{{ gitea_secrets... }}` vault vars), no auth changes beyond the documented OIDC-preserving cutover, no unbounded loops, functions ≤40 lines, all cyclomatic complexity ≤10 (radon, fresh). Nothing to report beyond the rows above.

**Test-deletion scrutiny**: no test was deleted or weakened by this spec's commits. `4fca806c` split `classification_problems` into three helpers — messages verified unchanged by my red run, test count 20 in-file before and after.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All criteria met or dispositioned; the one form-level gap (staging MinIO marker) is honestly `partial` and ruled on above, with substance-level evidence intact. |
| Verification       | B | I reproduced f1, f2 (28 passed), f5 + its negative, both renders (97/108), lint (exit 0), mypy (125 files clean), radon, and a live red/green mutation; only the live-cluster e2e half could not be re-run (cluster unreachable). |
| Scope              | A | The five implementation PRs each touch only their task's files; the base..HEAD range is larger only because the spec shares `master` history, documented in Sources. |
| Reliability        | B | Gate fails closed in CI (kubectl missing, empty render, malformed YAML all handled); local kubectl-less runs skip loudly; subprocess render lacks a timeout (negligible). |
| Maintainability    | A | All CC ≤10 (fresh radon, round-1's 11 fixed in `4fca806c`), helpers ≤40 lines, comments explain WHY, no dead code. |
| Handoff-readiness  | A | Proposal/tasks/verification/features kept current through two review rounds, dispositions recorded, promotion candidates answered, ADR + amendment notes landed. |

### Verdict
PASS WITH GAPS

Open items are minors only, each with a disposition line above; no Blocker, no Major. The two post-round-1 commits (`4fca806c`, `6974af9b`) correctly address round 1's findings and interact cleanly with the early work — the helper split preserved message bytes (verified by re-running the red path), and the disposition record matches what I independently verified.

### Recommended next steps

- (verification.md, outside contract set) Add a note beside the AC2 transcript that its gitea-mutation step predates gitea's retirement, with the grafana mutation as the current re-run recipe.
- (verification.md) Record this review's AC4-minio supersession ruling in the archive checklist, then run `dotf spec archive` — the contract set is closed under this verdict; do not edit `proposal.md`/`tasks.md`/`features.json`.
- (follow-up tickets, already exist — do not duplicate) #2062 (StatefulSet `volumeClaimTemplates` outside the gate), #501/#688 (n8n general promotion path, which is what would turn D3's prose condition into enforcement).
- (cosmetic, disposition only) `features.json` f2's `_PLACEMENT_SUFFIXES` note vs the implemented symbol names — declined or fixed at next contract-touching round, not now.
