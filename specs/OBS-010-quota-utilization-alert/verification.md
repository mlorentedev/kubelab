---
tags: [spec, verification, templates]
created: "2026-08-14"
---

# Verification - OBS-010-quota-utilization-alert

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] Criterion 1 (emitter: CronJob, RBAC, correct per-dimension log lines) -> commits `42fb710`/`352b4d9` / tests `TestQuotaWatcherRBAC`, `TestQuotaWatcherEmitter` (`tests/infra/test_quota_alerting.py`) — staging, 5/5 passing
- [x] Criterion 2 (two Grafana rules, provisioned, correct config) -> commits `1b53373`/`e09d530` / test `TestQuotaUtilizationRules` (`tests/infra/test_grafana_alerting.py`) — staging, 3/3 passing (8/8 whole file, zero regression on OBS-007's own tests)
- [x] Criterion 3 (routine surge does not fire) -> first pass FAILED for real (caught a genuine bug, fixed in commit `6cef9a4`); re-verified clean post-fix 2026-08-14, staging (see Test status below)
- [x] Criterion 4 (killing the emitter fires the alert, noDataState proven live) -> exercised 2026-08-14, staging (see Test status below)
- [x] Part 4 — prod (spoke RBAC registered, quota-watcher and its RBAC live) -> 2026-08-14, once aws1 returned (see Test status below)

## Test status

- `poetry run pytest tests/infra/test_quota_alerting.py -m infra --env staging` -> 5 passed, run 3x consecutively to confirm the concurrency-tolerance fix (below) holds, 2026-08-14
- `poetry run pytest tests/infra/test_grafana_alerting.py -m infra --env staging` -> 9 passed (5 OBS-007 + 4 OBS-010, includes the `last_over_time` regression guard), 2026-08-14
- `poetry run pytest --deselect tests/test_monitoring_integration.py --no-cov` (full suite, pre-existing out-of-lane flake deselected per #1038) -> 500 passed, 2026-08-14
- `make test-infra ENV=staging` -> 35 passed, 6 failed, 1 skipped. **All 6 failures are pre-existing and unrelated to this diff**: `test_network.py::test_tailscale_ping_all_nodes` and all of `test_nodes.py::TestNodeHealth` fail because `aws1` (the Argo CD hub) is unreachable — confirmed independently via `tailscale status` (reports "offline, last seen 3h+ ago", predating this session's OBS-010 work), `tailscale ping` (timeout), and a direct SSH attempt (connection timed out). This diff touches no ansible/networking/hub files. Flagged to the user rather than fixed or ticketed silently — see the session's closing summary; Part 4 (`make register-spoke ENV=prod`, which writes to the hub) was blocked until aws1 returned. **Resolved 2026-08-14** — aws1 came back and Part 4 ran; see § *Part 4 — prod* below. The outage itself is ticketed as #1066.
- Manual smoke test (surge, AC3) — **first pass FAILED the criterion for real, not just in theory**: reproduced IDP-031's exact drill (`kubectl rollout restart` on all 14 `kubelab` deployments, immediately followed by an on-demand `quota-watcher` trigger to catch a mid-restart reading). Captured `limits.memory` at **88.39%** (`used_mi=6336`, `hard_mi=7168`) — comfortably over 80% and closely matching IDP-031's own 87.5% measurement. All 14 rollouts completed cleanly (do-no-harm), quota usage returned to baseline (`limits.memory: 4992Mi/7168Mi` = 69.6%) within a minute — but polling the rule's live state every 90s for 15 minutes afterward (`/api/prometheus/grafana/api/v1/rules`, port-forward + admin auth) showed it go `inactive` → `pending` (01:03:20) → **`firing`** (01:08:20), and it was still `firing` 13+ minutes later. Cross-checked against the raw Loki log lines and a direct re-run of the rule's own LogQL: the underlying value had genuinely returned to 70.54% within 5 minutes, yet `max_over_time(...[10m])` kept reporting the stale 88.39% peak to every evaluation until the spike physically aged out of the 10-minute window — the `for: 5m` sustain check was being satisfied by the window's own memory, not by a real sustained condition. Root-caused, fixed (`max_over_time` → `last_over_time`, commit `6cef9a4`), locked in with `test_query_uses_last_not_max_over_time`, and **re-exercised clean** (see below) before this criterion was marked done.
- Manual smoke test (surge, AC3) — **second pass, post-fix, clean**: the previously-`firing` state persisted through the Grafana pod restart (alerting state lives in Grafana's own database, not memory) and needed one more real evaluation cycle to clear (`firing` → `inactive` at 01:28:20, watched for 3+ minutes stable afterward) — that persistence-across-restart behavior is itself worth knowing, not a defect. With the state confirmed clean, repeated the identical drill (rollout restart of all 14 deployments + on-demand `quota-watcher` probe): captured the same peak, `limits.memory` 88.39%. This time both rules went `inactive` → `pending` (05:08:20) — including `requests.memory`, whose captured probe read only 74.22% but a later natural scheduled tick apparently caught a higher concurrent reading, consistent with the restart's timing being spread across 14 deployments — and resolved cleanly to `inactive` (05:13:20/05:18:20) once the 5-minute window elapsed with no sustained breach. Neither rule reached `firing`. `pending` is the correct, expected transient state for a real-but-short breach; only `firing` triggers Apprise delivery.
- Manual smoke test (fault injection, AC4): suspended `quota-watcher` (`kubectl patch cronjob ... suspend:true`) in staging. Once the last real log lines aged out of the 10-minute LogQL window with no new ones arriving, both rules transitioned to `firing` (`noDataState: Alerting` proven live, not just configured). Un-suspended and immediately triggered an on-demand run to seed fresh normal data (60.16%/71.43%, both dimensions) rather than wait for the next scheduled tick; both rules resolved to `inactive` at 06:23:40 once a fresh evaluation picked up the new data. Confirmed the CronJob was left un-suspended afterward. Reliability note: initial attempts to poll rule state used `kubectl port-forward` in the background, which repeatedly died mid-wait (VPN blips coinciding with long-running background shells); switched to a single synchronous `kubectl exec ... wget` call per check (the same pattern the runbook itself documents) and a `Monitor` until-loop for the final wait — no further failures.
- No regressions in existing test suite: yes — `TestAlertDelivery`/`TestAcmeAlertRule` (OBS-007) both still 5/5 after this spec's ConfigMap and Grafana-restart changes.

### Part 4 — prod, 2026-08-14

**Before.** aws1 returned (`make check-spokes` → both spokes `OK (registered + reachable)`), and prod's Application immediately surfaced the gap this task predicted. `make check-apps`:

```
kubelab-prod      OutOfSync     Progressing
--- kubelab-prod conditions ---
Failed last sync attempt: error running rbacReconcile: error running kubectl auth reconcile:
roles.rbac.authorization.k8s.io is forbidden: User "system:serviceaccount:kubelab:argocd-manager"
cannot create resource "roles" in API group "rbac.authorization.k8s.io" in the namespace "kubelab",
[...same for rolebindings...] (retried 5 times).
```

This is the live confirmation of the preflight recorded in `tasks.md` (all three grants `no` in prod). It is Argo CD refusing what the spoke was not authorized to write, i.e. the TOOL-029 safeguard behaving correctly — not a defect introduced by this spec.

**Action.** `make register-spoke ENV=prod`. The applied delta was exactly the one grant this spec added, and nothing else:

```
clusterrole.rbac.authorization.k8s.io/argocd-manager-write configured
serviceaccount/argocd-manager unchanged
clusterrole.rbac.authorization.k8s.io/argocd-manager-readonly unchanged
rolebinding.rbac.authorization.k8s.io/argocd-manager-write unchanged
clusterrole.rbac.authorization.k8s.io/argocd-manager-cluster-write unchanged
  kubelab: writes OK / cluster: reads OK
✓ Spoke prod registered in Argo CD hub
```

**After.** `make sync-app APP=kubelab-prod`, then the Application's per-resource status on the hub. The failure condition is gone and every resource this spec ships is `Synced` in prod:

```
ResourceQuota    kubelab-quota            sync=Synced
ServiceAccount   quota-watcher            sync=Synced
CronJob          quota-watcher            sync=Synced
Role             quota-watcher            sync=Synced
RoleBinding      quota-watcher            sync=Synced
```

`Role` and `RoleBinding` are the two kinds that were `forbidden` above, so this is end-to-end proof rather than a config assertion.

**Deviation from the task text, stated rather than glossed.** The task prescribed `make register-spoke ENV=prod` *then* `make deploy-k8s ENV=prod`. Only the first ran. `deploy-k8s` carries an interactive production confirmation (`toolkit/features/validation.py:62`) with no bypass flag — correct by design — and it proved unnecessary: with the grant in place, Argo CD's own automated sync applied the manifests. That is the stronger evidence of the two, since it exercises the GitOps path this spec actually depends on rather than a workstation apply.

**One unrelated resource kept prod `OutOfSync` afterwards; resolved on the operator's explicit call.** Exactly one of prod's 91 resources was out of sync: `PersistentVolumeClaim gitea-data`, a leftover of the ADR-061 Gitea cutover which Argo wanted to prune and could not. Three `Succeeded` backup Job pods created *before* the cutover (`2026-08-13T03:00`, `2026-08-14T00:22`, `2026-08-14T03:00`) still referenced the claim, and the `kubernetes.io/pvc-protection` finalizer blocks deletion while any pod does. `overlays/prod/backup.yaml` was already correct — it no longer mounts `gitea-data` (see its own comment) — so this was historical pod residue, not manifest drift.

Why it was not left alone: a permanently `OutOfSync` prod is an uninformative one. Any future real drift would have hidden behind this single stale row, which is the same signal-degradation problem filed as #1072 (TOOL-034).

Deleting the three completed Jobs released the claim (`get pods` → no pod references `gitea-data`), and Argo pruned the PVC on the next sync (`persistentvolumeclaims "gitea-data" not found`). **Prod is now `Synced`, 90/90 resources, 0 out of sync, 0 non-Healthy.** The prune destroyed the pre-cutover Gitea data — irreversible, done on the operator's explicit instruction after the trade-off was stated, not as a side effect of this verification.

Two observations recorded while doing it, neither belonging to this spec:

- `quota-watcher` is running on schedule in prod and succeeding (Jobs at `00:50`, `00:55`, `01:00` all `succeeded=1`) — independent confirmation that Part 4 is live rather than merely applied.
- Three `pvc-backup` Jobs from June (`29674260`, `29675700`, `29677140`) sit in prod with neither `succeeded` nor `active` set. They did not block the PVC and were left untouched — they are the only surviving evidence of those June failures. A backup Job that never reported success and went unnoticed for two months is exactly the gap #686 (NOTIFY-007) item (b) already describes: "PVC backup CronJob failure currently emits NOTHING". Recorded there with the transcript rather than filed as a duplicate. Recent runs succeed, so this is an observability gap, not a live outage.

- **AUTH-002 (#951) prod-test skip** applies here identically to how it already affects OBS-007's prod tests. Cited per the task, not re-diagnosed.

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- **A brand-new Role + RoleBinding pair, applied through the impersonated dry-run path, needs the `bind` verb — not just create/update/patch/delete.** Not anticipated when drafting `proposal.md`'s Risks section (which flagged the RBAC preflight generally, but not this specific escalation-check mechanic). K8s's privilege-escalation check fetches the referenced Role to compare granted permissions; under `--dry-run=server` that Role was never persisted in the same batch, so the fetch 404s and the RoleBinding is rejected as `NotFound` — a response that does not read as an RBAC gap on first sight, since `Forbidden` is the expected shape for a missing grant. `bind` on `roles` authorizes the reference directly and skips the comparison. Cluster-admin (used by `make register-spoke`) never hits this, since escalation checks are skipped for identities that already hold every permission there is — which is exactly why this was invisible until the impersonated path was exercised.
- **A YAML literal block scalar's indentation contract doesn't know about shell line-continuation conventions.** Splitting the emitter's `echo` across two physical lines for readability (backslash-continuation inside a double-quoted shell string) put the second line at column 0, which broke the surrounding `|` block's indentation rule — kustomize failed with a parse error before the manifest was ever deployed, not a runtime failure. Fixed by re-indenting the continuation line to match the block; the extra leading whitespace this puts inside the JSON string is harmless (it lands after a comma, valid JSON whitespace), verified both with a standalone `json.tool` check and a `kustomize` parse before redeploying.
- **The emitter's own test triggers a real, bounded confound in the quota it's reading.** `test_run_emits_correct_utilization_per_dimension` creates a throwaway Job from the CronJob to exercise it, and that Job's own pod (32Mi request / 64Mi limit) is Running and self-counted in the quota at the exact moment the emitter queries it — while the test's "expected" snapshot was taken before the Job existed. First run failed by exactly 32Mi, which is diagnostic rather than mysterious: it's the emitter's own declared request, verbatim. Fixed with an assertion bounded by the Job's own known footprint (`_SELF_FOOTPRINT_MI`), not a blind widening — the same principle as IDP-031's terminal-pod exclusion fix, applied to a self-referential rather than an external confound.
- **That same test flaked once more, for a related but distinct reason**, caught by running it 3x in a row during closing verification: `concurrencyPolicy: Forbid` on the CronJob only governs jobs the *CronJob controller* schedules — a manually created `kubectl create job --from=cronjob/...` job (this test's own) is not one of those, so it can genuinely overlap with a naturally scheduled tick, doubling the self-referential footprint. Widened the tolerance to `2x` the single-job footprint (`_MAX_CONCURRENT_RUNS`), with the mechanism documented in the test itself rather than just picking a bigger number.
- **The verification drill kept killing its own long-running background checks.** Multiple attempts to poll Grafana's rule state via a backgrounded `kubectl port-forward` inside a loop died partway through (exit 144), correlating with observed Tailscale connectivity blips during this session. Switched to the pattern the runbook itself now documents — `kubectl exec deploy/grafana -- wget` with a hand-built Basic auth header, one synchronous call per check, no backgrounded port-forward to lose — which proved reliable for the rest of the verification.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons.md`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/<feature-id>/` -> `specs/archive/<feature-id>/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
