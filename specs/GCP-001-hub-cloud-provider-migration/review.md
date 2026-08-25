---
spec: "GCP-001-hub-cloud-provider-migration"
verdict: "FAIL"
reviewed_sha: "45e0c9008bf383353a7548e7c21fe1db97cd18a7"
reviewer: "nan/deepseek-v4-flash"
date: "2026-08-25"
---

## Adversarial review

**Scope**: GCP-001-hub-cloud-provider-migration
**Sources**: `specs/GCP-001-hub-cloud-provider-migration/{proposal,tasks,verification}.md`,
`infra/terraform/gcp/{main.tf,cloud-init.yml}`, `infra/config/values/common.yaml`,
`tests/{test_gcp_cloud_init,test_gcp_mig,test_headscale_nodes,test_gcp_hub_module}.py`,
commits from `cf5f98f^` to `45e0c90` (reviewed HEAD).

### Spec and task alignment

- **Contract files unchanged at reviewed sha.** `proposal.md`/`tasks.md`/`features.json`
  are at `45e0c90`; no staleness risk against the review. (No `features.json` exists —
  this spec uses the proposal/tasks/verification triad.)
- **No `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags** in any spec file — the pre-archive gate
  is not the reason archive is blocked.
- **Task `[x]` claims vs diff:** nearly every `[x]` carries a `✓ sha/PR` and a named test
  (cloud-init bring-up → `test_gcp_cloud_init.py`; MIG/RESOLVE → `test_gcp_mig.py`;
  SOPS→SM sync → `test_secret_manager_sync.py`; portability → `test_gcp_hub_module.py`).
  The pattern holds; I found no `[x]` without diff evidence.
- **Acceptance criteria status** (as evidenced in `verification.md`, which is unusually
  honest): AC1 ✓, AC2/AC2b ✓ (kill switch fired through the real topic), AC3 ✓ (forced-sync history, 93 resources), AC5 ✓ (scored), AC6 ✓ teardown + rotation, AC7 ✓,
  AC8 [~] partial (wall-time deferred). **AC4 — satisfiable only partially**, details
  below. That is the crux.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Blocker  | THEORETICAL (incident itself is REAL) | AC4 — self-heal of the MagicDNS given-name | The design's load-bearing claim — *re-registers under the SAME given-name, no human action* — is **not demonstrated against the event AC4 stands for**. The live real preemption (2026-08-24) FALSIFIED it: the OLD stale-recycle predicate `.online==false` never matched (proto3 omits `false`, so `null==false` selects nothing), the replacement registered as `gcp1-mj5bsge9`, `gcp1.kubelab.internal` sat on a corpse, and `argo.kubelab.live` went down. The fix (drop `.online`, accept both spellings) is present and statically tested, BUT (a) it only takes effect on the next `terraform apply` (template change replaces the hub), and (b) the very PR that lands it states **AC3/AC4 of #1369 "stay open"** — a graceful delete cannot distinguish the fixed code from the code it replaces. Every Phase 4 task in `tasks.md` (delete the instance; `dig` the name; count human steps; repeat) is still `[ ]`. So the one claim the regional MIG exists for is not yet proven on the branch that triggered the incident. Note on reality: the incident itself is REAL and reproducible (log 17:13:39→17:13:57), but the CURRENT code's behaviour on that path is only reasoned, not yet observed → the stepping blocker is the unverified-fix class, which I grade Blocker because AC4 is an unsatisfied core acceptance criterion, not a soft gap. Root-cause evidence in the file tells an internal reviewer they were claimed "closed in code" for F1 once and got burned; AC4 has the same silhouette. | Tests cover the tool logic (`test_an_offline_node_omits_the_online_field_and_still_parses_as_offline`, `test_the_live_incident_produces_the_expected_plan`) and boot static (`test_argo_cd_is_installed_not_merely_namespaced`), but **no named test / live drill exercises end-to-end: abrupt preemption → MIG recreate → auto-reclaim `gcp1` → Synced with zero human steps**. UNTESTED for the load-bearing branch. | code (already landed) + tests + **live preemption drill** (simulate abrupt kill, not a graceful terminal), record name + Synced + human-step count |
| Major | REAL | AC8 — measured ceilings | **`make deploy-argocd` wall time remains unmeasured.** AC8 in `proposal.md` requires all three ceilings "measured, not assumed." Egress and disk IOPS are measured (2026-08-24); the wall-time is explicitly deferred to the next legitimate deploy (#1209), because running prod to collect a baseline inverts the risk (#1348). This is a *stated, defensible* decision, but it leaves a named AC8 clause (an observation-dependent criterion) UNFULFILLED at archive time. Not a defect — a documented deferral. | verification.md `[~] AC8` / "deferred as a decision", cost-envelope `UNVERIFIED` cleared for tier only | UNTESTED (no value; a live deploy is the test) | spec/verification once measured |
| Major | REAL | Regression debt — `make test-infra` red | The suite is red on master: 6 failures, all `kubelab-aws1` SSH timeouts, because `networking.aws` still declares a live `always-on` node referencing the instance AC6 destroyed (kept deliberately per #1333 / #1182, a documented tension). `tasks.md` closing checklist carries "`make test` green; lint and type checks pass" as an open item, and it is not green today. Tracked #1365. Confirmed by record (f7b518 "red, before and after"). | f7b518 commit verification + `make test` (unit 1409p/15s) vs `make test-infra` red | UNTESTED (integration; currently failing) | config/tests — retire the destroyed-node declaration or note the barrier ; #1365 |
| Minor | THEORETICAL | credential drift — Argo admin password | The four *AWS* exposed credentials are confirmed neutralised (3 Headscale keys expired at issuer, IAM key deleted, #1353/#1349/#1335), and the residue is ticketed #1351 (#SSOT-025). What is NOT addressed: `argocd.admin_password` was present in the audit table "byte-identical to 2026-08-15" and is not among the rotated set. If it was part of the 2026-08-20 exposure corpus, it may still be live. The verification reads it as *drift* (SOPS-vs-hub divergence) either way — a real residual. Not the spec's AC1-AC7 obligation. | verification cred-table rows + #1351 | UNTESTED | operator/confirmation (Question) |

Reality note on the Blocker: skill defines THEORETICAL as "concrete plausible failure path, never observed". The *current-code gap* fits that; the *incident* fits REAL. Combined, this cannot be waved off. Since AC4 is a core acceptance criterion, this is Blocker independently of the label detail.

### Positive strengths that mitigate the finding (not praise — direct evidence)

Two things materially cap the blast radius and are cited because they reduce what the Blocker blocks, not to soften its status:
- The whole bootstrap is bounded and unattended-safe: every network call bounded (F1), no secret on argv/log, one-shot preauth minted with `--no-retry` to avoid orphan keys, single-retry under idempotent reads only. That is why a recreate resurrects the hub's Argo CD rather than hanging silent.
- The failure was *measured, recorded and fixed in code* at the source, with the actual live payload fixtured verbatim and named defensive tests. The remaining artifact is the missing drill (observe the fix on a real preemption), not missing diagnosis.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | C | 6/7 ACs with strong forced evidence; AC4 (the core design claim) is unmet and unverified-against-its-event; one deferred AC8. |
| Verification       | B | Evidence is reproducible, command+output, and honestly adversarial (the "tenth false green" and the falsified AC4 half / the IOPS note are gold), but AC4's live drill and AC8 wall-time are absent. |
| Scope              | A | Diff tracks the three-column contract; net-new vs touched only by naming is respected; deliberate non-genericisation documented. |
| Reliability        | A | Error paths adversarial, idempotent (provision twice → changed=0), rollback preserved (paused hub), secrets-on-files discipline. |
| Maintainability    | A | Dense WHY comments, ≤40-line functions, no dead code; the drift tests span past sections and catch smells. |
| Handoff-readiness  | C | Lessons 354/355, ADR-063/documentation updated; but ADR-063 `proposed→accepted` open, test-infra red, AC4 drill still pending, AC8 deferred. |

### Verdict
FAIL

### Recommended next steps (before archive)
1. **Close AC4 with an abrupt-path drill, not a graceful one**: kill the MIG instance via a path that does not let Tailscale log out (e.g. a simulated preemption), then observe: `dig +short gcp1.kubelab.internal` resolves to the new node's address, zero human steps between kill and Synced, both Applications at Synced (with forced-sync history ≥2, per the criterion's own "empty history ≡ false" rule), repeat once, and record whether the address rotated. Do not tick AC4 on the template-change recreate.
2. **Close AC3/AC4 of #1369** with the drill's evidence; it is the single gating event.
3. **Measure wall time on the next legitimate deploy** (#1209, chart is two majors behind) and record it in the AC8 table; edit ADR-063/`gcp-cost-envelope.md` only if it regresses AWS baseline.
4. **Settle the `make test-infra` red** (#1365) or close the closing gate; the repo should not be archived with a known-red suite labelled as debt.
5. **Confirm-by-consequence** whether `argocd.admin_password` was in the 2026-08-20 exposure and, if so, rotate it (issue or Question disposition, not auto).
6. Move the closing metadata: ADR-063 `proposed→accepted`, close #1066 and the Argo-password question with a written reason.

**Minimum to flip FAIL → PASS**: repeat #1 (a real abrupt-preemption drill that reclaims the name, returns to Synced with zero human steps) + record the AC8 wall-time (or a written reason-plus-owner, as already done). The failure here is honest and rare: the contributor's own acceptance criteria are higher than the state, and the gate should hold until the measured claim holds.
