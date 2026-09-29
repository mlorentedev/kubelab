---
spec: "OPS-023-retire-minio"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "c4e09bff413ff2e68713fb4117cf47c4b929e3f6"
reviewer: "nan/mimo-v2.5"
date: "2026-09-28"
---

## Adversarial review

**Scope**: OPS-023-retire-minio, `git diff 490b765be6a9c9104f33d8c9ae0558b18dce206d...HEAD`
**Sources**: `specs/OPS-023-retire-minio/{proposal.md,tasks.md,verification.md,features.json}`;
diff base `490b765b` (verified `git merge-base --is-ancestor` = true, and
`git rev-parse 6abdea1b^` = `490b765b`, i.e. the parent of the spec's first merged commit);
HEAD `c4e09bff` (branch `docs/archive-ops-023`).

### Scope note (read first)

The resolved base is the parent of PR 1, and the range therefore spans **56 commits /
270 files**: the spec's own five commits (`6abdea1b` #1788 PR1, `3f46c450` #1838 PR2,
`30a90cf6` #1880 PR3a, `d7882172` #1890 PR3b, `c4e09bff` evidence) interleaved on master
with **51 commits from other lanes** (gitea/n8n/auth/secrets/deps…). I reviewed the five
spec commits line-by-line as the change under review, and used the *whole* range for the
interaction questions a late fix must be judged against: does the AC5 guard still pass at
HEAD after every later merge, did any other lane re-introduce a live MinIO reference, and
are the generated artifacts still in sync. Those checks are green (Evidence below). I did
not judge other lanes' code for their own specs' criteria.

### Spec and task alignment

- **Tasks**: every box is ticked except the final one (`Independent adversarial review`) —
  which this artifact closes. One tick lacks diff evidence: see F1.
- **Acceptance criteria, re-verified in this session where the environment allowed**:
  - **AC1** — `kubectl kustomize` of `overlays/staging` and `overlays/prod` at HEAD:
    121 / 130 resources, **0** `minio|pvc-backup` matches. Live **prod** (all 6 namespaces,
    `deploy,sts,svc,pvc,cronjob,ingressroute,cm,secret,pv`): clean. **Staging cluster was
    unreachable this session** (`dial tcp 100.64.0.11:6443: i/o timeout`) → staging live
    state rests on verification.md's 2026-09-25 before/after capture (UNVERIFIED now).
  - **AC2** — repo side verified: no `minio`, no `9000/9001`, no `/opt/minio` anywhere in
    `infra/ansible/`, so re-provisioning cannot reinstall it. **Beelink unreachable this
    session** (`100.64.0.3:22` timeout — it is powered off most of the week) → the
    `changed=0` runs in verification.md (2026-09-26 run 2, 2026-09-28 CHECK=1) stand as
    recorded evidence only (UNVERIFIED now).
  - **AC3** — live **prod** probe reproduced: `client_id=minio` → `error=invalid_client`,
    control `client_id=grafana` → `error=invalid_request`. Generated `oidc-clients.yml`
    (both overlays) contain no `minio`. Staging endpoint unreachable → recorded evidence.
  - **AC4** — `make secrets-audit` rerun: **rc=0**, no `minio` key among the orphans
    (the two `[ERROR]` lines are pre-existing expiring GitHub tokens, unrelated).
  - **AC5** — `pytest -k no_live_minio_reference` → **13 passed** at HEAD (no xfail).
    **Mutation proof reproduced**: appending one `MinIO` line to `docs/runbooks/cicd.md`
    turns it red (`1 failed, 12 passed`, offender list names the file); `git checkout` →
    `13 passed`. Independent `grep -ri minio` over the tree confirms every remaining hit
    is an exempt/historical path or the Spanish `dominios`.
  - **AC6** — `make backup-coverage ENV=prod` rerun: beelink / rpi3 / rpi4 / vps all
    `covered`, newest 1.0–3.7h ago.
- **Proposal promises vs diff**: K8s manifests, CronJob, dev stack, SSOT, SOPS keys,
  OIDC client + Authelia rules, DNS records, 3 Uptime Kuma monitors, homepage tiles,
  `renovate.json`, `generator_traefik.py` special cases, `make backup-pvc`, the Beelink
  teardown and `headscale` `tag:hermes → beelink:9000` grant — all present in the diff
  and absent from HEAD. ADR-061 D4 carries the `Resolved: retired` note; ADR-024,
  ADR-028 and ADR-023 carry retirement banners. Task-level promises: **except F1**.
- **Test deletions** (retention bar): the four removed tests
  (`test_minio_root_user_resolves_from_the_identity_ssot`, `test_minio_maps_to_minio`,
  `test_minio_uses_correct_health_path`, `test_minio_secrets_is_declared_retired`) all
  had MinIO itself as their subject; the surviving mechanisms keep named coverage
  (`test_retired_secrets.py` now patches a synthetic entry so the empty
  `RETIRED_SECRETS` list cannot make assertions vacuous; `test_apply_secrets_preview.py`
  does the same; `test_secrets_orphan_audit.py` moved to a synthetic key). The guard's
  own history is documented (`git log -S` on the pattern). No test was deleted to make
  the suite quieter while its behavior survived.
- **No `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tags** in any spec file (grep, rc=1).
- **Security scan of the range**: SOPS files change only ciphertext; the only
  plaintext-shaped additions are obvious test fixtures (`not-a-real-value-fixture…`,
  `pr-agent-test-secret-not-a-real-one`). No credentials, keys or `.env` added.
  verification.md's SEC-023 note (real dev Gitea admin password removed from
  `local-development.md`, rotation ticketed as #1884) is a genuine find, correctly routed.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | spec/tasks integrity | `tasks.md` PR 2 is ticked `[x]` for "Leave the `VPNACL-001` draft's `tag:hermes → MinIO` rule a note on that spec", but none of the five spec commits touches `specs/VPNACL-001-fleet-segmentation/`, whose proposal still presents `hermes → MinIO (beelink:9000)` as a **[RESOLVED]** operator decision with no retirement note. A `[x]` without diff evidence. | `git show --stat` over `6abdea1b 3f46c450 30a90cf6 d7882172 c4e09bff` → no VPNACL path; `grep -rn "OPS-023\|retired" specs/VPNACL-001-fleet-segmentation/` → no hit; proposal.md:37 still lists the dead rule | UNTESTED (no test covers spec prose) | spec artifacts — **outside this spec's contract set**: add the note to `specs/VPNACL-001-fleet-segmentation/proposal.md`, then record the disposition in `verification.md` |
| Minor | THEORETICAL | spec-vs-code (AC5) | AC5 exempts "an ADR, lesson, **archived** spec or changelog"; the implemented guard exempts the **entire** `specs/` tree (active specs too) and `docs/audits/`. Documented in `tasks.md` and in the guard's docstring, but broader than the proposal's wording — an active spec or a current-state audit could carry a live MinIO instruction without failing. No such live instruction exists today (grepped: every exempt hit is history/context). | `proposal.md` AC5 vs `EXEMPT_PREFIXES` in `tests/test_no_live_minio_references.py:39-46` | `test_only_a_document_that_declares_itself_not_current_is_exempt` covers the frontmatter path only → prefix breadth UNTESTED | spec (proposal wording) — **contract set**: do not edit under this verdict; disposition in `verification.md` or a follow-up ticket |
| Minor | REAL | docs drift | ADR-061 **Consequences** still instructs: "Retiring Gitea's PVC requires editing `overlays/prod/backup.yaml` in the **same change**, or the backup CronJob renders…" — that file and that CronJob were deleted by this change. Forward-looking guidance in a live (non-historical) ADR now points at nothing. | `docs/adr/adr-061-stateful-service-placement.md:121` read at HEAD; file absent (`git log --diff-filter=D` / kustomize clean) | UNTESTED (no test asserts ADR file references; `test_runbook_targets_exist` covers runbooks only) | code/docs — outside the contract set; a one-line resolution note beside that bullet, or a follow-up ticket |
| Minor | REAL | docs/config comment | `infra/helm/argocd/values.yaml:185` justifies the `batch_CronJob` health customization with "(pvc-backup CronJobs)"; neither overlay nor either cluster renders a CronJob any more, so the live config comment names a retired referent. | `kubectl kustomize` both overlays → no `CronJob`; live prod `kubectl get cronjob` → none | UNTESTED | code (comment) — follow-up ticket |
| Minor | REAL | quality (CC>10) | `radon cc` at HEAD on `toolkit/features/k8s_secrets.py`: `_build_apprise_config` **D(21)**, `apply_secrets` **C(17)**, `_apply_single_secret` **C(16)** (base `490b765b`: 21 / 14 / 12 — partly pre-existing, partly grown inside this range by the retired-secrets hook and other lanes' preview/shape work). Over the repo's CC threshold. | `radon cc toolkit/features/k8s_secrets.py -s -n B` run this session (output above) | behavior is covered (`test_retired_secrets.py`, `test_apply_secrets_preview.py`, full suite green); the CC property itself UNTESTED | code — follow-up refactor ticket, not this spec |
| Question | REAL | process (disclosed) | PR #1890 (the guard-going-green docs PR) merged with **no review decision**; verification.md discloses it ("PR-Agent published no review in five attempts, TOOL-087 #1909"). Disclosed, tracked — no action beyond keeping #1909 open. | `gh pr view 1890 --json reviewDecision` → `null`; disclosure in verification.md "Test status" | n/a | vault/repo: already ticketed (#1909) |

**Test-traceability gate**: no Blocker or Major was raised, so no UNTESTED gap blocks the
verdict; the five UNTESTED cells above are the gaps this review itself found.

**Live-verification limits (this session)**: staging (`100.64.0.11`) and the Beelink
(`100.64.0.3`) were unreachable, so AC1-staging, AC2-live and AC3-staging are **UNVERIFIED
now** and rest on verification.md's timestamped captures; prod, the repo-side render, AC4,
AC5 and AC6 were all re-run fresh (Evidence below).

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | Every AC reproduced where reachable (prod live, kustomize, guard+mutation, audit, coverage); staging/Beelink live unreachable and negative paths around the exemption prefixes untested |
| Verification       | B | verification.md is unusually concrete (rc, timestamps, before/after, controls) and most of it re-ran green here; a few claims are historical-only because the endpoints are offline |
| Scope              | B | The five spec commits match the proposal with no creep; the launcher's range also carries 51 other-lane commits, so scope was judged per commit rather than per range |
| Reliability        | B | Delete/idempotency/missing-kubectl/dry-run paths of `delete_retired_secrets` have named tests; retirement is one-shot with a documented no-rollback posture; two live endpoints unverified |
| Maintainability    | B | New code small and documented (`delete_retired_secrets` CC7, guard well-explained), but three functions in a touched file measure CC 16–21 (F5) |
| Handoff-readiness  | B | Spec trio + two lessons + ADR notes + decision log are all in place; held back by the unevidenced `[x]` (F1) and the AC5 wording delta (F2) |

Aggregation: no D, no C → all B or above. Severity axis: no Blocker, no Major.

### Verdict

**PASS WITH GAPS** — minors only, rubric all B. Six findings, each tagged with reality
and a named-test-or-UNTESTED cell, none of them blocking; two live-verification windows
(staging, Beelink) could not be reopened from this session.

### Recommended next steps

- Disposition each finding above in `verification.md` (applied / ticketed / declined with
  a reason) — that file is outside the staleness set, so it can take them without
  invalidating this verdict.
- F1 (VPNACL-001 note): add the note to `specs/VPNACL-001-fleet-segmentation/proposal.md`
  (not this spec's contract set) or ticket it; F3/F4/F5: one follow-up ticket each, code/docs.
- F2 (AC5 exemption breadth vs `proposal.md` wording): **do not edit the contract** while
  this verdict stands — record it as a disposition, or carry it as a follow-up ticket.
- When staging and the Beelink are next reachable, re-run `features.json` `f1` (staging
  half) and `f2` to close the two UNVERIFIED windows.
