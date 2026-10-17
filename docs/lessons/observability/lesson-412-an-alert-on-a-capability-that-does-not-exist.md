---
id: lesson-412-an-alert-on-a-capability-that-does-not-exist
type: lesson
status: active
created: "2026-09-01"
owner: manu
category: observability
tags: [kubelab, observability, alerting, security, crowdsec, loki]
---

# An alert on a capability the system does not have fires always or never, and fixing its query only picks which

**Context**: A Slack alert, "CrowdSec automated perimeter IP ban surge — >5 bans
in 10m ... Active port scan, brute force, or L7 exploit attempt mitigated on
ingress", had been arriving since 2026-08-23. The operator could not tell
whether it was good news or bad, and asked where to look.

**Problem**: Three layers, and only the first is the one you would guess.

The alert's LogQL counted **log lines**, not bans:

```logql
sum(count_over_time({container="crowdsec"} |~ "(?i)(ban|decision|blocked|remediation)" [10m]))
```

The CrowdSec bouncer polls the LAPI every 60 seconds. That poll is logged as
`GET /v1/decisions/stream`, and `(?i)decision` matches the URL. Measured from
Loki's own query log, the expression returned `post_filter_lines=20` on every
five-minute evaluation, against a `> 5` threshold. Permanently firing, by
construction, on a completely idle CrowdSec.

The second layer: `cscli decisions list` reported "No active decisions", which
looks like confirmation — but it hides CAPI decisions by default.
`--origin CAPI` showed ~4,500 standing community bans. So the honest statement
was never "nothing is banned"; it was "nothing is *locally* detected", because
`acquis.yaml` points at an emptyDir nobody writes to and Acquisition Metrics is
an empty table. That is a documented posture (LAPI-only), not a fault.

The third layer is the one that mattered. `Bouncer Metrics: dropped requests`
was **0** across seven days — with thousands of blocklisted IPs including Tor
exit nodes, on a public ingress, across 13 routes carrying the bouncer
middleware. A full blocklist and an empty enforcement counter are only
compatible if the comparator never receives the input it compares. klipper-lb
MASQUERADEs every source IP before Traefik sees it (#1067), and the bouncer's
`clientTrustedIPs` is the Tailscale CIDR, not the pod CIDR — so it checks
`10.42.0.x` against a list of public addresses, at full effort, forever
returning "not banned".

**Solution**: Deleted the rule rather than correcting its query, and recorded
why in `infra/k8s/base/kustomization.yaml` where the file was generated from.
A corrected query would have had no true-positive path either: with no local
acquisition there is no ban *surge* to detect, since CAPI delivers its
blocklist in bulk on a schedule. The fix would have converted an alert that
always fires into one that never fires, and the second failure is quieter, not
better.

The prerequisite chain was written down instead: #1067 (real client IP at L4)
→ #704 (trust `CF-Connecting-IP` on proxied hosts) → the bouncer bites →
alerting on `dropped requests` has something to be true about. Note the order:
#704 looks like the lighter path and is not, because trusting a forwarded
header requires trusting a peer IP that *every* request shares under
klipper-lb, so a direct-to-origin request could forge its own identity. #1067
is the prerequisite for #704, not a heavier alternative to it.

**Rule**: Before writing or believing an alert, verify the enforcement path it
describes actually exists and can act. An alert is a claim that some capability
produced an observable event; if the capability is absent, the metric is
measuring something else — usually the component's own idle chatter. The tell
is a firing state that never resolves, or a counter of "things prevented" that
sits at zero while the input that should trigger it is abundant. Check the
second number, not just the first: a full blocklist with zero blocks is a
broken comparator, never a quiet internet.

Corollary for log-derived alerting, which is all this stack has (Vector → Loki
→ Grafana, no Prometheus): `count_over_time` over a free-text filter measures
**verbosity**, and a healthy idle component's verbosity is constant and
non-zero. Match on structure — a parsed field, a line shape unique to the event
— never on a word that also appears in a URL.

This is the third of its family: [[lesson-386-the-alert-that-was-never-true-and-the-one-nobody-read]]
made the same point about a channel nobody reads, and OBS-018 (#1377) was a PVC
alert that "has fired since the day it shipped and has never been true". The
recurring cause is that an alert's query is reviewed against its own syntax
rather than against a moment when it should be silent.

**Tags**: `#alerting` `#crowdsec` `#loki` `#logql` `#pr-1526`
