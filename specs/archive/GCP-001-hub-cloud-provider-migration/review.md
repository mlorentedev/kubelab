---
spec: "GCP-001-hub-cloud-provider-migration"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "29acb61c776ae1ec9ac56ac2466682e38b6864d8"
reviewer: "nan/deepseek-v4-flash"
date: "2026-08-25"
---

## Adversarial review

**Scope**: GCP-001-hub-cloud-provider-migration
**Sources**: `specs/GCP-001-hub-cloud-provider-migration/{proposal,tasks,verification}.md`,
`tests/{test_headscale_nodes,test_gcp_cloud_init,test_gcp_secret_sync,test_gcp_tfvars,test_gcp_mig,test_provision_gcp1_playbook,test_gcp_hub_module,test_gcp_preemption}.py`,
`infra/terraform/gcp/cloud-init.yml`, `docs/adr/adr-{063,023}-*.md`,
commits `cf5f98f^..HEAD`.

### Spec and task alignment

- **Contract files unchanged at reviewed sha.** `proposal.md`/`tasks.md` are at
  `HEAD`; no `features.json` exists (this spec uses the triad). No staleness
  risk against this review.
- **No `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags** in any spec file — this is not
  the reason archive is blocked.
- **Task `[x]` claims vs diff:** every migration-core `[x]` carries a `✓ sha/PR`
  and a named test. I found no `[x]` without diff evidence. The SOPS→Secret
  Manager sync, the pinned-chart bring-up, the `provision-gcp1` playbook and the
  MIG/RESOLVE work all have dedicated test files that I ran green.
- **Acceptance criteria status** (as evidenced in `verification.md`): AC1 ✓, AC2/AC2b
  ✓ (kill switch fired through the real topic, 10.7s detach), AC3 ✓ (forced-sync
  history, 93 resources), AC5 ✓ (scored with real counts), AC6 ✓ teardown +
  rotation neutralised at source (#1335/#1349/#1353), AC7 ✓ (ADR-023 supersession
  marker at the section), AC4 ✓ **now — closed by a matching-stimulus drill, see the
  findings table**, AC8 [~] partial (wall-time deferred, owned).

  The prior independent review (verdict FAIL) was Blocker'd on AC4: *"the design's
  load-bearing claim is not demonstrated against the event AC4 stands for; a
  graceful delete cannot distinguish the fixed code from the code it replaces."*
  **That Blocker is now resolved in HEAD** (this is the material change since the
  last review): the preemption fix landed, and commit `e5f8551` (#1386) closes AC4
  with a drill whose stimulus (`gcloud compute instances stop`, producing STOPPING)
  matches GCP's own logged reasons string for a real preemption; the node
  re-registers under the canonical name with zero human steps between stop and
  reclaim, and the recycle-predicate fix is guarded by passing regression tests
  (`tests/test_headscale_nodes.py`). Two other prior Majors are cleared: the
  `kubelab-aws1` SSH `test-infra` failures (#1365) are gone — HEAD commit `29acb61`
  (#1391) is precisely the fix that retires the destroyed-node declaration, and I
  confirmed the six aws1 timeouts are no longer present.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | REAL | AC8 — measured ceilings | **`make deploy-argocd` wall time is not yet measured.** AC8 in `proposal.md` requires all three ceilings measured; egress (4.5 GiB/mo, $0) and disk IOPS (3209/3233 vs the 3000 spec) are measured, but wall-time is explicitly deferred to the next legitimate deploy (`#1209`, chart two majors behind) and the last real run died mid-phase (`#1348`). This is a **documented, owned deferral** — not a defect — but it leaves one clause of a named acceptance criterion unfulfilled while the AC8 line reads `[x]`. The prior review already accepted the written-reason-plus-owner form, so this is negotiated at the closing gate, not a derailer. | `verification.md` AC8 "deferred as a decision"; egress/IOPS rows dated 2026-08-24; `make deploy-argocd` wall-time row empty | UNTESTED (a live deploy *is* the test; the responsibility is the recording) | spec / verification once measured |
