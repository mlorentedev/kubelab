---
id: lesson-386-the-alert-that-was-never-true-and-the-one-nobody-read
type: lesson
status: active
created: "2026-08-24"
owner: manu
category: observability
tags: [kubelab, observability, alerting, loki, grafana, incident]
---

# A channel with a permanent false positive is not a channel anyone reads

**Context**: on 2026-08-24 the Argo CD hub was preempted and `argo.kubelab.live`
went down. Detection worked, and worked well:

| Local time | Event |
|---|---|
| 18:13:39 | instance preempted |
| **18:17:32** | Uptime Kuma: `Services · Auth · Argo CD` **Down, 504** |
| **18:17:45** | Uptime Kuma: `Infra · VPN · GCP1 Tailscale` **Down** |

Four minutes, two independent monitors, both delivered to the alerts channel. The
second even named the fault in its body — `PING gcp1.kubelab.internal
(100.64.0.13) ... 100% packet loss`, which is the dead address.

**Problem**: nobody acted for 35 minutes. The outage was found by an operator
tripping over an SSH timeout in an unrelated disk benchmark.

The channel those correct alerts arrived in already contained
`PersistentVolumeClaim unbound or failed`, firing from **two** Grafanas since the
day it shipped, while all 20 PVCs in both clusters were `Bound`. Its cause is its
own small lesson: the watcher emitted `healthy: (.status.phase == "Bound")` —
jq's `==` yields a JSON **boolean** — and the rule read it with LogQL
`| unwrap healthy`, which needs a float. The sample was dropped, the query
returned no data, and `noDataState: Alerting` did the rest. The sibling metric in
the same file was fine because bash `$(( ))` returns 0/1, so only half the file
misbehaved and the emitter was never suspected.

Its summary asserted a cause it had never checked: *"a storage backend outage or
capacity ceiling is preventing stateful workloads from provisioning."*

**Solution**: emit a number, and make the text admit both reasons the rule can
fire. `noDataState: Alerting` stays — a watcher that goes quiet should be noticed
— but a rule that fires for two reasons must not name one of them with
confidence. A static guard now checks the *joint*: for every `| unwrap <field>`
in the rules, no watcher may emit that field as a boolean. Neither side is wrong
alone, which is why review passed it and why the test has to span both files.

**Rule**: the cost of a false positive is not the notification, it is the
**next** notification. Alert fatigue is usually described as a volume problem; it
is cheaper to think of it as a credibility problem with one arithmetic property —
a channel carrying a permanently-firing alert has an audience of nobody, and the
first real page is delivered into that silence. Treat a never-true alert as an
outage of the alerting system, because that is what it is.

**Tags**: `#alerting` `#grafana` `#loki` `#logql` `#uptime-kuma` `#issue-1377`
