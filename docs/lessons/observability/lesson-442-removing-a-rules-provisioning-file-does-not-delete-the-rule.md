---
id: lesson-442-removing-a-rules-provisioning-file-does-not-delete-the-rule
type: lesson
status: active
created: "2026-09-03"
owner: manu
category: observability
tags: [kubelab, observability, grafana, alerting, provisioning, argocd, false-green, pr-1610]
---

# Removing a rule's provisioning file is not deleting the rule — Grafana keeps evaluating it, and every repo-side signal says it is gone

**Context**: #1529 retired the `obs015-crowdsec-ban-surge` alert (lesson-386) by deleting `security-rules.yaml` from the Grafana alerting overlay. Ten days later the alert was still arriving in Slack from both clusters. #1583 AC2 asked whether Grafana was still evaluating it.

**Problem**: Grafana file provisioning is *additive*. A rule it has once loaded lives in its own database and goes on being evaluated after the file that created it disappears. Nothing the repo controls can show this: the file is gone, the rendered ConfigMap is clean, Argo CD reports Synced/Healthy, and prod's pod had even restarted without the file. Measured on both clusters on 2026-09-04:

```
rule_uid=obs015-crowdsec-ban-surge org_id=1 fromAlert=true
  query="sum(count_over_time({container=\"crowdsec\"} |~ \"(?i)(ban|decision|blocked|remediation)\" [10m]))"
logger=ngalert.sender.router msg="Sending alerts to local notifier" count=1
```

Diffing the uids Grafana evaluates against the uids the overlay declares gave exactly one orphan — this one. Everything declared was right; the retention was the only explanation left, and it was confirmed rather than assumed.

**Solution**: Grafana's own mechanism for the second operation is a `deleteRules` provisioning entry, checked against the docs for the running version (13.0.2):

```yaml
apiVersion: 1
deleteRules:
  - orgId: 1
    uid: obs015-crowdsec-ban-surge
```

Verified live on staging (Argo CD repointed at the branch per lesson-256, Grafana restarted onto the new ConfigMap): `deleted-rules.yaml` present in the pod, log mentions of the uid **78 before, 0 after**, five other rules still evaluating in the same window — so the rule is gone, not merely quiet. Three guards pin it: a uid may not be both declared and deleted (anti-vacuity floor on the derived set, lesson-416); the retired uid must stay declared as a floor, never read from the file under test; and the deletion is asserted in the *render*, because a generator entry is exactly what can be dropped with no visible failure. Removing the generator entry turns both environments' render tests red.

**Rule**: "Retire a provisioned object" is two operations — stop declaring it, and tell the system to forget it — and only the first is visible from the repo. When a retired alert keeps firing, read what the target *evaluates*, not what the repo *declares*; a Synced overlay proves the declaration, never the target's state. `deleteRules` entries are permanent: a missing rule costs nothing on every start, while removing the entry re-arms the failure for any instance restored from an older backup.

**Tags**: `#grafana` `#alerting` `#provisioning` `#argocd` `#false-green` `#pr-1610` `#1583`
