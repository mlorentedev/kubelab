---
spec: "TOOL-036-platform-manifest-sync"
verdict: "FAIL"
reviewed_sha: "bfa19d68cf84eef3ce0dbf33101cf984527b0319"
reviewer: "nan/deepseek-v4-flash"
date: "2026-09-05"
---

## Adversarial review

**Scope**: TOOL-036-platform-manifest-sync
**Sources**: `specs/TOOL-036-platform-manifest-sync/{proposal,tasks,verification}.md`,
`features.json`, `toolkit/features/platform_manifest.py`, `toolkit/cli/sync.py`,
`tests/test_sync_platform_json.py`, `Makefile`, `.github/workflows/check-config-drift.yml`,
`infra/config/platform.json`, `infra/config/values/common.yaml`, and the downstream
schema `Projects/web/site/src/data/platform.ts`.

> **Note on HEAD drift during review.** The launcher pinned `reviewed_sha` to
> `bfa19d68` in `review-request.json`. Mid-review a concurrent session committed
> `1fc5996a` ("fix(ci): give the sync check the history its provenance reads") on
> top of it, which is now `HEAD`. `git diff bfa19d68 1fc5996a` is the workflow
> `fetch-depth: 1 → 0` change only; the platform feature code is identical. I am
> signing `bfa19d68` (the pinned target, and what the archive gate's
> `checkReviewProvenance` requires) and flag the follow-up where relevant.

### Spec and task alignment

- **Proposal's core premise (Why/What)**: project `infra/config/values/common.yaml`
  into the sanitized public `platform.json`; compute `activeNodes`, `totalServices`,
  `kubernetesClusters`, `kubernetesNodes` **directly from `common.yaml`**; project
  the 9 nodes, the services catalog, and the architecture diagrams **from the SSOT**.
- **Acceptance criteria (AC1–AC5)** as read from `proposal.md`. The "from
  `common.yaml`" / "compute directly from `common.yaml`" requirements are the heart
  of the spec — they are what make the generated artifact a *manifest* rather than a
  hand-maintained snapshot.
- **tasks.md** marks the implementation boxes `[x]`, but leaves
  `[ ] verification.md filled in` unchecked even though `verification.md` is fully
  populated, and ticks `[AC5] Run … adversarial review` while no `review.md` existed
  at `bfa19d68` — the task list does not track reality. `[ ] PR opened` is correctly
  still open.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Blocker | REAL | SSOT projection | The manifest is **not** projected from `common.yaml`. All node, service, diagram, cluster-count and metric data are hardcoded Python constants (`NODE_METADATA`, `PLATFORM_SERVICES`, `ARCHITECTURE_DIAGRAMS`, `cluster_info`, `metrics`). The only value read from `common.yaml` is `k3s.version`. | Reproduction: appended a new node `brandnew` (tailscale_ip `100.64.0.99`, lan_ip `172.16.1.99`) to `common.yaml` `networking.nodes` and called `generate_manifest(config_path=...)` → node count stays 9, node ids unchanged, `activeNodes` stays 8, `totalServices` stays 35. A SSOT change produces **zero** output change. | `test_manifest_schema_and_counts` asserts the hardcoded values (activeNodes=8, etc.), so it passes *precisely because* the data is hardcoded — it cannot catch SSOT drift. UNTESTED for the SSOT path. | code (derive nodes/services/counts/diagrams from common.yaml) + spec |
