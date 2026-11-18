---
id: "kubelab-runbook-resume-daily-pipeline"
type: runbook
status: active
tags: [runbook, kubelab, resume, cronjob, alerting]
created: "2026-11-17"
owner: manu
---
# resume's daily pipeline

> resume runs `resume daily` once a day as the CronJob `resume-daily`, rendered from
> its contract snapshot (`infra/config/products/contracts/resume.yaml`). Staging only
> for now (RES-HOST-001, #2366).

## First deploy to an environment

Argo CD renders resume as soon as its product entry merges. Its Secrets reach the
cluster only through `apply-secrets` (#3645), so until that runs the pod sits in
`ImagePullBackOff` (`FailedToRetrieveImagePullSecret pull-ghcr-io`).

1. Check the vault: `toolkit secrets audit --env <env>` lists no missing key for
   resume (`apps.platform.resume.llm_api_key`, `ghcr.pull_token`, the notify
   bearer). Set a missing value in the vault its catalog entry names, and land
   the encrypted file through a PR. `ghcr.pull_token` is shared, so set it with
   `--env common`. A per-environment copy would shadow every later rotation.
   resume's own keys take `--env <env>`:
   `toolkit secrets set <key> --env <env> --stdin`.
2. From a tree at `master`, preview the apply with
   `make apply-secrets ENV=<env> DRY_RUN=1`. Only resume's Secrets
   (`resume-secrets`, `pull-ghcr-io`) should show as created, plus
   `sealed-secrets-key` on the first apply, and the only restart should be
   `deployment/resume`. Stop if anything else changes.
3. Apply with `make apply-secrets ENV=<env>`. The first image pull can outlast
   the 180s readiness wait, in which case the run exits 1 although every Secret
   was applied (#3652). Confirm against that same environment's cluster:
   `kubectl --kubeconfig ~/.kube/kubelab-<env>-config -n kubelab rollout status deploy/resume`.
   Every `kubectl` command below takes the same `--kubeconfig`.
4. Acceptance:
   - The pod is `Ready` on `/healthz`.
   - An `operator` user gets 403 and a `superadmin` user gets the board. This is
     checked by hand for now (#3653).
   - From the pod, TCP 443 to a public host connects. TCP 443 to a private
     address that is known to listen (the node's traefik VIP) is refused. Public
     port 80 is blocked, and `n8n:5678` connects. Run the same private connect
     from a pod without an egress policy as the control: a refusal on a closed
     port proves nothing.
   - The first scheduled run prints `daily: ok`, and the no-success alert
     returns to Normal.

Rollback: to take resume out of an environment, revert the product entry's PR.
Argo then prunes the Deployment and the CronJob and keeps the PVC (`Prune=false`).
Argo does not manage the Secrets, so they stay behind: delete `resume-secrets` by
hand, and keep `pull-ghcr-io` only while another product still pulls from ghcr.
Do not run `apply-secrets` for that environment until the entry is gone from the
Secret mappings in `toolkit/features/k8s_secrets.py`, or it recreates them.

## No-success alert

The rule `reshost001-resume-daily-no-success` fires when no `daily: ok` line from
resume's daily Job reached Loki in the last 26 hours. `resume daily` prints that
line last, on stderr, and only when it exits 0. In staging the alert archives
(`apprise-log`) and never pages.

1. Read the last runs:
   `{container="daily", pod=~"resume-daily-.+"}` over the last two days in Grafana
   Explore. A failed run prints `daily: started <time>` and then names its step:
   `daily: <step> failed`, or `daily: evaluate failed (<reason>)`.
2. No lines at all means no Job reached its container. Read the CronJob and its
   Jobs with `kubectl -n kubelab get cronjob resume-daily` and
   `kubectl -n kubelab get jobs -l app.kubernetes.io/name=resume`, then the pod's
   events: an image pull refused (the `pull-ghcr-io` Secret), or a missing
   `resume-secrets` key, stops it before it logs.
3. A step that failed: fix the cause, then let the next scheduled run clear the
   alert. A finished Job is kept for a day (`ttlSecondsAfterFinished`).

A run is never replayed by hand to silence the alert: the next scheduled run is the
check, and a manual Job is an acceptance step of the first deploy only.