| Minor | REAL | Spec-internal contradiction in AC4 narrative | `verification.md` closes AC4 ("zero human steps between the stop and the reclaim") and one line later says *"recovery is still **not** hands-free: `argocd-repoint`, a re-trusted SSH host key (#1380) and a fresh cluster CA were all needed afterwards."* A strict reader cannot tell from that file alone which claim bounds AC4. The two are compatible — spoke reconciliation (the AC4 claim) self-heals, while the inbound UI route (`argo.kubelab.live`) and operator SSH trust are explicitly out of AC4's scope per `tasks.md` Phase 2 — but the bound is not stated where it is claimed. This is exactly the false-green trap the file spends a thousand words hunting. | drill block verbatim | UNTESTED (no code path to test; documentation-only) | spec (`verification.md` AC4) |
| Minor | REAL | Closing gate not fully green | `make test-infra` still reports 2 failures at HEAD (`tests/infra/test_k3s.py::TestK3sCluster::test_pvcs_bound`, `tests/infra/test_rate_limit.py::TestEveryLiveRouteIsRateLimited::test_every_route_references_rate_limit` — gitea route lacks the rate-limit middleware). These are **not caused** by GCP-001 (PVC-bound PVCs; a gitea route in the staging mesh), so they are not a migration regression, and the migration-caused `kubelab-aws1` failures are gone. But the closing box "`make test` green; lint and type checks pass" is not literally met, and the two failures sit in a different repo area (`tests/infra/`). | I ran `make test-infra ENV=staging`: `2 failed, 55 passed, 1 skipped`, both named above. HEAD commit `29acb61` (#1391) says `26 passed` on its own branch with the fleet on. | `test_pvcs_bound` / `test_every_route_references_rate_limit` (failing, not covering) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness | C | Every AC's core is now met and the prior Blocker (AC4) is closed by a matching drill, but AC8 has one clause (wall-time) unfulfilled and the AC4 verification narrative contains an internal hands-free tension. |
| Verification | B | Strongly honest and reproducible forced-sync evidence, drill logs, IOPS/egress measurements; AC8 partial and the wall-time is owned-not-done. |
| Scope | A | Diff respects the three-column contract; deliberate non-genericisation (#1182) documented; no creep. |
| Reliability | A | Idempotency proven (`changed=0`), rollback via paused hub, secrets-off-argv discipline, bounded retries; SE-verified drill. |
| Maintainability | A | Dense WHY comments, small functions, drift tests that survive refactors. |
| Handoff-readiness | C | Lessons 354/355, ADR-023 superseded and ADR-063 written, but ADR-063 still `proposed` (Closing task open) and AC8 / `test-infra` gating items remain open. |

### Verdict
**PASS WITH GAPS**

### Recommended next steps (before archive)

1. **Decide/finish AC8**: either measure `make deploy-argocd` wall time on the next
   legitimate deploy (#1209) and record it, or formally convert AC8's wall-time
   clause to a deferred acceptance line with an owner. If left pending, that alone
   keeps the verdict at PASS WITH GAPS.
2. **Resolve the AC4 hands-free wording in `verification.md`**: state in one line
   what AC4 covers (auto spoke reconciliation to Synced) and what it does not
   (inbound UI and SSH trust), so a later session — or a real preemption — cannot
   be read as either a pass or a false alarm.
3. **Triage the two residual `test-infra` failures** (PVCs, gitea rate-limit) — not
   GCP-001's, but they block the stated closing gate. Fix or annotate.
4. **Drive ADR-063 `proposed → accepted`** and tick the Phase 6/Closing boxes in
   `tasks.md` (close `#1066` as `wait`, comment the coupled issues).

**Minimum to flip PASS-WITH-GAPS → PASS**: close the AC8 wall-time decision and
resolve the AC4 wording. Neither is a code defect; the previously-Blocker'd AC4 is
demonstrated by a real matching drill now in HEAD. Archive is **advisable** once
AC8 and the two `test-infra` triages are dispositioned — but not before, because
`verification.md` still, in the same block, both passes and fails AC4's most
literal reading.
