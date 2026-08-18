---
id: lesson-343-elapsed-time-inside-a-long-session-is-not-a-m
type: lesson
status: active
created: "2026-08-09"
owner: manu
tags: [kubelab, lesson, kubernetes, kubelet, diagnosis, clock-skew, false-alarm]
---

# Elapsed time inside a long session is not a measurement — pull the authoritative clock

**Context:** Prod's homepage pod showed `ContainerCreating` with `FailedMount ... configmap "homepage-config-t88c6mm6ch" not found` logged 75 s earlier, while `kubectl get cm` showed that exact ConfigMap present. Pod age read `44m`.

**Problem:** I read it as a live anomaly — a ConfigMap that exists and a kubelet that cannot see it — and was one step from reporting a prod incident. The reasoning depended entirely on an unstated assumption: that "44 minutes old" and "created a while ago" sat on the same timeline as my sense of how long the session had been running. In a long session full of slow operations, that intuition drifts badly.

**Solution:** Pulled the cluster clock alongside the object's `creationTimestamp`: now `00:26:43Z`, ConfigMap created `00:25:41Z`. It was **62 seconds old**, and the last mount failure predated its existence. No anomaly at all — a peer's deploy had just created it, and kubelet mounted it on the next retry.

**Rule:** A timestamp in an event is only interpretable against the clock of the system that wrote it. Before concluding anything is "stuck", fetch the authoritative `now` and subtract; never compare a cluster timestamp against a felt sense of elapsed time. The tell is any sentence of the form "it has been X minutes and still…" where X was estimated rather than computed.

**Tags:** `#kubernetes` `#kubelet` `#diagnosis` `#clock-skew` `#false-alarm`

---
