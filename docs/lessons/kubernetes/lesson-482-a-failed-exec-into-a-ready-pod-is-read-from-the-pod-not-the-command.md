---
id: lesson-482-a-failed-exec-into-a-ready-pod-is-read-from-the-pod-not-the-command
type: lesson
status: active
created: "2026-09-28"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes, n8n, kubectl, memory]
---

# A failed `kubectl exec` into a Ready pod is explained by the pod's record, not by the command's error

**Context**: #1863 (TOOL-086). `make import-n8n` failed on one workflow of four,
intermittently. The ticket's hypothesis was the tool's own restart after each
workflow: the next `kubectl exec deploy/n8n` landed on the pod being terminated.
#1892 removed the per-workflow restart and made every exec target a named pod
that is Running, Ready and not being deleted.

**Problem**: The failure recurred with both fixes in place. In run 3 of 3, the
exec went into a pod the resolver had just judged Ready. It answered `command
terminated`, the retries answered `error: Internal error`, and a later exec found
no Ready pod at all. Then the remaining workflows imported normally. The
container had died and come back inside the same pod, which no pod-selection
rule can prevent. `kubectl exec`'s own error is identical for a container killed
mid-command and for a command that failed on its own, so the output could not
say which one this was.

A second fact is easy to miss: `n8n import:*` does not talk to the running server.
It starts **another n8n process in the same container**, under the same cgroup
limit. Sampled with `kubectl top` during three imports, the container reached
500Mi of its 512Mi limit and 1690m of 2000m CPU (#1902).

**Solution**: after a failed exec, the tool lists the pod again and logs its
`containerStatuses`: restart count, and the last termination's reason, exit code
and time (`_pod_record` in `toolkit/features/n8n_import.py`). `OOMKilled/137`,
a liveness kill (`Error/137` with a restart) and a genuine import error with no
restart now read differently. The memory limit itself is #1902, sized from that
record rather than from the guess.

**Rule**: when an exec into a pod fails, read the pod before you read the
command: `restartCount`, `lastState.terminated`, and `deletionTimestamp`. "Ready
when chosen" does not mean "alive for the whole command". Read immediately,
kubelet may not have recorded the death yet, so `restarts=0` means "too early",
not "survived". A CLI that runs inside the app's container, such as `n8n
import`, `gitea admin` or `rails runner`, spends the app's memory limit, so size
the limit for the app plus its CLI.

**Tags**: `#n8n` `#kubectl` `#issue-1863` `#pr-1892` `#issue-1902` `#issue-1009`
