# Run ap-20261102-kubelab-obs

Armed 2026-11-02T05:55Z, expires 17:55Z. Envelope: `.agent/unattended.yml` at f951fc7.
Paused 06:05Z-07:10Z by a usage limit; the wake-lock held.

## Items

- #2929 OBS-042: spec opened with `--over-wip-limit`. PR 1 (notice title, cause, runbook) merged as #2987 (`61631c2`); prod Synced at 09:32Z. Proven by delivery from a local grafana-oss:13.0.2 and in staging: slot pointed at the branch 08:51Z, `make drill-pvc-unbound ENV=staging` fired after 38.2 min, #ops-log got `[staging] FIRING: PersistentVolumeClaim unbound or failed` with runbook and source at 09:30Z; slot returned to master. A real prod notice with the new title has not been seen yet (none manufactured: no prod drill at night).
- #1668 + #1320: PR 3 is #2991, draft: the PVC rule split (`noDataState: OK` plus a new ungrouped liveness rule) and a fleet-wide emitter-window guard at floor 2. Held as draft until #2987 lands and a prod notice with the new title is seen. #1668 AC1/AC2/AC4 need daytime staging measurements.
- #2924: all eight pages attributed (second comment on the issue). Apprise prod, 5 days: 68 deliveries, 6 from Grafana, 62 from the n8n router. The six `page` ones are rpi4 `kubelab-edge-liveness` fail/recover pairs (Wi-Fi radio flapping, already #2682); the other two plus 10-31 17:38Z are `deploy` notices. No Grafana rule fired on a single sample, so no rule ticket. The record has to live at Apprise or the router, not in Grafana.
- #2921 AI-030: #2992 (fetch timeout, stale threshold, exit 75, `LC_ALL=C` so the unreachable-remote match is locale-proof). Provisioned twice from the branch after merging master: run 5 changed=3, run 6 changed=0. Merged as #2992 at 09:50Z after triage (pr-agent's 6h-window finding declined: `kubelab-notify` posts once per incident plus hourly reminders). #2921 stays open for AC3.

## Prod and staging reads

- 05:58Z kubectl get deploy (staging grafana, apprise; prod grafana image): reachability check only.
- 07:05Z `make alerts ENV=staging`: nothing firing.
- 08:51Z-09:35Z staging slot on `feat/obs-042-notice-contract` (read master first; returned to master).
- 09:20Z-09:40Z prod Loki reads of `apprise`, `grafana`, `traefik` (redacted, counted first) and #alerts in Slack, for #2924.
- 07:40Z prod Grafana `/api/annotations?type=alert`, 2026-10-26..11-02, through the toolkit's port-forward and read-only alerts token.

## Prod changes

- `make provision NODE=ace2 ENV=prod TAGS=agent_stack` from the #2921 branch (the tag also runs `node_maintenance`, which the playbook files under it). The first pair ran from a branch older than #2947 and reverted its Open WebUI env on ace2 (disclosed on #2947). Runs 3/4 were refused by the provision gate (checkout behind origin/master). After merging master: run 5 changed=3 (Open WebUI env, Open WebUI restart, vault mirror script), run 6 changed=0, so ace2 now carries #2947 and #2992 together.

## Waiting on the operator

- #1320: the emitter-window floor is 2 samples; 3 (the R2 guard's bar) turns the disk, quota and edge rules red.
- `obs015-disk-root-saturation` still alerts on two causes; splitting it like the PVC rule is a call to make.
- #1710 severity routing; #1668 AC1/AC2/AC4 need daytime staging measurements; #2921 AC3 root cause needs a journal read on ace2.

## Later in the run

- #2991 out of draft at 10:27Z. pr-agent reviewed; the vacuous-guard finding applied (`d4c38184`, proven red by `make mutate`), three declined with reasons, live ACs deferred to #1668. Codex and CodeRabbit sent capacity notices.
- Staging drill for #2991: the 09:56Z run reported `FIRING after 3.0m` from the 09:30Z instance, which the pre-check missed because staging Grafana had restarted at 09:54Z; filed as #2998 (OBS-044). The 12:44Z run refused correctly (a residue claim of unknown origin kept the rule firing; noted on #2998). A third run is scheduled once the instance resolves.
- Staging slot: lent to the console lane 10:24Z-10:26Z on request, taken back, returned to master 12:45Z while the alert resolves.
- 15:16Z-16:00Z: a clean staging drill of #2991 (`d4c38184`), started after 20 quiet minutes on each side of the slot change: `FIRING after 44.1m`, longer than `for: 15m`, so it is evidence. Slot returned to master at 16:00Z. The two earlier fast firings (3.0m, 1.0m) are recorded on #2998 as false greens.
- #2991: CodeRabbit's second review triaged (summary now names log ingestion as the second cause, `aff1d4a7`; the 30m/`for: 0m` proposal declined). **Not merged**: no prod notice has been delivered since #2987 synced at 09:32Z (prod had nothing firing all day), so the envelope's "read the next prod notice before the next prod-bound merge" is unmet. Ready for the operator.
- #2921 set Blocked on AC3 (journal read on ace2), with the two options on the issue.
- Worktrees removed: `feat-obs-042-notice-contract`, `fix-ai-030-vault-mirror-fail-fast` (forced past its generated inventory). The launch worktree `feat-gitops-003-verify-staging` stays.

## End state

- Merged: #2987 (notice contract), #2992 (vault mirror fail-fast).
- Open and ready: #2991 (PVC split + emitter-window guard), held for a prod notice.
- Filed: #2998 (OBS-044, drill false green after a Grafana restart).
- Board: #2929, #1668, #1320, #2924 In Progress; #2921 Blocked.
