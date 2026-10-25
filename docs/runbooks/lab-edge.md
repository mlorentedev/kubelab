# Lab edge

The RPi4 is the lab's edge (ADR-075): its built-in radio is the lab Wi-Fi, and a
USB adapter is the uplink to whatever network the site offers. This runbook
starts with the alerts prod raises about it; the site procedures (bring-up,
captive portal, uplink profiles) are added with NET-005 task 35.

## Edge alerts

Prod's `edge-watcher` CronJob (`infra/k8s/base/services/edge-watcher.yaml`)
makes one TCP connect every 5 minutes to each target in
`infra/k8s/base/services/edge-watcher/targets.txt`: the edge, and every
always-on node behind it. The list is generated from `networking` in
`common.yaml` by `make sync-edge-watcher-targets`. Each run logs one line per
target:

```json
{"metric":"edge_probe","namespace":"kubelab","node":"rpi4","up":1}
```

The edge cannot page about its own uplink while that uplink is down, so this
probe runs where the edge's failure does not reach. Read the lines first:

```bash
toolkit obs logs --env prod -q '{container="edge-watcher"} |= "edge_probe"' --since 1h
```

### Edge target down

`net005-edge-target-down` fires when a target has answered no probe for 10
minutes. One answer clears it.

- **Every target down**: the edge's uplink is the suspect, since the nodes
  behind it reach the tailnet through it. The uplink adapter is unplugged, the
  site's network is down, or a captive portal holds it (before the first login,
  or after the access expired). From a client on the lab Wi-Fi, check whether
  the site's portal page answers.
- **One target down while the others answer**: that node is down or off the
  tailnet. For rpi3, Uptime Kuma's own heartbeats stop too.
- **No lines at all**: see [Edge watcher silent](#edge-watcher-silent). The
  rule pages on no data as well.

### Edge watcher silent

`net005-edge-watcher-silent` fires when no `edge_probe` line arrived for 15
minutes, three runs. The probe prints a line for every target on every run,
so silence is the watcher, never the edge, and the edge's state is unknown.

```bash
kubectl get cronjob,jobs -n kubelab | grep edge-watcher
```

A Job that never started (image pull, a suspended CronJob, a CronJob never
deployed), or a Job that failed: the probe exits 1 without a line when its
targets file is missing or empty, and says why on stderr.