| Major | REAL | Data integrity | `cluster.totalServices` is a hardcoded `35`, not computed from `common.yaml` and inconsistent with the manifest's own 14-entry `services` catalog. It silently diverges from the SSOT and from the catalog. | `generate_manifest` sets `"totalServices": 35` as a literal; `len(manifest["services"]) == 14`. Web schema documents `totalServices` as "workloads across all three clusters" — an unrelated number. | `test_manifest_schema_and_counts` only asserts `totalServices >= 14` (a weak bound that cannot catch the 35-vs-14 mismatch or a SSOT change). UNTESTED. | code (compute from common.yaml / services) + tests |
| Major | REAL | CI / provenance | At `bfa19d68` the committed `.github/workflows/check-config-drift.yml` `windows-sync-check` job uses `fetch-depth: 1`, but `_get_commit_provenance` reads `git log -1 -- common.yaml`, which cannot reach the last-touch commit in a shallow clone. Provenance falls back to `datetime.now()` + `0000…0`, so the regenerated manifest differs from the committed one and the job reports drift that does not exist. | Shallow-clone test: in a depth-1 clone, `git log -1 -- infra/config/values/common.yaml` returns the shallow tip, not `6c4e283e` (the true last-touch commit the committed `platform.json` records). The workflow's own comment documents the same measurement. **Addressed by follow-up commit `1fc5996a`** (fetch-depth → 0), which landed mid-review; it was **not** part of the reviewed commit. | `test_git_failure_falls_back_gracefully` covers the git-failure fallback, not the shallow-clone scenario. UNTESTED. | CI (done in `1fc5996a`) + a named regression test for the shallow-clone provenance |
| Minor | REAL | Spec-vs-verification | AC5 requires "100% unit test coverage"; actual coverage is 98% (2 branch misses at `platform_manifest.py` 586→591 and 616→619). `verification.md` itself states "98% branch/line coverage". | `.venv/bin/pytest tests/test_sync_platform_json.py` → coverage report for `platform_manifest.py` = 98%. | `tests/test_sync_platform_json.py` (suite) — UNTESTED for the 2 missed branches. | spec (align AC5 wording / coverage claim) |
| Minor | REAL | Verification | The "schema conformance" test does **not** validate against the actual `site/src/data/platform.ts`; it hand-checks a subset of keys/counts and one enum value. No named test enforces the schema's enum/required-field constraints against future drift. | Read of `test_manifest_schema_and_counts` vs `platform.ts` interfaces. My independent validator (mirroring `platform.ts`) found 0 schema errors in the current data, so it conforms *today* — but nothing guards it. | `test_manifest_schema_and_counts` — UNTESTED for real schema conformance. | tests (add a schema-validation test reading `platform.ts` or mirroring its interfaces) |
| Minor | REAL | Spec-vs-code | `source_commit` deviates from the proposal's literal `git rev-parse HEAD`; the code uses `git log -1 -- common.yaml` (last commit touching the SSOT). Documented in `verification.md` as a deliberate determinism decision, and it satisfies the schema (full git object name), so it is a wording drift rather than a defect. | `_get_commit_provenance` uses `git log -1 --format=%H <file>`; proposal says `source_commit (git rev-parse HEAD)`. | `test_provenance_determinism` checks only the 40-hex format, not the provenance source. UNTESTED. | spec (align wording) — accept as documented |
| Minor | THEORETICAL | Zero-Addressing | The guard detects dotted-quad IPv4 and `.internal/.local/.lan` suffixes only; it does **not** catch IPv6. `common.yaml` declares `networking.ipv6_prefix: fd7a:115c:a1e0::/48`. No IPv6 currently leaks into output, so the gap is latent. | `generate_manifest` regexes: `\b(?:\d{1,3}\.){3}\d{1,3}\b` and `\.(?:internal|local|lan)\b`; no IPv6 pattern. | `test_zero_addressing_sanitization` / `test_zero_addressing_guard_catches_*` — UNTESTED for IPv6. | code (extend guard) or spec (narrow AC to IPv4/CGNAT/RFC1918) |
| Minor | REAL | Maintainability | `generate_manifest` is ~67 lines (repo rule: <40), and `platform_manifest.py` is 696 lines dominated by ~600 lines of hardcoded data that duplicates the SSOT — knowledge duplication that will drift. | `awk` line counts; functions at lines 594–660 (`generate_manifest`), 661+ (`sync`). mypy/ruff pass; `cyclomatic-complexity` of the control functions is low. | `test_*` (none for length) — UNTESTED. | code (refactor projection out of the constants) |
| Minor | REAL | Spec artifacts | `tasks.md` is stale: `[ ] verification.md filled in` unchecked while `verification.md` is populated; `[AC5] Run … adversarial review` ticked with no `review.md` at `bfa19d68`. | `grep` of `tasks.md` vs `verification.md` content. | n/a | spec (tasks.md) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness | D | The core requirement — project and compute the manifest **from `common.yaml`** — is not met; the data is hardcoded, so a SSOT change produces no output change. |
| Verification | C | Commands are reproducible and happy-path/zero-addressing are proven, but the SSOT projection is unproven (it doesn't exist) and the "schema conformance" test doesn't validate the real schema; AC5's 100% claim is actually 98%. |
| Scope | B | Committed diff matches the proposal; the CI `fetch-depth` fix is a separate, uncommitted-at-review-time change (now `1fc5996a`). |
| Reliability | C | Provenance depends on full git history (fragile in a shallow CI clone); the `datetime.now()` fallback makes `--check` non-idempotent when git is unavailable; `totalServices` is a magic number. |
| Maintainability | C | Control functions are clean (CC low, mypy/ruff green) but the module is 696 lines dominated by hardcoded data duplicating the SSOT, and `generate_manifest` exceeds the 40-line rule. |
| Handoff-readiness | B | Spec updates and implementation decisions are documented in `verification.md`; `tasks.md` is stale and the archive checklist is pending. |

### Verdict

**FAIL**

One **REAL Blocker** (the manifest is not projected from `common.yaml` — the
feature's entire premise) plus **REAL Majors** (hardcoded `totalServices`; the
committed CI `fetch-depth: 1` provenance break, since fixed in follow-up
`1fc5996a`). Per the aggregation rule, a single Blocker forces FAIL, and
Correctness grades D.

### Recommended next steps (before archive)

1. **Make the projection real (Blocker).** Derive the node fleet, service catalog,
   cluster counts (`activeNodes`, `kubernetesClusters`, `kubernetesNodes`), and
   `totalServices` from `common.yaml` (its `networking.nodes`, `services`, and
   `k3s` sections), rather than from hardcoded Python constants. Either enrich
   `common.yaml` to carry the hardware/role data or read what it already has
   (`tailscale_ip`, `lan_ip`, `location`, `hostname`, `ansible_groups`,
   `dashboard`), and drop the parallel hardcoded catalogs.
2. **Add a regression test that proves SSOT projection.** A test that mutates
   `common.yaml` (adds/removes a node or service) and asserts the manifest changes
   accordingly — the current suite passes because the data is hardcoded.
3. **Resolve `totalServices`.** Tie it to the derived catalog or `common.yaml`, and
   assert it in a test instead of the weak `>= 14` bound.
4. **Commit the CI provenance fix.** Confirm the PR head is `1fc5996a` (or later)
   so `windows-sync-check` is green; add a named test for the shallow-clone
   provenance fallback.
5. **Spec cleanup.** Align AC5's "100%" claim with the measured 98%; align the
   `source_commit` wording with the `git log -1` decision; tick `tasks.md`
   `verification.md filled in`; optionally extend the Zero-Addressing guard to
   IPv6.

`dotf spec archive` is **not advisable** in the current state: the Blocker and
Majors must be addressed and the review re-run against the resolved head before
the archive gate will (correctly) pass.
