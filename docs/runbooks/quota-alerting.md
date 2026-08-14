---
id: "kubelab-runbook-quota-alerting"
type: runbook
status: active
tags: [runbook, kubelab, quota, resourcequota, alerting, grafana]
created: "2026-08-14"
last_tested: "2026-08-14"
owner: manu
---
# Namespace quota utilization high — what the alert means and what to do

> Triage for the **Namespace quota utilization high** alerts (OBS-010, #918).
> Two independent rules, one per dimension: `requests.memory` and
> `limits.memory`. Either firing means the `kubelab` `ResourceQuota` (IDP-031,
> #811) has crossed 80% of its hard ceiling and stayed there for 5 minutes.

## Why this alert exists

The `ResourceQuota` itself can only admit or reject a pod at the moment it is
scheduled — it has no concept of "getting close." Before this alert, the first
signal anyone got that the namespace was running out of room was a failed
deploy, at the worst possible time to discover it.

This alert exists to give an earlier, non-blocking signal. It does not enforce
anything and does not stop a deploy — it only tells you the room to grow
without hitting rejection is shrinking.

## What you will receive

Routed the same way OBS-007's ACME alert is — prod to the push channel
(`page`), staging to the archive channel (`log`):

```text
kubelab · page · firing: Namespace quota utilization high (limits.memory)
kubelab namespace limits.memory utilization crossed 80% of its ResourceQuota
ceiling (IDP-031/#811) — the load-bearing dimension, 5.7% headroom by design.
Deploys are still succeeding, but the room to grow the namespace without
hitting admission rejection is shrinking.
Started: 2026-08-14 01:10:00 +0000 UTC
Source: https://grafana.kubelab.live/
```

You may receive one or both rules firing independently — they are unrelated
alerts, not a combined condition.

## Triage

### 1. Confirm it against the live quota, not just the alert text

```bash
kubectl --kubeconfig ~/.kube/kubelab-<env>-config \
  describe resourcequota kubelab-quota -n kubelab
```

Read `Used` against `Hard` for both `requests.memory` and `limits.memory`
directly — the alert's own percentage is computed by `quota-watcher`
(`infra/k8s/base/services/quota-watcher.yaml`), and a live read is the
independent check.

### 2. Distinguish real growth from a persistent surge

IDP-031's own measured deploy-restart surge peaks around 87.5% of
`limits.memory` for well under a minute — this alert's 5-minute `for:` window
already filters that out (see "What this alert does NOT cover" below). If it
fired, the elevated reading held for at least 5 minutes, which a routine
restart cannot do. That means either:

- **Real growth** — a new workload, a raised resource request, or a memory
  leak holding a pod above its normal footprint. Check what changed:
  `kubectl get pods -n kubelab -o json | jq -r '.items[] | select(.status.qosClass != "BestEffort") | "\(.metadata.name) \(.spec.containers[].resources.requests.memory // "-")"'`
  and compare against the last known-good baseline in IDP-031's
  `verification.md` (2.312 Gi requests / 4.875 Gi limits, both environments,
  2026-08-12).
- **A leak recovering slowly** — if one specific pod's usage keeps climbing
  and does not recover after a restart, that is a leak in that workload, not a
  namespace-capacity problem. Restarting it is a stopgap, not a fix.

### 3. Decide, don't reflexively raise the ceiling

The whole reason this alert exists instead of a tighter quota is to keep
detection and enforcement separate (see proposal.md → Why, and #912). Raising
`infra/k8s/base/governance/resourcequota.yaml`'s `hard:` values is a real
option, but it is a capacity decision that should follow from what step 2
found — not a reflex to make the alert stop firing.

## What this alert does NOT cover

It watches **utilization of the existing ceiling**, not whether the ceiling
itself is still the right number, and not CPU (see IDP-031/proposal.md — CPU
is compressible, out of scope on the same evidence standard). It also cannot
distinguish "one big legitimate workload" from "many small ones adding up" —
both cross 80% the same way. Step 2 above is where that distinction gets made,
by a human, not by the rule.

It is silent about `kube-system` entirely — OBS-009 gave that namespace a
`LimitRange` floor but deliberately no `ResourceQuota` (a system namespace
cannot safely reject at admission), so there is no utilization number there to
alert on.

## Testing this alert

Two behaviors were verified by deliberate, measured exercises in staging
rather than waited for — see `specs/OBS-010-quota-utilization-alert/verification.md`
for the full evidence:

**A routine surge does not fire it.** Reproduced IDP-031's own drill (full
`make deploy-k8s ENV=staging` + `rollout restart` of every deployment in
`kubelab`), captured a mid-restart reading with `quota-watcher` triggered on
demand, and confirmed `limits.memory` peaked at 88.39% — comfortably over the
80% threshold — while the rule stayed `inactive` throughout, because the
surge could not hold for the required 5 minutes.

**A broken emitter fires it, on purpose.** `noDataState`/`execErrState` are
`Alerting`, the inverse of OBS-007's ACME rule — silence here means
`quota-watcher` stopped running, not that the namespace is healthy. To
reproduce, **staging only, never prod**:

```bash
kubectl --kubeconfig ~/.kube/kubelab-staging-config \
  patch cronjob quota-watcher -n kubelab -p '{"spec":{"suspend":true}}'

# Wait past one for: window with no fresh log lines (at least 5-10 minutes),
# then confirm via the rules-state endpoint. The endpoint needs Basic auth --
# busybox wget's -qO- alone gets a 401, and it has no --user/--password flags,
# so the header has to be built by hand (measured 2026-08-14):
USER=$(kubectl --kubeconfig ~/.kube/kubelab-staging-config get secret grafana-admin -n kubelab -o jsonpath='{.data.admin-user}' | base64 -d)
PASS=$(kubectl --kubeconfig ~/.kube/kubelab-staging-config get secret grafana-admin -n kubelab -o jsonpath='{.data.password}' | base64 -d)
AUTH=$(printf '%s:%s' "$USER" "$PASS" | base64 -w0)
kubectl --kubeconfig ~/.kube/kubelab-staging-config exec -n kubelab deploy/grafana -- \
  wget -qO- --header="Authorization: Basic $AUTH" http://localhost:3000/api/prometheus/grafana/api/v1/rules \
  | grep -o '"name":"Namespace quota utilization high[^"]*","state":"[a-z]*"'

# Un-suspend and confirm it returns to inactive once fresh data arrives.
kubectl --kubeconfig ~/.kube/kubelab-staging-config \
  patch cronjob quota-watcher -n kubelab -p '{"spec":{"suspend":false}}'
```

Do not run the suspend step against prod — it disarms real quota visibility
for the duration of the test.

## Related

- Spec: `specs/OBS-010-quota-utilization-alert/`
- **IDP-031 (#811)** — the `ResourceQuota` this alert watches, and the source
  of the surge measurement this alert's `for: 5m` is sized against
- **OBS-007 (#799)** — the Apprise/Loki delivery path this alert reuses
  (contact points, tiers, notification policy) rather than rebuilding
- **OBS-009 (#924)** — the sibling `kube-system` `LimitRange`, deliberately
  without a `ResourceQuota` and so without an alert of this kind
- `docs/runbooks/acme-alerting.md` — the sibling runbook this one's structure
  follows
